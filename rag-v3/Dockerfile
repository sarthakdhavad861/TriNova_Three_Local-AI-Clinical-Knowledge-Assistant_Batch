# Frontend image (build + nginx). The backend and Ollama run on the host (see docs/SETUP.md) — they are NOT in this image.
# UNVERIFIED in the authoring environment (no Docker/npm access there): treat as a starting point.
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
# The browser calls the API through nginx at /api (same origin → no CORS needed).
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Where nginx finds the FastAPI backend. On Docker Desktop: http://host.docker.internal:8000
ENV BACKEND_URL=http://host.docker.internal:8000
EXPOSE 80
