FROM debian:bullseye
RUN sed -i "s#deb.debian.org#ftp.cn.debian.org#g" /etc/apt/sources.list
RUN apt-get update && \
	apt-get install -y --no-install-recommends \
	    tzdata \
	    locales \
	    ca-certificates \
        netbase \
        && rm -rf /var/lib/apt/lists/ \
        && apt-get autoremove -y && apt-get autoclean -y
RUN locale-gen zh_CN.UTF-8; \
    update-locale zh_CN.UTF-8;
RUN cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime;
ENV TZ Asia/Shanghai
ENV LANG zh_US.utf8
