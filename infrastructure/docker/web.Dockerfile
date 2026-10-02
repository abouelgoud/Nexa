# Next.js web app from the npm workspace. Build context: repository root.
FROM node:22-alpine AS deps
WORKDIR /repo
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/agent-schema/package.json packages/agent-schema/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/workflow-engine/package.json packages/workflow-engine/package.json
RUN npm ci --workspaces --include-workspace-root

FROM deps AS build
# Browser calls go to /api on the web origin; the Next.js server proxies them to API_INTERNAL_URL.
ARG API_INTERNAL_URL=http://api:8000
ARG NEXT_PUBLIC_API_URL=
ENV API_INTERNAL_URL=$API_INTERNAL_URL NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
COPY packages packages
COPY apps/web apps/web
RUN npm run build -w @nexa/web

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
