# Use the official Playwright image that includes Python and all browsers pre-installed
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app

# Copy your dependency files and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot files into the container
COPY . .

# Start your Telegram bypass bot
CMD ["python", "bot.py"]
