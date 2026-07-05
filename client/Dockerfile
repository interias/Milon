# Milon Frontend — Next.js 16 (App Router). Multi-Stage → schlankes Runtime-Image
# über output:"standalone" (nur getracte Dateien + minimaler server.js, kein volles node_modules).

# ---- 1. Dependencies (mit Layer-Cache über lockfile) ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- 2. Build ----
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# WICHTIG: Next bäckt das Rewrite-Ziel (next.config.ts) zur BUILD-Zeit in die routes-manifest.json;
# die Runtime-Env greift dafür nicht. Daher das Backend-Ziel als Build-Arg setzen.
ARG API_PROXY_TARGET=http://server:8000
ENV API_PROXY_TARGET=$API_PROXY_TARGET
# Telemetrie aus; Build erzeugt .next/standalone + .next/static
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- 3. Runtime (schlank) ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Nicht als root laufen
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# Standalone-Server + statische Assets (standalone kopiert public/static NICHT automatisch)
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
