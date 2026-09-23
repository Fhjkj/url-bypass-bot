#!/usr/bin/env python3
"""Pure HTTP method for lksfy.com following the 6-phase structure.

Uses the docker-configured solver API (SOLVER_API env var) and proxy pool
(BYPASS_PROXY_POOL env var) to solve Turnstile and avoid IP blocks.
"""

import json
import os
import random
import re
import time
import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _configured_proxies():
    """Read the BYPASS_PROXY_POOL env var (comma-separated URLs)."""
    raw = os.getenv("BYPASS_PROXY_POOL", "")
    return re.findall(r"https?://[^\s,'\"}]+", raw)


def next_proxy():
    """Return a sticky proxy from the pool, or None if unconfigured."""
    from time import monotonic_ns
    values = _configured_proxies()
    if not values:
        return None
    return values[monotonic_ns() % len(values)]


def solver_api():
    """Return the configured solver API base URL."""
    return os.getenv("SOLVER_API", "https://turnstile-solver-production-edc7.up.railway.app").rstrip("/")


def solve_turnstile_api(sitekey, proxy=None):
    """Solve Cloudflare Turnstile via the docker-configured solver API."""
    api = solver_api()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    payload = {
        "siteurl": "https://lksfy.com",
        "sitekey": sitekey,
        "timeout": 30,
    }
    r = requests.post(f"{api}/solve-challenge", json=payload, proxies=proxies, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Solver API returned status {r.status_code}: {r.text[:200]}")
    data = r.json()
    token = data.get("token") or data.get("cf-turnstile-response") or data.get("response")
    if not token:
        raise RuntimeError(f"Solver API response missing token: {data}")
    return token


def extract_turnstile_sitekey(soup):
    """Extract Turnstile sitekey by class name cf-turnstile."""
    widget = soup.find(class_="cf-turnstile")
    if widget:
        sitekey = widget.get("data-sitekey")
        if sitekey:
            return sitekey
    elem = soup.find(attrs={"data-sitekey": True})
    return elem.get("data-sitekey") if elem else None


def parse_lksfy_html(html_text):
    """BeautifulSoup method: parse lksfy.com HTML and return structured data.

    Returns a dict with:
      - sitekey: Cloudflare Turnstile data-sitekey (found via cf-turnstile class)
      - form_data: dict of every hidden input field inside the main form
      - action: form action attribute (URL to POST to)
      - title: page title (optional diagnostic)
    """
    soup = BeautifulSoup(html_text, "html.parser")

    sitekey = extract_turnstile_sitekey(soup)

    form = soup.find("form")
    form_data = {}
    action = ""
    if form:
        action = form.get("action", "")
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

    title = soup.title.string.strip() if soup.title else ""

    return {
        "sitekey": sitekey,
        "form_data": form_data,
        "action": action,
        "title": title,
    }


def lksfy_get_link(target_url, proxy=None, delay=12):
    """Run the 6-phase pure HTTP flow and return the final link.

    Uses the docker-configured SOLVER_API and BYPASS_PROXY_POOL env vars.
    """
    session = requests.Session()
    ua = random.choice(USER_AGENTS)
    session.headers.update(
        {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    )

    # PHASE 1: Initialize session with sticky proxy from pool
    if proxy is None:
        proxy = next_proxy()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})

    # PHASE 2: Inspect reverse-engineered web flow
    resp = session.get("https://lksfy.com", timeout=30)
    resp.raise_for_status()
    parsed = parse_lksfy_html(resp.text)

    sitekey = parsed["sitekey"]
    if not sitekey:
        raise RuntimeError("Could not find Turnstile sitekey")
    form_data = parsed["form_data"]
    action = parsed["action"]

    # PHASE 3: Solve Turnstile challenge via docker-configured solver API
    token = solve_turnstile_api(sitekey, proxy=proxy)

    # PHASE 4: The timing bypass
    time.sleep(delay)

    # PHASE 5: Execute final handshake
    submit_data = dict(form_data)
    submit_data["cf-turnstile-response"] = token
    submit_data["action"] = "get_link"
    submit_data["url"] = target_url

    if action.startswith("http"):
        submit_url = action
    else:
        submit_url = "https://lksfy.com" + action

    r = session.post(
        submit_url,
        data=submit_data,
        allow_redirects=False,
        timeout=30,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://lksfy.com/",
        },
    )

    # PHASE 6: Final parse
    if r.status_code == 302:
        return r.headers.get("Location")
    if r.status_code == 200:
        try:
            return r.json().get("url")
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"Unexpected response: {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "https://lksfy.com/UFMfmoi"
    try:
        link = lksfy_get_link(target)
        print(link)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)