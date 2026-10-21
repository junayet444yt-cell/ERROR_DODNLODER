FROM node:20-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# yt-dlp in its own venv (owned by the app user so it can self-update at runtime).
# [default] pulls in the JS-challenge solver YouTube needs; Node (already in this image) is the JS runtime.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -U "yt-dlp[default]" \
 && chown -R node:node /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
RUN mkdir -p /app/downloads && chown -R node:node /app
USER node
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm","start"]
