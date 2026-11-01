FROM python:3.12-alpine

RUN apk add --no-cache \
      ffmpeg \
      curl \
      deno \
 && pip install --no-cache-dir \
      --break-system-packages \
      yt-dlp \
      flask \
      waitress \
 && mkdir -p /etc \
 && echo '--remote-components ejs:github' > /etc/yt-dlp.conf

WORKDIR /app

COPY engine.py .
COPY app.py .
COPY api.py .
COPY library_cache.py .
COPY jobs.py .
COPY templates ./templates
COPY static ./static

EXPOSE 8080

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--threads=4", "app:app"]
