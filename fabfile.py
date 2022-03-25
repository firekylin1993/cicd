#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import yaml
import requests
from fabric.api import task, local, abort, warn, settings

# 部署参数(以项目根目录作为根目录)
ci_conf = {
    # 要部署到的K8S集群名（线上环境不进行部署）
    "deployCluster": "test",
    # 要部署到的K8S集群命名空间（线上环境不进行部署）
    "deployNamespace": "develop",
    # 部署时使用的yaml模板文件
    "yamlPath": "_ci/template.yaml",
    # 预发布环境使用的环境变量文件路径
    "preEnvPath": "env/pre.env",
    # 线上环境使用的环境变量文件路径
    "prodEnvPath": "env/prod.env",
    # 本地部署配置路径
    "configPath": "ciconf.yaml",
    # 构建用的dockerfile路径
    "deployDockerFilePath": "_ci/Dockerfile",
    # hook
    "jenkinsTriggerUrl": "http://project-service-project.t.k8ss.cc/api/project-service/v1/jenkins-event",
}

# 常量
# 获取gitInfo时用到的git命令
git_shell = {
    "currentBranch": "git name-rev --name-only HEAD",
    "currentCommitID": "git rev-parse HEAD",
    "currentTag": "git describe --tags --exact-match $(git rev-parse HEAD)",
    "latestLog": "git log -1"
}

# 全局变量
git_info = {
    "commitID": None,  # git 提交ID
    "tag": None,  # git tag
    "branch": None,  # git branch
    "version": None,  # 当前版本号
    "merge_approver": list(),  # merge请求批准人员邮箱列表
    "trigger_user": None  # 触发用户邮箱
}

# 环境变量
env_dict = {}

# 任务列表


@task
def build():
    read_conf()
    get_tag()
    sonar_scanner()
    make_tmpimg()
    push_img()
    git_remote_tag()
    clean_img()


@task
def k8sdeploy():
    read_conf()
    create_yaml()
    if not git_info["branch"] == "master":
        deploy_yaml()


@task
def all():
    read_conf()
    get_tag()
    sonar_scanner()
    make_tmpimg()
    push_img()
    git_remote_tag()
    clean_img()
    create_yaml()
    if not git_info["branch"] == "master":
        deploy_yaml()


@task
def testdeploy():
    read_conf()
    get_tag()
    sonar_scanner()
    make_tmpimg()
    clean_img()
    create_yaml()
    test_deploy_yaml()


@task
def jobstart():
    get_env()
    project_center_hook("start", "start")


@task
def jobstop(status):
    get_env()
    project_center_hook("stop", status)


@task
def localsonarscanner():
    read_conf()
    get_tag()
    sonarscanner()

# 子任务

# 项目配置中心通报hook


def project_center_hook(post_type="start", status="unkown"):
    get_env()
    requests.post(ci_conf["jenkinsTriggerUrl"], json={
        "post_type": post_type,
        "status": status,
        "deploy_key": env_dict["deploy_key"],
        "cur_branch": env_dict["cur_branch"],
        "auto_triggered": env_dict["isAutoTrigger"],
        "time": str(time.time()),
        "data": dict({
            "BUILD_URL": env_dict["BUILD_URL"],
            "BUILD_TAG": env_dict["BUILD_TAG"],
            "GIT_COMMIT": env_dict["GIT_COMMIT"],
            "JOB_URL": env_dict["JOB_URL"],
            "RUN_CHANGES_DISPLAY_URL": env_dict["RUN_CHANGES_DISPLAY_URL"],
            "RUN_DISPLAY_URL": env_dict["RUN_DISPLAY_URL"],
            "JOB_NAME": env_dict["JOB_NAME"],
            "JOB_BASE_NAME": env_dict["JOB_BASE_NAME"],
            "GIT_BRANCH": env_dict["GIT_BRANCH"],
            "GIT_URL": env_dict["GIT_URL"],
            "JOB_DISPLAY_URL": env_dict["JOB_DISPLAY_URL"],
            "BUILD_NUMBER": env_dict["BUILD_NUMBER"],
        })
    })

# 读取构建配置文件（当 ci_conf.projectCenterUrl 配置存在时，从远程获取配置，否则读取本地）


def read_conf():
    print("---Stage: read ci config from config file---")
    global ci_conf
    get_env()
    # if ci_conf["projectCenterUrl"]:
    #     resp = requests.get(
    #         ci_conf["projectCenterUrl"],
    #         timeout=10,
    #         params={
    #             "deploy_key": env_dict["deploy_key"]
    #         },
    #     )
    #     proj_conf = resp.json()
    # else:
    #     with open(ci_conf["configPath"], "r") as proj_conf_file:
    #         proj_conf = yaml.load(
    #             proj_conf_file,
    #             Loader=yaml.SafeLoader
    #         )
    with open(ci_conf["configPath"], "r") as proj_conf_file:
        proj_conf = yaml.load(
            proj_conf_file,
            Loader=yaml.SafeLoader
        )
    print(proj_conf)
    if isinstance(proj_conf, dict):
        for key, values in proj_conf.items():
            ci_conf[key] = values
    else:
        abort("配置文件不正确")

# 获取自定义构建脚本并执行


def get_deploy_script():
    print("---Stage: get deploy script from config center---")

# 从本地git仓库获取标签信息


def get_tag():
    print("---Stage: get image tag from git---")
    git_current_branch = os.popen(git_shell["currentBranch"]).read().strip()
    git_current_commit_id = os.popen(
        git_shell["currentCommitID"]).read().strip()
    git_latest_log = os.popen(git_shell["latestLog"]).read()
    if git_current_branch == "master":
        matcher1 = re.search(
            re.compile(
                r"Merge branch 'rb-([0-9]{1,}.[0-9]{1,}.[0-9]{1,})' into 'master'"),
            git_latest_log
        )
        if not matcher1:
            tag = git_current_commit_id
            warn("当前分支为master，但找不到rb分支合并记录，无法使用版本号打tag，将使用commitID打tag")
        else:
            tag = matcher1.group(1)
    elif git_current_branch.find("rb-", 0) != -1:
        tag = git_current_branch + "_" + git_current_commit_id[0:8]
    else:
        tag = git_current_commit_id
    global git_info
    git_info = {
        "commitID": git_current_commit_id,
        "tag": tag,
        "version": git_current_branch + "_" + git_current_commit_id[0:8],
        "branch": git_current_branch
    }
    print(git_info)

# 创建临时镜像


def make_tmpimg():
    print("---Stage: make docker image with a temp name---")
    local("docker build --build-arg VERSION_TAG=%s --build-arg COMMIT_ID=%s  --rm -f %s -t wsmtmpdocker:%s ." %
          (git_info["version"], git_info["commitID"][0:8], ci_conf["deployDockerFilePath"], git_info["commitID"]))

# 推送镜像version


def push_img():
    print("---Stage: tagged temp image and push it to harbor---")
    temp_img = "wsmtmpdocker:%s" % (git_info["commitID"])
    docker_push(temp_img, "%s:%s" % (ci_conf["harbor"], git_info["tag"]))
    if git_info["branch"] == "master":
        docker_push(temp_img, "%s:latest" % (ci_conf["harbor"]))

# 清理临时镜像


def clean_img():
    print("---Stage: clean temp image---")
    if git_info and git_info["commitID"]:
        with settings(warn_only=True):
            local("docker rmi -f  wsmtmpdocker:%s" % (git_info["commitID"]))

# 远程给git仓库打tag


def git_remote_tag():
    if git_info["branch"] == "master":
        requests.post(
            "https://code.avlyun.org/api/v4/projects/%s/repository/tags?tag_name=%s&ref=master" % (
                ci_conf["gitPath"].replace("/", "%2F"),
                git_info["tag"].replace(".", "%2e")
            ),
            headers={
                "PRIVATE-TOKEN": "CZD3q7SPUEduXmfiAEgF"
            }
        )

# 读取yaml模板文件并创建部署用yaml


def create_yaml():
    print("---Stage: creat deploy yaml file---")
    # 读取yaml模板文件
    with open(ci_conf["yamlPath"], "r") as tmpYamlFile:
        tmp_yaml = tmpYamlFile.read()
    # 替换yaml模板文件中的一些内容
    tmp_yaml = tmp_yaml.replace("$replace_tag", git_info["tag"])
    tmp_yaml = tmp_yaml.replace("$replace_deploy_time", str(time.time()))
    tmp_yaml = tmp_yaml.replace(
        "$replace_project_name", ci_conf["projectName"])
    tmp_yaml = tmp_yaml.replace("$replace_harbor", ci_conf["harbor"])
    # 读取环境变量配置文件
    if git_info["branch"] == "master":
        env_file_path = ci_conf["prodEnvPath"]
    else:
        env_file_path = ci_conf["preEnvPath"]
    # 处理并替换yaml模板文件中的环境变量
    env_yaml = ""
    env_temp = "{\"name\": \"$env_name\", \"value\": \"$env_value\"},"
    if not(os.path.exists(env_file_path) and os.path.isfile(env_file_path)):
        env_temp = ""
    else:
        with open(env_file_path, "r") as envFile:
            env_conf_lines = envFile.readlines()
            # 一行一行的读取配置文件
            for i in env_conf_lines:
                i = i.strip()
                # 处理掉空行或者以#号开头的注释行
                if i and (not i.startswith("#")):
                    i = i.split("=", 1)
                    env_yaml = env_yaml + \
                        env_temp.replace("$env_name", i[0]).replace(
                            "$env_value", i[1])
    tmp_yaml = tmp_yaml.replace("$replace_env", env_yaml.strip(","))
    print(tmp_yaml)
    # 输出yaml文件
    with open("deploy.yaml", "w") as deployYamlFile:
        deployYamlFile.write(tmp_yaml)

# 部署yaml文件


def deploy_yaml():
    print("---Stage: deploy yaml file to k8s---")
    local("kubectl apply -f deploy.yaml --namespace=%s --context=%s" %
          (ci_conf["deployNamespace"], ci_conf["deployCluster"]))

# 测试yaml部署


def test_deploy_yaml():
    print("---Stage: test deploy yaml file to k8s---")
    local("kubectl apply -f deploy.yaml --dry-run --namespace=%s --context=%s -o yaml" %
          (ci_conf["deployNamespace"], ci_conf["deployCluster"]))

# sonarscanner


def sonar_scanner():
    print("---Stage: sonarscanner---")
    sonar_container = os.popen(
        "docker create --rm --env cur_branch=%s harbor.avlyun.org/c-base/sonar-web-scanner:v3.3.0" % (env_dict["cur_branch"])).read().strip()
    print(sonar_container)
    local("docker cp . %s:/project" % (sonar_container))
    local("docker start %s" % (sonar_container))

# 工具函数

# 判断字符串是否是数字


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass
    return False

# 将环境变量存储到env_dict中


def get_env():
    global env_dict
    env_dict = os.environ

# 推送镜像并删除本地镜像


def docker_push(temp_image, temp_push_image):
    local("docker tag %s %s" % (temp_image, temp_push_image))
    local("docker push %s" % (temp_push_image))
    with settings(warn_only=True):
        local("docker rmi -f %s" % (temp_push_image))

# 同意合并


def approve_merge_request():
    if env_dict["gitlabMergeRequestTargetProjectId"] and env_dict["gitlabMergeRequestIid"]:
        requests.post(
            "https://code.avlyun.org/api/v4/projects/%s/merge_requests/%s/approve" % (
                env_dict["gitlabMergeRequestTargetProjectId"],
                env_dict["gitlabMergeRequestIid"]
            ),
            headers={
                "PRIVATE-TOKEN": "1FSMtzD2JSygww36GPzR"
            }
        )

# 在合并请求界面添加评论


def notes_merge_request(note):
    if env_dict["gitlabMergeRequestTargetProjectId"] and env_dict["gitlabMergeRequestIid"]:
        requests.post(
            "https://code.avlyun.org/api/v4/projects/%s/merge_requests/%s/notes" % (
                env_dict["gitlabMergeRequestTargetProjectId"],
                env_dict["gitlabMergeRequestIid"]
            ),
            headers={
                "PRIVATE-TOKEN": "1FSMtzD2JSygww36GPzR"
            },
            json={
                "body": note
            }
        )

# 本地版代码扫描


def sonarscanner():
    if os.path.isfile("sonar-project.properties"):
        messages = os.popen(
            "/data/disk01/sonar-scanner/bin/sonar-scanner -Dsonar.projectVersion=%s" % (env_dict["cur_branch"])).read().strip().replace("\n", "\n\n")
        print("[sonarscanner_msg]", messages)
        # 获取 task id
        task_id_arr_pattern = re.compile(
            ur'http://sonarqube.avlyun.org/api/ce/task\?id=(.*)', re.M)
        task_id_arr = task_id_arr_pattern.findall(messages)
        if len(task_id_arr) == 1:
            task_id = task_id_arr[0]
            print('task_id:', task_id)
            # 循环获取 task 信息
            task_status = 'PENDING'
            task_analysis_id = ''
            task_component_id = ''
            task_component_key = ''
            while (task_status in ['PENDING', 'IN_PROGRESS']):
                time.sleep(10)
                task_resp = requests.get(
                    "http://sonarqube.avlyun.org/api/ce/task?",
                    timeout=15,
                    params={
                        'id': task_id
                    },
                    headers={
                        'Authorization': 'Basic Nzc1YWZkYzI1NDVhMTNkZWIyYzMwYjY2YjczMGU1YjlmNTZjYjI1Nzo='
                    }
                )
                if task_resp.status_code != 200:
                    break
                # task 信息对象
                task_obj = task_resp.json()
                # task 状态：SUCCESS FAILED CANCELED PENDING IN_PROGRESS
                print("[task_obj]")
                print(task_obj)
                try:
                    task_status = task_obj['task']['status']
                except:
                    print('无法获取扫描任务状态')
                    notes_merge_request(
                        "无法获取扫描任务状态，可能是扫描失败了，需要手动检查: %s" % (env_dict["BUILD_URL"]))
                    return
            try:
                task_status = task_obj['task']['status']
                task_analysis_id = task_obj['task']['analysisId']
                task_component_id = task_obj['task']['componentId']
                task_component_key = task_obj['task']['componentKey']
            except:
                print('无法获取扫描任务ID')
                notes_merge_request(
                    "无法获取扫描任务ID，可能是扫描失败了，需要手动检查: %s" % (env_dict["BUILD_URL"]))
                return

            if (task_status in ['PENDING', 'IN_PROGRESS']):
                print('无法获取扫描任务数据')
                notes_merge_request(
                    "无法获取扫描任务数据，需要手动检查: %s" % (env_dict["BUILD_URL"]))
            elif task_status == 'SUCCESS':
                print('扫描完成')
                # 扫描完成，等待十秒获取项目扫描结果状态
                time.sleep(10)
                # 获取当前扫描结果
                cur_task_state_resp = requests.get(
                    "http://sonarqube.avlyun.org/api/qualitygates/project_status?",
                    timeout=15,
                    params={
                        'analysisId': task_analysis_id
                    },
                    headers={
                        'Authorization': 'Basic Nzc1YWZkYzI1NDVhMTNkZWIyYzMwYjY2YjczMGU1YjlmNTZjYjI1Nzo='
                    }
                )
                cur_task_state_ok = False
                if cur_task_state_resp.status_code == 200:
                    cur_task_state_ok = True
                cur_task_state_obj = cur_task_state_resp.json()
                print("[cur_task_state_obj]")
                print(cur_task_state_obj)
                # 获取项目扫描结果
                time.sleep(1)
                cur_proj_state_resp = requests.get(
                    "http://sonarqube.avlyun.org/api/qualitygates/project_status?",
                    timeout=15,
                    params={
                        'projectId': task_component_id
                    },
                    headers={
                        'Authorization': 'Basic Nzc1YWZkYzI1NDVhMTNkZWIyYzMwYjY2YjczMGU1YjlmNTZjYjI1Nzo='
                    }
                )
                cur_proj_state_ok = False
                if cur_proj_state_resp.status_code == 200:
                    cur_proj_state_ok = True
                cur_proj_state_obj = cur_proj_state_resp.json()
                print("[cur_proj_state_obj]")
                print(cur_proj_state_obj)
                # 拼接评论数据
                cur_task_state_text = ""
                if cur_task_state_ok:
                    cur_task_state_text = '新增代码扫描结果：{0[projectStatus][status]}\n\n    详细数据：\n'.format(
                        cur_task_state_obj)
                    for condition in cur_task_state_obj['projectStatus']['conditions']:
                        cur_task_state_text += '    指标：{0[metricKey]} 状态：{0[status]} 计数：{0[actualValue]}\n'.format(
                            condition)
                    cur_task_state_text += '\n'
                cur_proj_state_text = ""
                if cur_proj_state_ok:
                    cur_proj_state_text = '整体代码扫描结果：{0[projectStatus][status]}\n\n    详细数据：\n'.format(
                        cur_proj_state_obj)
                    for condition in cur_proj_state_obj['projectStatus']['conditions']:
                        cur_proj_state_text += '    指标：{0[metricKey]} 状态：{0[status]} 计数：{0[actualValue]}\n'.format(
                            condition)
                    cur_proj_state_text += '\n'
                res_text = cur_task_state_text + cur_proj_state_text

                can_merge = False
                can_merge_text = ""
                if cur_task_state_ok:
                    if cur_task_state_obj['projectStatus']['status'] == 'OK':
                        can_merge = True
                    else:
                        can_merge = False

                if cur_proj_state_ok:
                    if cur_proj_state_obj['projectStatus']['status'] == 'OK':
                        can_merge = True
                    else:
                        can_merge = False

                if can_merge:
                    can_merge_text = "同意合并"
                else:
                    can_merge_text = "拒绝合并"

                res_text += 'Sonar 扫描结论：{0}\n\n更多详情请前往 SonarQube 项目页面：http://sonarqube.avlyun.org/dashboard?id={1}\n'.format(
                    can_merge_text, task_component_key)
                # 发送评论
                notes_merge_request(res_text)
                # 判断是否同意合并
                if can_merge:
                    approve_merge_request()

            elif task_status == 'FAILED':
                print('扫描失败')
                notes_merge_request(
                    "扫描任务失败，详情请前往: http://sonarqube.avlyun.org/dashboard?id=%s" % (task_component_key))
            elif task_status == 'CANCELED':
                print('扫描被取消')
                notes_merge_request(
                    "扫描任务被取消，详情请前往: http://sonarqube.avlyun.org/dashboard?id=%s" % (task_component_key))
            else:
                print('扫描结果状态异常')
                notes_merge_request(
                    "扫描结果返回值异常，需要手动检查: http://sonarqube.avlyun.org/dashboard?id=%s" % (task_component_key))
        else:
            print('无法获取扫描任务ID')
            notes_merge_request("无法获取扫描任务ID，可能是扫描失败了，需要手动检查: %s" %
                                (env_dict["BUILD_URL"]))
