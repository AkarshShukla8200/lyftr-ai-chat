# syntax=docker/dockerfile:1
# ---- build stage: Vite production build ----
FROM node:24.22.3-slim@sha256:32e57b5784e8875d2cc0112dcaf13f9100f2d0d9446187808738e99aee29a5a2 AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
# Exact versions + integrity hashes from package-lock.json; no install scripts.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
# Backend URL as seen by the BROWSER (not the Docker service name). Build-time only.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---- runtime stage: static files on nginx ----
FROM nginx:1.30.8-alpine@sha256:6437a63b5c529f0e06162b3f593c0154cff6fa2ea0f94fd7c27928cb399e022d AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
