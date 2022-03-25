#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import requests
import json
from fabric.api import task, abort

# 环境变量
env_dict = {}


@task
def jobstart():
    get_env()
    project_center_hook("start", "start")


@task
def jobstop(status):
    get_env()
    project_center_hook("stop", status)

# 获取环境变量


def get_env():
    global env_dict
    env_dict = os.environ

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
        })
    }
    response = requests.post(
        "http://project-service-project.t.k8ss.cc/api/project-service/v1/jenkins-ci-event", json=req_data)
    # print(response)
    # print(123)
    # if response.status_code != 200:
    #     abort("配置中心服务无响应")
