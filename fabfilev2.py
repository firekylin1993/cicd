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
}

# 常量
# 获取gitInfo时用到的git命令
git_shell = {
    "currentBranch": "git name-rev --name-only HEAD",
    "currentCommitID": "git rev-parse HEAD",
    "currentTag": "git describe --tags --exact-match $(git rev-parse HEAD)",
    "latestLog": "git log -1",
    "checkBase": "git log HEAD..origin/master"
}

# 环境变量
env_dict = {}

# 全局变量
git_info = {
    "commitID": None,  # git 提交ID
    "tag": None,  # git tag
    "branch": None,  # git branch
    "version": None,  # 当前版本号
    "merge_approver": list(),  # merge请求批准人员邮箱列表
    "trigger_user": None  # 触发用户邮箱
}

# 任务列表


@task
def build():
    read_conf()
    get_tag()
    is_branch_base_master()
    make_tmpimg()
    push_img()
    clean_img()
    create_yaml()


@task
def deploy():
    read_conf()
    deploy_yaml()


@task
def testdeploy():
    read_conf()
    get_tag()
    make_tmpimg()
    clean_img()
    create_yaml()
    test_deploy_yaml()


@task
def localsonarscanner():
    read_conf()
    is_branch_base_master()
    sonarscanner()

# 子任务
# 读取构建配置文件


def read_conf():
    print("---Stage: read ci config from config file---")
    global ci_conf
    get_env()
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


# 从本地git仓库获取标签信息


def get_tag():
    print("---Stage: get image tag from git---")
    git_current_branch = env_dict["cur_branch"].strip().replace("/", "_")
    git_current_commit_id = os.popen(
        git_shell["currentCommitID"]).read().strip()
    version = git_current_branch + "_" + git_current_commit_id[0:8]
    git_current_tag = ""
    if os.system(git_shell["currentTag"]) == 0:
        git_current_tag = os.popen(git_shell["currentTag"]).read().strip()
        version = git_current_tag
    global git_info
    git_info = {
        "commitID": git_current_commit_id,
        "version": version,
        "branch": git_current_branch,
        "tag": git_current_tag
    }
    print(git_info)

# 创建临时镜像


def make_tmpimg():
    print("---Stage: make docker image with a temp name---")
    local("docker build --build-arg VERSION_TAG=%s --build-arg COMMIT_ID=%s  --rm -f %s -t wsmtmpdocker:%s ." %
          (git_info["version"], git_info["commitID"][0:8], ci_conf["deployDockerFilePath"], git_info["commitID"]))

# 推送镜像


def push_img():
    print("---Stage: tagged temp image and push it to harbor---")
    temp_img = "wsmtmpdocker:%s" % (git_info["commitID"])
    docker_push(temp_img, "%s:%s" % (ci_conf["harbor"], git_info["version"]))
    if git_info["branch"] == "master":
        docker_push(temp_img, "%s:latest" % (ci_conf["harbor"]))

# 清理临时镜像


def clean_img():
    print("---Stage: clean temp image---")
    if git_info and git_info["commitID"]:
        with settings(warn_only=True):
            local("docker rmi -f  wsmtmpdocker:%s" % (git_info["commitID"]))


# 读取yaml模板文件并创建部署用yaml


def create_yaml():
    print("---Stage: creat deploy yaml file---")
    # 读取yaml模板文件
    with open(ci_conf["yamlPath"], "r") as tmpYamlFile:
        tmp_yaml = tmpYamlFile.read()
    # 替换yaml模板文件中的一些内容
    tmp_yaml = tmp_yaml.replace("$replace_tag", git_info["version"])
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
        "docker create --rm --env cur_branch=%s harbor.inf.avlyun.org/c-base/sonar-web-scanner:v3.3.0" % (env_dict["cur_branch"])).read().strip()
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
    if not env_dict.get('gitlabActionType'):
        return
    if env_dict["gitlabActionType"] == "MERGE" and env_dict["gitlabMergeRequestTargetProjectId"] and env_dict["gitlabMergeRequestIid"]:
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
    if not env_dict.get('gitlabActionType'):
        return
    if env_dict["gitlabActionType"] == "MERGE" and env_dict["gitlabMergeRequestTargetProjectId"] and env_dict["gitlabMergeRequestIid"]:
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

# 企业微信消息通知


def qywx(users=[], msg=""):
    if len(users) < 1:
        return
    for user in users:
        if user == "":
            continue
        if user == "jenkins":
            continue
        requests.post(
            "http://notification-wechat-api.dev.k8ss.cc/message/send",
            json={
                "touser": user,
                "msgtype": "text",
                "text": {
                    "content": msg
                },
                "safe": 0
            }
        )
# 判断master merge请求当前分支base是否是master


def is_branch_base_master():
    if not env_dict.get('gitlabActionType'):
        return
    if env_dict["gitlabActionType"] == "MERGE":
        ok = os.popen(
            "if [[ $(git log HEAD..origin/master) ]]; then echo 1; else echo 2; fi").read().strip() == "2"
        if not ok:
            msg = "当前 %s 分支的 base 分支不是最新的 master，需要先 rebase 后重新提交：%s/merge_requests/%s" % (
                env_dict["gitlabSourceBranch"], env_dict["gitlabSourceRepoHomepage"], env_dict["gitlabMergeRequestIid"])
            notes_merge_request(msg)
            qywx([env_dict["gitlabMergedByUser"]], msg)
            abort("当前分支未基于最新的master")


# 获取合并请求批准用户列表


def get_mr_approvers():
    mraps_res = requests.get(
        "https://code.avlyun.org/api/v4/projects/%s/approval_rules" % (
            env_dict["gitlabMergeRequestTargetProjectId"]),
        headers={
            "PRIVATE-TOKEN": "1FSMtzD2JSygww36GPzR"
        },
    )
    if mraps_res.status_code != 200:
        print("无法获取批准用户列表")
        return []
    mraps_res_obj = mraps_res.json()
    print("[mraps_res_obj]")
    print(mraps_res_obj)
    if len(mraps_res_obj) < 1:
        return []
    users = []
    for approver_rules in mraps_res_obj:
        if approver_rules['users']:
            for user in approver_rules['users']:
                if user['username'] not in users:
                    users.append(user['username'])
    return users

# 获取合并请求发起用户


def get_mg_rq_user():
    if not env_dict.get('gitlabActionType'):
        return []
    if not env_dict.get('gitlabMergedByUser'):
        return []
    if env_dict["gitlabActionType"] == "MERGE":
        return [env_dict["gitlabMergedByUser"]]
    else:
        return []


# 本地版代码扫描


def sonarscanner():
    auth_header = "Basic Nzc1YWZkYzI1NDVhMTNkZWIyYzMwYjY2YjczMGU1YjlmNTZjYjI1Nzo="
    if not os.path.isfile("sonar-project.properties"):
        return

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
                    'Authorization': auth_header
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
                msg = "无法获取扫描任务状态，可能是扫描失败了，需要手动检查: %s" % (
                    env_dict["BUILD_URL"])
                notes_merge_request(msg)
                qywx(get_mg_rq_user(), msg)
                return
        try:
            task_status = task_obj['task']['status']
            task_analysis_id = task_obj['task']['analysisId']
            task_component_id = task_obj['task']['componentId']
            task_component_key = task_obj['task']['componentKey']
        except:
            print('无法获取扫描任务ID')
            msg = "无法获取扫描任务ID，可能是扫描失败了，需要手动检查: %s" % (env_dict["BUILD_URL"])
            notes_merge_request(msg)
            qywx(get_mg_rq_user(), msg)
            return

        if (task_status in ['PENDING', 'IN_PROGRESS']):
            print('无法获取扫描任务数据')
            msg = "无法获取扫描任务数据，需要手动检查: %s" % (env_dict["BUILD_URL"])
            notes_merge_request(msg)
            qywx(get_mg_rq_user(), msg)
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
                    'Authorization': auth_header
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
                    'Authorization': auth_header
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
                cur_task_state_text = '代码扫描结果：{0[projectStatus][status]}\n\n    详细数据：\n'.format(
                    cur_task_state_obj)
                for condition in cur_task_state_obj['projectStatus']['conditions']:
                    cur_task_state_text += '    指标：{0[metricKey]} 状态：{0[status]} 计数：{0[actualValue]}\n'.format(
                        condition)
                cur_task_state_text += '\n'
            res_text = cur_task_state_text

            can_merge = False
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
                res_text += 'Sonar 扫描结论：同意合并\n\n更多详情请前往 SonarQube 项目页面：http://sonarqube.avlyun.org/dashboard?id={0}\n'.format(
                    task_component_key)
                notes_merge_request(res_text)
                approve_merge_request()
                msg = "代码合并 | %s | %s | 扫描通过 | %s/merge_requests/%s" % (env_dict["gitlabMergeRequestTitle"],env_dict["gitlabUserName"],env_dict["gitlabSourceRepoHomepage"],env_dict["gitlabMergeRequestIid"])
                users = get_mr_approvers()
                qywx(users, msg)
            else:
                res_text += 'Sonar 扫描结论：拒绝合并\n\n更多详情请前往 SonarQube 项目页面：http://sonarqube.avlyun.org/dashboard?id={0}\n'.format(
                    task_component_key)
                notes_merge_request(res_text)
                qywx(get_mg_rq_user(), res_text)

        elif task_status == 'FAILED':
            print('扫描失败')
            msg = "扫描任务失败，详情请前往: http://sonarqube.avlyun.org/dashboard?id=%s" % (
                task_component_key)
            notes_merge_request(msg)
            qywx(get_mg_rq_user(), msg)
        elif task_status == 'CANCELED':
            print('扫描被取消')
            msg = "扫描任务被取消，详情请前往: http://sonarqube.avlyun.org/dashboard?id=%s" % (
                task_component_key)
            notes_merge_request(msg)
            qywx(get_mg_rq_user(), msg)
        else:
            print('扫描结果状态异常')
            msg = "扫描结果返回值异常，需要手动检查: http://sonarqube.avlyun.org/dashboard?id=%s" % (
                task_component_key)
            notes_merge_request(msg)
            qywx(get_mg_rq_user(), msg)
    else:
        print('无法获取扫描任务ID')
        msg = "无法获取扫描任务ID，可能是扫描失败了，需要手动检查: %s" % (env_dict["BUILD_URL"])
        notes_merge_request(msg)
        qywx(get_mg_rq_user(), msg)
