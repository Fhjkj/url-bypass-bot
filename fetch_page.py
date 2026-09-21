"""Fetch javhdporn.net page HTML via Turnstile solver and analyze it."""
import asyncio
import httpx
import json
import os

SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")
URL = "https://www.javhdporn.net/video/apak-095-decensored/"


async def fetch():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLVER_API}/solve-challenge",
            json={"siteurl": URL, "timeout": 60},
            timeout=120
        )
        result = response.json()
        print(f"Success: {result.get('success')}")
        print(f"Final URL: {result.get('final_url')}")

        html = result.get("html", "")
        if html:
            with open("/tmp/jav_page.html", "w") as f:
                f.write(html)
            print(f"HTML saved, length: {len(html)}")

            # Search for video-related patterns
            import re

            # Look for m3u8 URLs
            m3u8 = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
            print(f"\n=== M3U8 URLs found ===")
            for u in m3u8:
                print(f"  {u}")

            # Look for mp4 URLs
            mp4 = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
            print(f"\n=== MP4 URLs found ===")
            for u in mp4:
                print(f"  {u}")

            # Look for video-related data attributes
            data_attrs = re.findall(r'data-[a-z]+="([^"]*)"', html)
            print(f"\n=== Data attributes ===")
            for attr in data_attrs:
                if any(k in attr.lower() for k in ['video', 'mpu', 'source', 'url', 'src', 'file']):
                    print(f"  {attr[:200]}")

            # Look for wpst-video or video-player
            if 'wpst-video' in html:
                idx = html.find('wpst-video')
                print(f"\n=== wpst-video context ===")
                print(html[max(0,idx-200):idx+500])

            if 'video-player' in html:
                idx = html.find('video-player')
                print(f"\n=== video-player context ===")
                print(html[max(0,idx-200):idx+500])

            # Look for ajax endpoints
            ajax = re.findall(r'(?:ajax|api|endpoint|fetch|url)\s*[:=]\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
            print(f"\n=== Possible AJAX endpoints ===")
            for a in ajax:
                if any(k in a.lower() for k in ['video', 'play', 'get', 'source', 'mp4', 'm3u8', 'stream']):
                    print(f"  {a}")

            # Look for JavaScript that handles video
            js_patterns = re.findall(r'(?:video|play|source|stream|getVideo|loadVideo)[^;]{0,200}', html, re.IGNORECASE)
            print(f"\n=== Video-related JS patterns ===")
            for p in js_patterns[:20]:
                print(f"  {p[:200]}")

            # Look for encrypted data
            if 'data-mpu' in html:
                idx = html.find('data-mpu')
                print(f"\n=== data-mpu context ===")
                print(html[max(0,idx-200):idx+500])

            # Search for any encoded/encrypted video data
            enc_patterns = re.findall(r'(?:encrypted|cipher|decrypt|encoded|token|key)\s*[:=]\s*["\']([^"\']{10,})["\']', html, re.IGNORECASE)
            print(f"\n=== Encrypted data patterns ===")
            for p in enc_patterns[:10]:
                print(f"  {p[:200]}")

        await client.aclose()


if __name__ == "__main__":
    asyncio.run(fetch())