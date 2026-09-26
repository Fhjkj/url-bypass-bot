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

Set `BOT_TOKEN`, `API_ID`, and `API_HASH`. Set `OWNER_ID` for owner-only controls and `AUTH_CHATS` for authorized group/topic access. Set `MONGODB_URI` to persist sudo users across restarts and redeployments; its URI should include a database name, or set `MONGODB_DATABASE` explicitly. See `sample_config.env` for the available settings.

## Bypass and sudo access

- In **private chat**, authorized users can send supported links without a command.
- In **groups**, start a request with `/bypass <link>` (or reply to a supported social-media link with `/bypass`). A bare group link is ignored.
- Each URL is classified once as social media, an ad shortener, a sharing/movie provider, or a generic link; duplicate URLs are collapsed, and social media is sent only to its downloader while every other category goes through the resolver once.
- The bot owner can grant/revoke persistent sudo access with `/addsudo <telegram_id>` and `/rmsudo <telegram_id>`. Sudo users receive the bot's normal authorized access, including `/bypass`, `/bash`, `/shell`, `/log`, and `/restart`; only the owner can manage sudo users.
- The owner or a sudo user can persistently allow or revoke a group with `/authorize` or `/unauthorize` inside that group, or pass a group ID, such as `/authorize -1001234567890`. Group overrides are stored in MongoDB and take precedence over `AUTH_CHATS`.

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
