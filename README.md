# FZBypassBot deployment

This repository contains the MIT-licensed [FZBypassBot](https://github.com/SilentDemonSD/FZBypassBot) implementation, integrated with a small Flask health endpoint for web deployments.

## Features

- Multi-link asynchronous bypassing.
- Nested shortener bypass loops.
- Authorized chats and topic support.
- Inline mode through `!bp <link>`.
- Supported direct-download, file-hosting, DDL, Google Drive, and scrape handlers from the upstream project.
- `/health` endpoint for deployment health checks.
- `/solve` and `/solve-challenge` endpoints for Cloudflare Turnstile resolution via a persistent Chromium profile.

## Cloudflare Turnstile Solver

`POST /solve` (or `/solve-challenge`) launches/reuses a Chromium browser profile,
navigates to the protected page, waits for the Turnstile widget to clear, and
returns the resulting token and clearance cookies.

**Request** (`POST /solve`, JSON):

```json
{
  "url": "https://protected-site.example.com",
  "timeout_ms": 45000,
  "headless": true
}
```

**Response**:

```json
{
  "success": true,
  "url": "https://protected-site.example.com",
  "final_url": "https://protected-site.example.com/dashboard",
  "token": "0xabc...",
  "cookies": [{"name": "cf_clearance", "value": "..."}],
  "clearance_cookie": "...",
  "error": null,
  "elapsed_ms": 8234
}
```

The browser profile is persisted to `CHROMIUM_PROFILE_DIR` (default
`/tmp/chromium-profile`) so repeat requests reuse cached clearance.

## Required environment variables

Set `BOT_TOKEN`, `API_ID`, and `API_HASH`. Set `OWNER_ID` for owner-only controls and `AUTH_CHATS` for authorized group/topic access. See `sample_config.env` for optional cookies, tokens, and site settings.

## Solver configuration

| Variable | Default | Description |
| --- | --- | --- |
| `CHROMIUM_PROFILE_DIR` | `/tmp/chromium-profile` | Persistent browser profile path |
| `CHROMIUM_PATH` | `/usr/bin/chromium` | Custom Chromium binary path |
| `SOLVE_TIMEOUT_MS` | `45000` | Navigation timeout per request |
| `SOLVE_MAX_WAIT_MS` | `90000` | Max time to wait for challenge resolution |

## Run

```bash
pip install -r requirements.txt
python bot.py
```

The Flask health server listens on Render's `$PORT` (falling back to `10000` locally). The Telegram bot runs in the same process.

## Attribution

The bypass engine is reused under the MIT License from Silent Demon SD (MysterySD). See `LICENSE`.


## Render deployment

Create a Render **Web Service** using this repository, or use the included `render.yaml` Blueprint. Render should use the Python runtime with:

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Health path: `/health`

Add the Telegram credentials and access settings as Render environment variables. Do not commit secrets to the repository.
