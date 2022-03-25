var jenkins = require("jenkins")({
    baseUrl:
        "http://sunyanjun:1192d2563a38397276277adcd9948f6ba8@192.168.48.15:8080",
    crumbIssuer: true,
    promisify: true
});

var parser = require("fast-xml-parser");
var Git = require("nodegit");
var path = require("path");

async function getjobs(views) {
    let tmparr = [];
    let viewJobs = [];
    for (let i = 0; i < views.length; i++) {
        viewJobs = await jenkins.view.get(views[i]);
        tmparr = tmparr.concat(viewJobs.jobs.map(x => x.name));
    }
    return tmparr;
}

async function getJobGitRepo(jobName) {
    const jobInfoXml = await jenkins.job.config(jobName);
    const jobInfoObj = parser.parse(jobInfoXml);
    const jobParamPart =
        jobInfoObj["flow-definition"]["properties"][
            "hudson.model.ParametersDefinitionProperty"
        ]["parameterDefinitions"]["hudson.model.StringParameterDefinition"];
    return jobParamPart
        .filter(x => x.name === "git_repo")
        .map(x => x.defaultValue);
}

var gitOption = {
    fetchOpts: {
        callbacks: {
            certificateCheck: () => 0,
            credentials: function(url, userName) {
                return Git.Cred.sshKeyMemoryNew(
                    userName,
                    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDcU41/LkbNCib4g6i7J/4Wux2rSdpLp0PwNQGQr1y7hL6Cx6rXaMDfhouyxrVzdQiRIUFPHTs+0MuS0hgybH0gCRfZ6pocJ9JzApgz8tG9ux6Mz5UD0Ia9FA5ub4Vm3lCA7fTxodZ7UyHz0Vw1QXsnvMDcEMeb0ubM8dCXvsSVPi52VX7RWM6ascACkVP0RkQWW5mK6qBYtfpzXBs2cuj2+IyP9uN3R0MIohun7wegYzkAKYkVMqVZiHHFvQvhea3+aj+vfQDn7qu8eBKCQZDeGKJJVSa8vLiF62Of+fNcI2hQEwDJdFa6ys6tUFBeXIj66E+7NDKTzBTinP83pp7X sunyanjun@DESKTOP-3AKH94U",
                    "MIIEpQIBAAKCAQEA3FONfy5GzQom+IOouyf+Frsdq0naS6dD8DUBkK9cu4S+gseq12jA34aLssa1c3UIkSFBTx07PtDLktIYMmx9IAkX2eqaHCfScwKYM/LRvbsejM+VA9CGvRQObm+FZt5QgO308aHWe1Mh89FcNUF7J7zA3BDHm9LmzPHQl77ElT4udlV+0VjOmrHAApFT9EZEFluZiuqgWLX6c1wbNnLo9viMj/bjd0dDCKIbp+8HoGM5ACmJFTKlWYhxxb0L4Xmt/mo/r30A5+6rvHgSgkGQ3hiiSVUmvLy4hetjn/nzXCNoUBMAyXRWusrOrVBQXlyI+uhPuzQyk8wU4pz/N6ae1wIDAQABAoIBAQDWYDnCMK3VHXazwa8wg4Y4adJBcveDOvngxEKEnAxXrJ6Ns2dodtWL6GcPCUdOUuaGB9x69Q9LXG9nqSLAFU1eGVrqvtk6YgjjvPeJPE+WE3ZzPhtY/dHMMbKlA7/CSrf76wy0+2oszsOvb9sPOmpxTLg+p9kApiHJ8dOrgoPWTT4Wcr88e0VNFMqw43+GCSLEM1/8Lkhx4UQMxFKDsMJfMa6CcCdX3cfRtsaNyy9x88k8RELRvPsPS5L8web2KSjbC5zxAXv3/987mTPQvT/cu1QJjRsToG9PxmQBRpwxyOBq9qfRdVX53TzUqLdBaWFGxP9lIDzb0f1dpvaHweIBAoGBAP9muiNcHdBbnCHfXrEhx+ypXTRyzcgEp1dg6rNkUTYFCFT8CrLLmCo3cGzxU+pAICIYbC/IzHAMt63rqHxX5E4HS5Nv3cT45srtrsWWIraChW2XCBJf1/AN4kJKwU8yMpoSwLCaeZMjW3QyKkIW32ro6TM3XkH88TwYG/bvm2UBAoGBANzXxrlye38xyJ1Cc2kCdy0cQE9kmRpYEq0NYANa4miIy5voFyOs3SAys+MumpRw4bPBjPXXIQ2har2QS8+bP1BAVBZdR8BxM4lCV143sP6eKBrXxNhVWSGDIRYX4zNIhhF3BPC+XGXSRK/05teMJ/waHvqPEfA0Ic717s2iDcvXAoGBAL8NmJaU9RSFQyGvl4VH8OdftoJikv9aQ9hAfrGdjIatcxMny9T+KiECgc5tJMnqGF+JB30jZ5M2YDzxOYNyuC2KlYWAPFR5oSQScxgJfIQs1SUqwvYDzmQb7rKKe1sEAQhymMRDekiQPXyJfkUcGRs/ihsvAwq37bl3i4vIp+UBAoGAEol2H8jRPurx2OlkAJN5Z2rwpvldtI1h++6ceYueZ4Hb/Vks4Ay5fuNioBYgWYdkGo+LgnMtThSXfhPnmSSB2v2bUUlBJZEa71GHPdxU2fpyiVZFKpd3ZM258D3PD1XuEvc3jfGcldthcpeO7NbR4GJc6VErA0uM7u9LvSz2FX8CgYEA5cmwZMVjepyeuRkjAUOz2MKglAmb3u5I6IdvhrLrnhTVjlSOUiH35d7HiBJleuPaMPWS1gX2/Bzt6PrP+/CRqqX5oc6wVXaa12Vwg58urDW25xpRULiZLfSj5YwFuXzr/98oHgg7eHSM1fQ2xkZeWdPrbyMtRCJxQOBiXbLOvd0=",
                    ""
                );
            }
        }
    }
};

getjobs(["k8s前端", "k8s后端"])
    .then(async jobsNameList => {
        let tmparr = [];
        let gitRepo = "";
        for (let i = 0; i < jobsNameList.length; i++) {
            gitRepo = await getJobGitRepo(jobsNameList[i]);
            tmparr.push({
                job: jobsNameList[i],
                git: gitRepo[0]
            });
        }
        return tmparr;
    })
    .then(async jobs => {
        console.log(jobs);
        for (let i = 0; i < jobs.length; i++) {
            await Git.Clone(
                jobs[i].git,
                path.join(__dirname, "gitrepos", jobs[i].job),
                gitOption
            ).then(repository =>
                repository
                    .getReferences()
                    .then(arrayReference => console.log(arrayReference))
            );
        }
    });
