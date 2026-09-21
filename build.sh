#!/usr/bin/env bash
set -o errexit

# Upgrade dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Let Playwright use its default cache path
playwright install chromium --with-deps