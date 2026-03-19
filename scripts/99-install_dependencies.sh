#!/usr/bin/env bash
# =====================================================================
# Trailarr Parrk — Dependency Installer
# Runs once at container startup to ensure all tools are available.
# =====================================================================

echo "[Trailarr Parrk] Installing dependencies..."

apk add --no-cache curl jq python3 py3-pip >/dev/null 2>&1
pip install --no-cache-dir --break-system-packages yt-dlp >/dev/null 2>&1

echo "[Trailarr Parrk] Dependencies installed successfully."