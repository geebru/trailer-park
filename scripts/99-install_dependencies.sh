#!/usr/bin/env bash
# =====================================================================
# Trailer Park — Dependency Installer
# Runs once at container startup to ensure all tools are available.
# =====================================================================

echo '[trailer-park] Installing dependencies...\n'

# Install ffmpeg and jq via apk if not already present
for _pkg in ffmpeg jq curl; do
    apk info -e "$_pkg" >/dev/null 2>&1 || apk add --no-cache "$_pkg"
done

# Always update yt-dlp — it breaks against YouTube changes frequently
curl -sSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod a+rx /usr/local/bin/yt-dlp

echo '[trailer-park] yt-dlp %s ready.\n' "$(yt-dlp --version 2>/dev/null)"