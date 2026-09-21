#!/usr/bin/env bash
# exit on error
set -o errexit

# Upgrade pip and install standard packages
pip install --upgrade pip
pip install -r requirements.txt

# Force Playwright to download Chromium to a persistent location
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.cache/ms-playwright
playwright install chromium chromium-headless-shell --with-deps