FROM node:22-alpine AS build

WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY index.html vite.config.js ./
COPY src/ ./src/

RUN npm run build
FROM nginx:1.27-alpine

ENV PORT=80
ENV API_UPSTREAM=http://api:8000

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist/ /usr/share/nginx/html/

EXPOSE 80 8080