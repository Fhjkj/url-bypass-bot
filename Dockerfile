FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    CHROMIUM_PATH=/usr/bin/chromium \
    SOLVER_API=https://turnstile-solver-production-7e59.up.railway.app \
    BYPASS_PROXY_POOL="http://A6b4nU8pS:fsjp9n9t7@172.120.57.232:62426,http://Lwscy8Syj:yZ8F8MGXq@172.120.57.74:62426,http://mQU5tajVR:DahYzcaVL@172.120.234.39:64694,http://U36PLFFKq:hjKgiFhFc@155.212.114.109:63856,http://eUZBmi8ME:jSz6iKwjv@155.212.114.15:64964,http://KgY3n8fPz:BVbBzkz3W@155.212.114.156:63856,http://t889uUyMQ:eEZ6GyfbW@155.212.114.162:63856"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/* \
    && test -x /usr/bin/chromium \
    && chromium --version

# Install Playwright browsers
RUN playwright install chromium

COPY . .

EXPOSE 10000
CMD ["python", "bot.py"]
