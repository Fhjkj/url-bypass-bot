# Use the official Playwright image that includes Python and all browsers pre-installed
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Copy your dependency files and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot files into the container
COPY . .

# Start your Telegram bypass bot
CMD ["python", "bot.py"]