#!/usr/bin/env python3
# coding: utf-8
import os
import re
import sys
import json
import logging
import requests
import traceback

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s [%(module)s.%(funcName)s line:%(lineno)d] %(message)s")
logger = logging.getLogger(__name__)


#
# 工具包
#

# 安全的从source字典中提取多级目标，目标为 `attr.attr.attr` 格式
# 支持多个多级目标，首次获取到非空目标则返回
def safeExtractDict(source, *queries):
    if not isinstance(source, dict):
        return None
    for query in queries:
        if not isinstance(query, str):
            return None
        s = source
        for q in query.split("."):
            if not isinstance(s, dict):
                return None
            s = s.get(q, None)
            if s is None:
                break
        if s is not None:
            return s


#
# 基础配置
#


# 元类，用于自动填充，即初始化时自动填充相关参数
class AutoFillMetaClass(type):

    def __new__(cls, name, bases, attrs):
        if name == "Env":
            for attrName in attrs.keys():
                if attrName.startswith("_"):
                    continue
                envValue = os.environ.get(attrName, None)
                if envValue is None:
                    continue
                logger.info(f"检测到环境变量[{attrName}]")
                attrs[attrName] = envValue
        return type.__new__(cls, name, bases, attrs)


# 自动填充环境变量，注意，区分大小写与驼峰命名。新增环境变量需在此处追加并写明用途。
class Env(metaclass=AutoFillMetaClass):
    # 项目相关
    CI_PROJECT_NAME = None
    GITLAB_USER_NAME = None
    GITLAB_USER_LOGIN = None
    CI_COMMIT_TITLE = None
    CI_MERGE_REQUEST_PROJECT_URL = None
    CI_JOB_URL = None
    # 合并请求相关
    CI_MERGE_REQUEST_PROJECT_ID = None
    CI_MERGE_REQUEST_IID = None
    CI_PRIVATE_TOKEN = None
    # sonar验证相关
    CI_SONAR_FILE_PATH = ".sonar.tmp"
    CI_SONAR_QUERY_INTERVAL = 10  # sonar查询间隔，一般仅在 pending 状态时才会等待查询
    CI_SONAR_MAX_PENDING = 600  # 最大等待时间10min
    CI_SONAR_TOKEN = "Basic Nzc1YWZkYzI1NDVhMTNkZWIyYzMwYjY2YjczMGU1YjlmNTZjYjI1Nzo="
    CI_SONAR_NEW_CODE_COVERAGE = 50


#
# 基础指令
#


class Command:

    @classmethod
    def exec(cls, cmd: str) -> str:
        return os.popen(cmd).read().strip()


class GitCommand(Command):

    @classmethod
    def check_base(cls) -> str:
        return cls.exec("git log HEAD..origin/master")


#
# 第三方服务
#


class Gitlab:
    suggested_approvers_ids = []

    @staticmethod
    def check_env() -> bool:
        if not Env.CI_MERGE_REQUEST_PROJECT_ID or not Env.CI_MERGE_REQUEST_IID or not Env.CI_PRIVATE_TOKEN:
            logger.error(f"缺失gitlab参数，无法进行留言操作，请检查相关环境变量。"
                         f"CI_MERGE_REQUEST_PROJECT_ID[{Env.CI_MERGE_REQUEST_PROJECT_ID}],"
                         f"CI_MERGE_REQUEST_IID[{Env.CI_MERGE_REQUEST_IID}],"
                         f"CI_PRIVATE_TOKEN[{Env.CI_PRIVATE_TOKEN}]")
            return False
        return True

    @classmethod
    def get_approval_rules(cls):
        response = requests.get(
            f"https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}/merge_requests/{Env.CI_MERGE_REQUEST_IID}/approvals",
            headers={
                "PRIVATE-TOKEN": Env.CI_PRIVATE_TOKEN
            },
        )
        if response.status_code != 200:
            logger.error("无法获取批准用户列表")
            return []
        json_data = response.json()
        logger.info(json_data)
        users = []
        for source in ["approvers", "approved_by", "suggested_approvers"]:
            for approver in json_data.get(source, []):
                username = safeExtractDict(approver, "username", "user.username")
                if isinstance(username, str) and username not in users:
                    users.append(username)
        for approver in json_data.get("suggested_approvers", []):
            userId = safeExtractDict(approver, "id", "user.id")
            if isinstance(userId, int) and userId not in cls.suggested_approvers_ids:
                cls.suggested_approvers_ids.append(userId)
        return users

    @classmethod
    def notes_merge_msg(cls, msg: str) -> None:
        if not cls.check_env():
            return
        response = requests.post(
            f"https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}/merge_requests/{Env.CI_MERGE_REQUEST_IID}/notes",
            headers={
                "PRIVATE-TOKEN": Env.CI_PRIVATE_TOKEN
            },
            json={
                "body": msg,
            }
        )
        if not (200 <= response.status_code < 300):
            logger.error(Env.CI_PRIVATE_TOKEN)
            logger.error(f"gitlab[https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}"
                         f"/merge_requests/{Env.CI_MERGE_REQUEST_IID}/notes]留言失败，返回：" + response.text)

    @classmethod
    def assign_suggest_to_approve(cls):
        if not cls.suggested_approvers_ids:
            logger.warning(f"未检测到推荐用户")
            return
        response = requests.put(
            f"https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}/merge_requests/{Env.CI_MERGE_REQUEST_IID}",
            headers={
                "PRIVATE-TOKEN": Env.CI_PRIVATE_TOKEN
            },
            json={
                "assignee_ids": cls.suggested_approvers_ids,
            }
        )
        if not (200 <= response.status_code < 300):
            logger.error(Env.CI_PRIVATE_TOKEN)
            logger.error(f"gitlab[https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}"
                         f"/merge_requests/{Env.CI_MERGE_REQUEST_IID}]assign推荐用户失败，返回：" + response.text)
        else:
            logger.info(f"assign成功，当前approve用户ids{cls.suggested_approvers_ids}")


# 企业微信功能
class EnterpriseWeChat:
    users = []

    @classmethod
    def check_env(cls) -> bool:
        for user in Gitlab.get_approval_rules():
            if user not in cls.users:
                cls.users.append(user)
        if Env.GITLAB_USER_LOGIN and Env.GITLAB_USER_LOGIN not in cls.users:
            cls.users.append(Env.GITLAB_USER_LOGIN)
        if not cls.users:
            logger.warning("缺少企业微信留言的用户，请检查是设置了相关approve人员")
            return False
        cls.users = [user for user in cls.users if user and user != "jenkins"]  # 过滤jenkins用户
        return True

    @classmethod
    def notice(cls, msg: str, add_users=True) -> None:
        if not cls.check_env():
            return
        # if add_users:  # 取消该功能，交由通知服务实现
        #     msg += f"""\n\n--------企业微信接收用户--------\n{", ".join(cls.users)}"""
        response = requests.post(
            "http://notification-wechat-api.prod.k8ss.cc/message/send",
            json={
                "touser": "|".join(cls.users),
                "msgtype": "markdown",
                "markdown": {
                    "content": msg
                },
                "safe": 0
            }
        )
        if response.status_code != 200:
            logger.error("企业微信返回异常，请检查接口/参数的正确性：" + response.text)


class Sonar:

    @staticmethod
    def status2markdown(status):
        if status == "ERROR":
            status = "ERR"
        if status in ("OK", "WARN"):
            return f"""<font color="info">{status}</font>"""
        else:
            return f"""<font color="warning">{status}</font>"""

    @classmethod
    def query_project_key_from_sonar_file(cls, file_path: str) -> str:
        if not os.path.exists(file_path):
            logger.warning(f"未检测到sonar文件[{file_path}]")
            return ""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            projectKey = re.search("QUALITY GATE STATUS.*?http://sonarqube.avlyun.org.*?\?id=(.*)",
                                   content)
            if projectKey:
                return projectKey.group(1)
            else:
                logger.warning(f"sonar文件中未检测到任务ID，检查文件内容是否正确:\n{content}")
                return ""

    @classmethod
    def query_measures_component(cls, projectKey):
        if not projectKey:
            raise Exception("缺失projectKey，无法获取sonar扫描结果，请检查sonar文件是否正常")
        metricKeys = {
            # 项目状态
            "alert_status": "未获取到此数据",
            "quality_gate_details": "未获取到此数据",
            # 当前提交
            "new_bugs": "未获取此数据",
            "new_code_smells": "未获取此数据",
            "new_security_rating": "未获取此数据",
            "new_maintainability_rating": "未获取此数据",
            "new_coverage": "未获取此数据",
            "new_duplicated_lines_density": "未获取此数据",
            # 项目统计
            "bugs": "未获取此数据",
            "code_smells": "未获取此数据",
            "security_rating": "未获取此数据",
            "coverage": "未获取此数据",
            "duplicated_lines_density": "未获取此数据",
        }
        response = requests.get(
            "https://sonarqube.avlyun.org/api/measures/component",
            params={
                "component": projectKey,
                "metricKeys": ",".join(metricKeys.keys()),
            },
            headers={
                'Authorization': Env.CI_SONAR_TOKEN
            },
            timeout=15,
        )
        if not (200 <= response.status_code < 300):
            raise Exception(response.text)
        for measure in response.json()["component"]["measures"]:
            key = measure["metric"]
            if key not in metricKeys:
                continue
            value = measure.get("value", None) or measure.get("period", {}).get("value", None)
            if value is not None:
                metricKeys[key] = value
        try:
            for condition in json.loads(metricKeys["quality_gate_details"])["conditions"]:
                key = condition["metric"]
                if key not in metricKeys:
                    continue
                metricKeys[key] = f"""{cls.status2markdown(condition["level"])} {{}} {condition["actual"]}"""
        except:
            logger.error("sonar分析结论获取异常")
            logger.error(traceback.format_exc())
        return metricKeys

    @classmethod
    def approve_merge_request(cls):
        response = requests.post(
            f"https://code.avlyun.org/api/v4/projects/{Env.CI_MERGE_REQUEST_PROJECT_ID}/merge_requests/{Env.CI_MERGE_REQUEST_IID}/approve",
            headers={
                "PRIVATE-TOKEN": Env.CI_PRIVATE_TOKEN
            }
        )
        if not (200 <= response.status_code < 300):
            logger.error(f"merge approve失败: {response.text}")


#
# 业务脚本代码
#


# assign推荐用户
def assign_suggest_to_approver():
    try:
        Gitlab.get_approval_rules()
        Gitlab.assign_suggest_to_approve()
    except Exception as e:
        logger.error(f"assign推荐用户失败: {e}")


# 判断当前分支是否基于最新master，若不是则gitlab留言并企业微信通知
def is_branch_base_master():
    err = GitCommand.check_base()
    if err:
        notice_msg = f"""
### {Sonar.status2markdown("ERROR")} 当前分支不是基于最新主分支 {Env.CI_PROJECT_NAME}
##### [job_url]({Env.CI_JOB_URL}) | [merge_url]({Env.CI_MERGE_REQUEST_PROJECT_URL}/-/merge_requests/{Env.CI_MERGE_REQUEST_IID})
""".strip()
        logger.error(notice_msg)
        EnterpriseWeChat.notice(notice_msg)
        Gitlab.notes_merge_msg(notice_msg)
        raise Exception(notice_msg)
    else:
        logger.info("当前分支是基于最新的master分支")


# 读取sonar扫描的文件结果，获取任务ID，远程获取任务状态，根据状态进行留言与通知，sonar不应该抛出异常
def sonar_report():
    # 根据sonar-cli扫描结果文件获取任务名
    projectKey = Sonar.query_project_key_from_sonar_file(Env.CI_SONAR_FILE_PATH)
    if not projectKey:
        return
    allow_merge = False
    # 根据项目key获取measures-component
    metricKeys = Sonar.query_measures_component(projectKey)
    status = metricKeys["alert_status"]
    if status in ("OK", "WARN"):
        allow_merge = True
        detail = "sonar扫描通过"
    elif status in ("ERROR"):
        detail = "sonar扫描未通过"
    elif status == "None":
        detail = "sonar扫描结果返回为空，需要手动检查"
    else:
        detail = "sonar扫描结果返回值异常，需要手动检查"
    # 增加new_coverage此次提交代码覆盖率检测
    coverage_status = "OK"
    logger.info(f"""获取到代码覆盖率：{metricKeys["new_coverage"]}""")
    if allow_merge and not new_coverage_check(metricKeys["new_coverage"]):
        logger.error("代码覆盖率不通过")
        allow_merge = False
        status = coverage_status = "ERROR"
        detail = f"sonar扫描未通过，此次提交单测覆盖率小于{Env.CI_SONAR_NEW_CODE_COVERAGE}"
        metricKeys["new_coverage"] = f"""<font color="warning">{metricKeys["new_coverage"]}</font>"""

    notice_msg = f"""
### {Sonar.status2markdown(status)} {detail} {Env.CI_PROJECT_NAME}
> #### **本次提交:**
> {metricKeys["new_bugs"].format("**new_bugs:**")} <br>
> {metricKeys["new_code_smells"].format("**new_code_smells:**")} <br>
> {metricKeys["new_security_rating"].format("**new_security_rating:**")} <br>
> {metricKeys["new_maintainability_rating"].format("**new_maintainability_rating:**")} <br>
> {Sonar.status2markdown(coverage_status)} **new_coverage(%)**: {metricKeys["new_coverage"]} <br>
> #### **项目统计:**
> {metricKeys["bugs"].format("**bugs:**")} <br>
> {metricKeys["code_smells"].format("**code_smells:**")} <br>
> {metricKeys["security_rating"].format("**security_rating:**")} <br>
> {Sonar.status2markdown("OK")} **coverage(%)**: {metricKeys["coverage"]} <br>
> {Sonar.status2markdown("OK")} **duplicated_lines_density(%)**: {metricKeys["duplicated_lines_density"]} <br>
##### [job_url]({Env.CI_JOB_URL}) | [merge_url]({Env.CI_MERGE_REQUEST_PROJECT_URL}/-/merge_requests/{Env.CI_MERGE_REQUEST_IID}) | [sonar_url](http://sonarqube.avlyun.org/dashboard?id={projectKey})
    """.strip().replace("<br>", "   ")
    logger.info(notice_msg)
    EnterpriseWeChat.notice(notice_msg)
    Gitlab.notes_merge_msg(notice_msg)
    # 允许合并代码
    if allow_merge:
        Sonar.approve_merge_request()
    else:
        raise Exception(notice_msg)


def new_coverage_check(coverage):
    try:
        if float(coverage) < float(Env.CI_SONAR_NEW_CODE_COVERAGE):  # 覆盖率小于指定值
            return False
    except:
        pass
    return True


# 单元测试失败通知
def unittest_failure_report():
    EnterpriseWeChat.notice(f"""
### {Sonar.status2markdown("ERROR")} 单元测试不通过 {Env.CI_PROJECT_NAME}
##### [job_url]({Env.CI_JOB_URL})
    """.strip())


# 部署失败通知
def deploy_failure_report():
    EnterpriseWeChat.notice(f"""
### {Sonar.status2markdown("ERROR")} 部署失败 {Env.CI_PROJECT_NAME}
##### [job_url]({Env.CI_JOB_URL})
        """.strip())


# 部署成功通知
def deploy_success_report():
    EnterpriseWeChat.notice(f"""
### {Sonar.status2markdown("OK")} 部署成功 {Env.CI_PROJECT_NAME}
##### [job_url]({Env.CI_JOB_URL})
        """.strip())


#
# 启动指令:
#   - python3 fabfilev3.py assign_suggest_to_approver
#   - python3 fabfilev3.py is_branch_base_master
#   - python3 fabfilev3.py sonar_report
#   - python3 fabfilev3.py unittest_failure_report
#   - python3 fabfilev3.py deploy_failure_report
#   - python3 fabfilev3.py deploy_success_report
#


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise Exception(f"未指定执行的业务脚本")
    _, funcName = sys.argv[:2]
    func = locals().get(funcName, None)
    if func is None:
        raise Exception(f"未定义业务脚本[{funcName}]")
    func()
