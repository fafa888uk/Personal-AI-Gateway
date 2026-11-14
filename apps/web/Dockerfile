# Personal AI Gateway — web image
# node:20 build (npm ci + next build), then run with `next start`.
# NOTE: next.config.ts does not enable `output: "standalone"`, so the
# runtime stage carries node_modules + .next (larger image, simpler and
# faithful to the tested `npm run build` / `npm start` flow). Switching to
# standalone output is a later optimisation, not a silent change here.
# The web app never holds the OpenAI key; the gateway URL comes from
# NEXT_PUBLIC_GATEWAY_URL at build time or from the browser's localStorage
# at runtime (see apps/web/src/lib/credentials.ts).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-slim AS runtime
ENV NODE_ENV=production \
    PORT=3000
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.ts ./next.config.ts
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 3000
CMD ["npm", "start"]
