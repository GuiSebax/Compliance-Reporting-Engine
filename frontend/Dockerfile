# --- deps: install once, cached while source changes ---
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- builder ---
FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time,
# not read at container start — so it must be supplied as a build ARG,
# not (only) a runtime `environment:` entry in docker-compose.yml.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN npm run build

# --- runtime: Next.js standalone output, non-root ---
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
# node:20-slim already ships a non-root "node" user (uid 1000) — reuse it
# instead of creating a new one.

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
RUN chown -R node:node /app

USER node
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
