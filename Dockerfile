# Use the official Playwright image that includes Python and all browsers pre-installed
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    SOLVER_API=https://turnstile-solver-production-edc7.up.railway.app \
    BYPASS_PROXY_POOL="http://A6b4nU8pS:fsjp9n9t7@172.120.57.232:62426,http://Lwscy8Syj:yZ8F8MGXq@172.120.57.74:62426,http://mQU5tajVR:DahYzcaVL@172.120.234.39:64694,http://U36PLFFKq:hjKgiFhFc@155.212.114.109:63856,http://eUZBmi8ME:jSz6iKwjv@155.212.114.15:64964,http://KgY3n8fPz:BVbBzkz3W@155.212.114.156:63856,http://t889uUyMQ:eEZ6GyfbW@155.212.114.162:63856"

WORKDIR /app

# Copy your dependency files and install them
COPY requirements.txt .
RUN pip install --no-cache-dir --force-reinstall --no-binary :all: greenlet && pip install --no-cache-dir -r requirements.txt

# Copy your bot files into the container
COPY . .

# Start your Telegram bypass bot
CMD ["python", "bot.py"]