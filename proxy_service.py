"""
Standalone proxy service for extracting video URLs from encrypted sites.

Usage:
    python proxy_service.py
    curl "http://localhost:10000/extract?url=https://www.javhdporn.net/video/apak-095-decensored/"
"""

import asyncio
import json
import os
from flask import Flask, request, jsonify
import httpx
from playwright.async_api import async_playwright

app = Flask(__name__)

SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")


async def solve_cf_challenge(url):
    """Use Turnstile Solver to get clearance for a URL."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLVER_API}/solve-challenge",
            json={"siteurl": url, "timeout": 60},
            timeout=120
        )
        if response.status_code == 200:
            return response.json()
        return None


async def extract_video_url(url):
    """Extract video URL from an encrypted site."""
    # Step 1: Solve CF challenge
    result = await solve_cf_challenge(url)
    if not result:
        return {"success": False, "error": "Failed to solve CF challenge"}
    
    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # Step 2: Use Playwright to load page and click play
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent
        )
        page = await context.new_page()
        
        for cookie in cookies:
            await context.add_cookies([cookie])
        
        video_urls = []
        
        async def handle_request(request):
            req_url = request.url
            if any(ext in req_url.lower() for ext in ['.m3u8', '.mp4']):
                if req_url not in video_urls:
                    video_urls.append(req_url)
        
        page.on("request", handle_request)
        
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Click play button to trigger decryption
        try:
            await page.click(".play-button", timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass
        
        try:
            await page.click("#video-player", position={"x": 400, "y": 300}, timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass
        
        await page.wait_for_timeout(5000)
        await browser.close()
        
        # Filter for actual video URLs
        video_urls = [u for u in video_urls if 'banner' not in u.lower() and 'storagexhd' not in u.lower()]
        
        # Prefer HLS master playlists
        hls_urls = [u for u in video_urls if '.m3u8' in u and 'master' in u.lower()]
        if not hls_urls:
            hls_urls = [u for u in video_urls if '.m3u8' in u]
        
        if hls_urls:
            return {
                "success": True,
                "video_url": hls_urls[0],
                "all_urls": video_urls[:10]
            }
        elif video_urls:
            return {
                "success": True,
                "video_url": video_urls[0],
                "all_urls": video_urls[:10]
            }
        else:
            return {"success": False, "error": "No video URL found"}


@app.route('/extract', methods=['GET'])
def extract():
    """Extract video URL from a given URL."""
    url = request.args.get('url')
    if not url:
        return jsonify({"success": False, "error": "URL parameter required"}), 400
    
    try:
        result = asyncio.run(extract_video_url(url))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/bypass', methods=['GET'])
def bypass():
    """Bypass Cloudflare and extract video stream URL."""
    url = request.args.get('url')
    if not url:
        return jsonify({"success": False, "error": "URL parameter required"}), 400
    
    try:
        result = asyncio.run(extract_video_url(url))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "video-proxy",
        "endpoints": ["/extract", "/bypass", "/health"]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))