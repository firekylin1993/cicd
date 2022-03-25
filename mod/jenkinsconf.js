var jenkins = require("jenkins")({
    baseUrl:
        "http://sunyanjun:1192d2563a38397276277adcd9948f6ba8@192.168.48.15:8080",
    crumbIssuer: true
});
var xml2js = require("xml2js");
// 复制jenkins任务模版创建jenkins任务
const newJobName = "test-autocreate-job";
const deployKey = "0060FEF13C264814ADD81B93F5E70E00";
const projectGitDSN = "git@git.avlyun.org:c-web/docs.git";
jenkins.job.copy("common-job-temp", newJobName, function(err) {
    if (err) {
        console.error(err);
        throw err;
    }
    // 将新创建的jenkins任务添加到对应的任务视图中
    jenkins.view.add("k8s前端", newJobName, function(err) {
        if (err) {
            console.error(err);
            throw err;
        }
        jenkins.job.config(newJobName, function(err, data) {
            if (err) {
                console.error(err);
                throw err;
            }
            xml2js.parseString(data, (err, result) => {
                let jobConfig = JSON.parse(JSON.stringify(result));
                jobConfig["flow-definition"]["properties"][0][
                    "hudson.model.ParametersDefinitionProperty"
                ][0]["parameterDefinitions"][0][
                    "hudson.model.StringParameterDefinition"
                ] = [
                    {
                        name: ["git_repo"],
                        description: ["GIT仓库地址"],
                        defaultValue: [projectGitDSN],
                        trim: ["true"]
                    },
                    {
                        name: ["deploy_key"],
                        description: [
                            "部署key,用来标记该jenkins任务以及获取部署时的参数"
                        ],
                        defaultValue: [deployKey],
                        trim: ["true"]
                    }
                ];
                jobConfig["flow-definition"]["definition"][0]["scm"][0][
                    "userRemoteConfigs"
                ][0]["hudson.plugins.git.UserRemoteConfig"][0][
                    "url"
                ][0] = projectGitDSN;
            });
        });
    });
});
