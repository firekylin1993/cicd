FROM golang:1.16.3

ENV GOPROXY=https://registry-mirrors.avlyun.org/repository/goproxy/,https://goproxy.io,direct
ENV GONOPROXY=*.avlyun.org
ENV GONOSUMDB=*.avlyun.org
ENV GOPRIVATE=*.avlyun.org
RUN cd /
RUN go get -u github.com/jstemmer/go-junit-report
RUN go get -u github.com/boumenot/gocover-cobertura

