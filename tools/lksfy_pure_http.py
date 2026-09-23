#!/usr/bin/env python3
"""Pure HTTP method for lksfy.com following the 6-phase structure."""

import json
import random
import time
import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

PROXIES = []  # Optional: list of "http://user:pass@ip:port" strings


def solve_turnstile_api(sitekey, proxy=None):
    """Solve Cloudflare Turnstile via 2CAPTCHA-compatible API."""
    api_key = "YOUR_2CAPTCHA_API_KEY"  # Replace with real key
    payload = {
        "key": api_key,
        "json": 1,
        "action": "turnstile",
        "sitekey": sitekey,
        "url": "https://lksfy.com",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.post("https://2captcha.com/in.php", data=payload, proxies=proxies)
    data = r.json()
    if data.get("status") != 1:
        raise RuntimeError(f"Solver rejected: {data}")
    captcha_id = data["request"]
    for _ in range(60):
        time.sleep(5)
        poll = requests.get(
            "https://2captcha.com/res.php",
            params={"key": api_key, "action": "get", "id": captcha_id, "json": 1},
            proxies=proxies,
        ).json()
        if poll.get("status") == 1:
            return poll["request"]
        if poll.get("request") in ("ERROR_BAD_TOKEN", "ERROR_CAPTCHA_UNSOLVABLE"):
            raise RuntimeError(poll["request"])
    raise RuntimeError("Turnstile solve timed out")


def extract_form_data(soup):
    """Harvest every hidden input field inside the main form."""
    form = soup.find("form")
    if not form:
        raise RuntimeError("No form found on page")
    data = {}
    for inp in form.find_all("input", {"type": "hidden"}):
        name = inp.get("name")
        value = inp.get("value", "")
        if name:
            data[name] = value
    action = form.get("action", "")
    return data, action


def extract_turnstile_sitekey(soup):
    """Extract Turnstile sitekey by class name cf-turnstile."""
    widget = soup.find(class_="cf-turnstile")
    if widget:
        sitekey = widget.get("data-sitekey")
        if sitekey:
            return sitekey
    # Fallback: any element with data-sitekey
    elem = soup.find(attrs={"data-sitekey": True})
    return elem.get("data-sitekey") if elem else None


def lksfy_get_link(target_url, api_key=None, proxy=None, delay=12):
    """Run the 6-phase pure HTTP flow and return the final link."""
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
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})

    # PHASE 2: Inspect reverse-engineered web flow
    resp = session.get("https://lksfy.com", timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    sitekey = extract_turnstile_sitekey(soup)
    if not sitekey:
        raise RuntimeError("Could not find Turnstile sitekey")
    form_data, action = extract_form_data(soup)

    # PHASE 3: Solve Turnstile challenge via API
    token = solve_turnstile_api(sitekey, proxy=proxy)

    # PHASE 4: Timing bypass
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
    api = sys.argv[2] if len(sys.argv) > 2 else None
    px = sys.argv[3] if len(sys.argv) > 3 else None
    try:
        link = lksfy_get_link(target, api_key=api, proxy=px)
        print(link)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)