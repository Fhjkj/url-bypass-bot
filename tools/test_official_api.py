#!/usr/bin/env python3
"""Test an authorized shortener destination API.

Required environment variables:
  DESTINATION_API_URL  Official API endpoint
  DESTINATION_API_KEY  API key/token

Optional:
  DESTINATION_API_AUTH  Header name for the key (default: Authorization)
  DESTINATION_API_KEY_PREFIX  Prefix such as "Bearer " (default: "Bearer ")
  DESTINATION_API_URL_PARAM  URL parameter name (default: url)
  DESTINATION_API_METHOD  GET or POST (default: GET)
  SOURCE_URL  Short URL to resolve

This script does not bypass CAPTCHA, Cloudflare, authentication, or access
controls. Use only an API and credentials supplied by the provider.
"""
import json
import os
import sys
from urllib.parse import urlparse

import requests


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def find_destination(payload):
    """Extract common destination fields without assuming a provider schema."""
    if isinstance(payload, dict):
        for key in ("destination", "destination_url", "final_url", "final", "url", "link"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        for value in payload.values():
            found = find_destination(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_destination(value)
            if found:
                return found
    return None


def main() -> int:
    endpoint = required("DESTINATION_API_URL")
    api_key = required("DESTINATION_API_KEY")
    source = required("SOURCE_URL")
    method = os.getenv("DESTINATION_API_METHOD", "GET").upper()
    param = os.getenv("DESTINATION_API_URL_PARAM", "url")
    auth_header = os.getenv("DESTINATION_API_AUTH", "Authorization")
    prefix = os.getenv("DESTINATION_API_KEY_PREFIX", "Bearer ")

    headers = {
        "Accept": "application/json",
        auth_header: prefix + api_key,
        "User-Agent": "AuthorizedDestinationAPI-Test/1.0",
    }
    timeout = float(os.getenv("DESTINATION_API_TIMEOUT", "30"))

    try:
        if method == "POST":
            response = requests.post(
                endpoint, json={param: source}, headers=headers, timeout=timeout
            )
        elif method == "GET":
            response = requests.get(
                endpoint, params={param: source}, headers=headers, timeout=timeout
            )
        else:
            raise SystemExit("DESTINATION_API_METHOD must be GET or POST")
    except requests.RequestException as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return 2

    print(f"HTTP status: {response.status_code}")
    if not response.ok:
        print(response.text[:1000], file=sys.stderr)
        return 3

    try:
        payload = response.json()
    except ValueError:
        print("API did not return JSON:")
        print(response.text[:2000])
        return 4

    destination = find_destination(payload)
    if not destination:
        print("No destination URL found in the API response.")
        print(json.dumps(payload, indent=2)[:4000])
        return 5

    parsed = urlparse(destination)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print(f"Invalid destination URL returned: {destination}", file=sys.stderr)
        return 6

    print(f"FINAL_DESTINATION={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
