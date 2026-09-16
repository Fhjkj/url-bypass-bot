import os
import re
from time import monotonic_ns


def _configured_proxies() -> list[str]:
    raw = os.getenv("BYPASS_PROXY_POOL", "")
    values = re.findall(r"https?://[^\s,'\"}]+", raw)
    if not values and os.getenv("BYPASS_PROXY_URL"):
        values = [os.environ["BYPASS_PROXY_URL"].strip()]
    return values


def next_proxy() -> str | None:
    values = _configured_proxies()
    if not values:
        return None
    return values[monotonic_ns() % len(values)]
