FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Trailer Park" \
      org.opencontainers.image.description="Downloads local trailers for Radarr and Sonarr titles using TMDB and yt-dlp." \
      org.opencontainers.image.source="https://github.com/geebru/trailer-park"

RUN apk add --no-cache \
      ffmpeg \
      curl \
      deno \
 && mkdir -p /etc \
 && echo '--remote-components ejs:github' > /etc/yt-dlp.conf

WORKDIR /app

# Flask and Waitress are pinned in requirements.txt. yt-dlp is not: the app updates it from Settings.
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt yt-dlp

COPY engine.py .
COPY app.py .
COPY api.py .
COPY library_cache.py .
COPY jobs.py .
COPY templates ./templates
COPY static ./static

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--threads=4", "app:app"]
