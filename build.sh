#!/usr/bin/env bash
set -o errexit

# Clean out any old/broken extraction caches
rm -rf /opt/render/project/src/.cache/ms-playwright/*

# Upgrade dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Force download of the full unified Chromium stack
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.cache/ms-playwright
playwright install chromium --with-deps
playwright install chromium-headless-shell --with-deps