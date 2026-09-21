"""Handler for javhdporn.net video URLs.

Uses Turnstile Solver API to bypass Cloudflare and extract
the HLS video URL from the encrypted page.
"""
import os
import re
import httpx
from FZBypass.core.exceptions import DDLException


async def javhdporn(url: str) -> str:
    """Extract video URL from javhdporn.net."""
    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Step 1: Solve CF challenge - the solver returns HTML with cleared cookies
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{SOLVER_API}/solve-challenge",
                json={
                    "siteurl": url,
                    "timeout": 60
                },
                timeout=120
            )
            if response.status_code != 200:
                raise DDLException("Failed to solve CF challenge via Solver API")
            result = response.json()
        except Exception as e:
            raise DDLException(f"Solver API connection error: {str(e)}")

    html = result.get("html", "")
    if not html:
        raise DDLException("No HTML returned from Solver API")

    # Step 2: Extract video URL directly from HTML
    # Look for HLS master playlist URLs
    hls_urls = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)

    # Filter out ads, tracking, and ping URLs
    hls_urls = [
        u for u in hls_urls
        if 'banner' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'ping.m3u8' not in u.lower()
        and 'ads' not in u.lower()
        and 'doppiocdn' in u.lower()
    ]

    # Prefer master playlists
    master_urls = [u for u in hls_urls if 'master' in u.lower()]
    if not master_urls:
        master_urls = [u for u in hls_urls if '_auto' in u.lower()]
    if not master_urls:
        master_urls = hls_urls

    if master_urls:
        return master_urls[0]

    # Also try to find MP4 URLs
    mp4_urls = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
    mp4_urls = [
        u for u in mp4_urls
        if 'banner' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'ads' not in u.lower()
    ]
    if mp4_urls:
        return mp4_urls[0]

    raise DDLException("No playable streaming video source detected in page HTML.")