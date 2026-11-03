# HomeAI Cloud — Caddy gateway image (builds the SPA, then serves it + proxies APIs).
# Owner: Renuka (P0-9). Build context is the repo root so the SPA source under
# web/ is available to the build stage. See docs/03_REPO_AND_INFRA.md sections 3 & 4.
#
#   docker build -f infra/caddy/Dockerfile -t homeai-caddy .

# ---- Stage 1: build the React SPA -----------------------------------------
FROM node:20-slim AS web-build
WORKDIR /web

# Install deps against the lockfile first for better layer caching.
COPY web/package.json web/package-lock.json ./
RUN npm ci

# Build the static bundle (tsc -b && vite build -> /web/dist).
COPY web/ ./
RUN npm run build

# ---- Stage 2: Caddy serving the SPA and proxying the API -------------------
FROM caddy:2-alpine

# Gateway config (routing table + SPA fallback).
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile

# Static SPA assets served at /srv/web (matches `root * /srv/web` in the Caddyfile).
COPY --from=web-build /web/dist /srv/web

EXPOSE 80 443
