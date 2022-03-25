FROM node:10 as builder
WORKDIR /project
COPY package.json yarn.lock .npmrc /project/
RUN yarn install
COPY . /project/
ENV PROJECT_NAME situation-01-fe
RUN yarn build

FROM harbor.inf.avlyun.org/inf/fe
EXPOSE 8080
ENV PROJECT_NAME situation-01-fe
COPY --from=builder /project/dist/static /usr/share/nginx/html/static
COPY _ci/default.conf.tmpl /etc/nginx/conf.d/default.conf.tmpl
