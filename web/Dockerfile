FROM node:20.20.2-alpine3.23 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.27.5-alpine3.21
# The site and config stay root-owned and read-only. nginx runs as the
# unprivileged "nginx" user and writes only its cache and pid file (compose
# mounts both as tmpfs, with the root filesystem read-only).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /var/cache/nginx \
    && touch /run/nginx.pid && chown nginx:nginx /run/nginx.pid
USER nginx
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
