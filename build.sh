#!/usr/bin/env bash
set -o errexit

# Install your app dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Force Playwright to download the complete browser system to the exact path needed
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/ms-playwright
playwright install chromium chromium-headless-shell --with-deps