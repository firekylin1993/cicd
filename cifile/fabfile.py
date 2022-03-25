#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import time
import requests
import yaml
import json
from fabric.api import task, local, abort, warn, settings

# 部署参数(以项目根目录作为根目录)
ci_conf = {
    # 预发布环境使用的环境变量文件路径
    "preEnvPath": "env/pre.env",
    # 构建用的dockerfile路径
    "deployDockerFilePath": "_ci/Dockerfile",
    # hook
    "jenkinsTriggerUrl": "http://project-service-project.t.k8ss.cc/api/project-service/v1/jenkins-ci-event",
    "projectCenterUrl": "http://project-service-project.t.k8ss.cc/api/project-service/v1/service-ci-config",
    "harbor": None,
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
    "commitID": None,
    "tag": None,
    "branch": None
}

# 环境变量
env_dict = {}

# 任务列表
@task
def build():
    read_conf()
    get_tag()
    make_tmpimg()
    push_img()
    clean_img()
    project_center_hook("stop", "done")

@task
def jobstart():
    get_env()
    project_center_hook("start", "start")

@task
def jobstop(status):
    get_env()
    project_center_hook("stop", status)

# 子任务-------------
# 项目配置中心通报hook
def project_center_hook(post_type="start", status="unkown"):
    get_env()
    req_data = {
        "post_type": post_type,
        "status": status,
        "input_branch": env_dict["input_branch"],
        "git_repo": env_dict["git_repo"],
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
        }),
        "deploy_info": git_info
    }
    response = requests.post(ci_conf["jenkinsTriggerUrl"], json=req_data)

    if response.status_code != 200:
        abort("配置中心不接受此次访问")

# 读取构建配置文件（当 ci_conf.projectCenterUrl 配置存在时，从远程获取配置，否则读取本地）
def read_conf():
    print("---Stage: read ci config from config file---")
    global ci_conf
    get_env()
    if ci_conf["projectCenterUrl"]:
        resp = requests.get(
            ci_conf["projectCenterUrl"],
            timeout=10,
            params={
                "deploy_key": env_dict["deploy_key"]
            },
        )
        proj_conf = resp.json()
        print(proj_conf)
        if isinstance(proj_conf, dict):
            for key, values in proj_conf.items():
                ci_conf[key] = values
        else:
            abort("配置文件不正确")
    else:
        abort("无法获取配置文件，projectCenterUrl未配置")

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
            tag = "master-" + git_current_commit_id[0:8]
            warn("当前分支为master，但找不到rb分支合并记录，无法使用版本号打tag，将使用" + tag + "作为tag")
        else:
            tag = matcher1.group(1)
    elif git_current_branch.find("rb-", 0) != -1:
        tag = git_current_branch
    else:
        tag = git_current_commit_id
    global git_info
    git_info = {"commitID": git_current_commit_id,
                "tag": tag, "branch": git_current_branch}
    print(git_info)

# 创建临时镜像
def make_tmpimg():
    print("---Stage: make docker image with a temp name---")
    local("docker build --rm -f %s -t wsmtmpdocker:%s ." %
          (ci_conf["deployDockerFilePath"], git_info["commitID"]))

# 推送镜像
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

# sonarscanner
def sonar_scanner():
    print("---Stage: sonarscanner---")
    sonar_container = os.popen(
        "docker create --rm --env cur_branch=%s harbor.inf.avlyun.org/c-base/sonar-web-scanner:v3.3.0" % (env_dict["cur_branch"])).read().strip()
    print(sonar_container)
    local("docker cp . %s:/project" % (sonar_container))
    local("docker start %s" % (sonar_container))

# 工具函数-----------
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
