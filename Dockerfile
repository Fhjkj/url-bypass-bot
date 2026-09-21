# Use your preferred Python base image
FROM python:3.10-slim

# Force Playwright to read/write from Render's exact expected path
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright
ENV CHROMIUM_PATH=/usr/bin/chromium
ENV SOLVER_API=https://turnstile-solver-production-7e59.up.railway.app
ENV BYPASS_PROXY_POOL="http://A6b4nU8pS:fsjp9n9t7@172.120.57.232:62426,http://Lwscy8Syj:yZ8F8MGXq@172.120.57.74:62426,http://mQU5tajVR:DahYzcaVL@172.120.234.39:64694,http://U36PLFFKq:hjKgiFhFc@155.212.114.109:63856,http://eUZBmi8ME:jSz6iKwjv@155.212.114.15:64964,http://KgY3n8fPz:BVbBzkz3W@155.212.114.156:63856,http://t889uUyMQ:eEZ6GyfbW@155.212.114.162:63856"

WORKDIR /app

# Install standard dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CRITICAL FIX: Download both chromium AND chromium-headless-shell
RUN playwright install chromium chromium-headless-shell --with-deps

COPY . .
CMD ["python", "bot.py"]