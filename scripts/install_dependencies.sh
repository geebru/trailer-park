#!/bin/bash

echo "Using apk to install dependencies..."
if command -v apk &> /dev/null; then
    apk update && \
    apk add jq yt-dlp && \
    rm -rf /var/cache/apk/*
else
    echo "apk not found. Cannot install dependencies."
fi

echo "Installation complete."