# FZBypassBot deployment

This repository contains the MIT-licensed [FZBypassBot](https://github.com/SilentDemonSD/FZBypassBot) implementation, integrated with a small Flask health endpoint for web deployments.

## Features

- Multi-link asynchronous bypassing.
- Nested shortener bypass loops.
- Authorized chats and topic support.
- Inline mode through `!bp <link>`.
- Supported direct-download, file-hosting, DDL, Google Drive, and scrape handlers from the upstream project.
- `/health` endpoint for deployment health checks.

## Required environment variables

Set `BOT_TOKEN`, `API_ID`, and `API_HASH`. Set `OWNER_ID` for owner-only controls and `AUTH_CHATS` for authorized group/topic access. See `sample_config.env` for optional cookies, tokens, and site settings.

## Run

```bash
pip install -r requirements.txt
python bot.py
```

The Flask health server listens on port `10000` by default. The Telegram bot runs in the same process.

## Attribution

The bypass engine is reused under the MIT License from Silent Demon SD (MysterySD). See `LICENSE`.
