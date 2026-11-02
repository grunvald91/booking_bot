FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts && npm cache clean --force
COPY worker/server.mjs ./worker/server.mjs
USER node
ENV STATE_DIR=/state PORT=8793
CMD ["node","worker/server.mjs"]
