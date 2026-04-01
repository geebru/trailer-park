# Trailarr Parrk

Downloads trailers for movies and TV shows via TMDB and yt-dlp. Triggered automatically by Radarr on import/upgrade and Sonarr on series add, or run manually from the container console. Primarily useful for Jellyfin, which has no native trailer support.

---

## Requirements

- Linuxserver.io Radarr and/or Sonarr
- A free [TMDB read access token](https://www.themoviedb.org/settings/api) — the long v4 JWT, not the short v3 API key

---

## Files

| File | Purpose |
|---|---|
| `trailarr-parrk.sh` | Main script — config block is at the top, edit this file |
| `99-install_dependencies.sh` | Container init script, installs `ffmpeg`, `jq`, `curl`, and `yt-dlp` on startup |

One set of files per Arr instance.

---

## Setup

### 1. Create directories

```bash
mkdir -p /path/to/appdata/{radarr,sonarr}/{cont-init.d,scripts}
```

### 2. Install dependencies

Copy `99-install_dependencies.sh` into each `cont-init.d` folder and mount it in your Docker Compose:

Radarr:
```yaml
- /path/to/appdata/radarr/cont-init.d:/etc/cont-init.d
```
Sonarr:
```yaml
- /path/to/appdata/sonarr/cont-init.d:/etc/cont-init.d
```

Restart each container. Dependencies will be installed automatically on every start.

### 3. Configure

Copy `trailarr-parrk.sh` into each scripts directory:
```
/path/to/appdata/radarr/scripts/
/path/to/appdata/sonarr/scripts/
```

Edit the config block near the top of `trailarr-parrk.sh` and add your TMDB read access token.

### 4. Set permissions

```bash
chmod +x trailarr-parrk.sh
chown PUID:PGID trailarr-parrk.sh
```

Replace `PUID:PGID` with the values set in your container environment.

### 5. Connect to Radarr and Sonarr

**Settings → Connect → Custom Script → Add New**

| App | Script path | Events |
|---|---|---|
| Radarr | `/config/scripts/trailarr-parrk.sh` | On Import, On Upgrade |
| Sonarr | `/config/scripts/trailarr-parrk.sh` | On Series Add |

For Sonarr's **On Series Add** to work, enable **Create Empty Series Folders** in Settings → Media Management. This fires once when a show is added — not per episode.

Use the **Test** button to confirm the script is found and executable.

---

## Configuration Reference

All options live in the config block at the top of `trailarr-parrk.sh`.

| Option | Default | Description |
|---|---|---|
| `TMDB_API_KEY` _(required)_ | _(empty)_ | TMDB v4 read access token |
| `PREFERRED_TERMS` | `"official,trailer,teaser,theatrical"` | Comma-separated. Each match adds +10 to the trailer's score. Trailers scoring 0 are skipped. Case-insensitive. |
| `EXCLUDED_TERMS` | `"fan made,fan-made,reaction,parody,review,recut,behind the scenes,featurette"` | Comma-separated. Any match disqualifies a trailer entirely. Case-insensitive. |
| `TRAILER_FOLDER` | `"trailers"` | Subfolder inside the media folder. Leave empty `""` to save directly into the media folder. |
| `FILENAME_TEMPLATE` | `"{title} ({year}).trailer"` | Output filename without extension. Supports `{title}` and `{year}` tokens. |
| `VIDEO_QUALITY` | `"1080"` | Max download height passed to yt-dlp. |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Webhook URL for download and failure notifications. Leave empty to disable. |

---

## Trailer Selection

The script fetches all videos linked to a title on TMDB, filters by site (YouTube) and type (Trailer), then scores each candidate:

| Points | Condition |
|---|---|
| +10 | Each `PREFERRED_TERMS` match in the trailer name |

Trailers are excluded entirely if their name contains any `EXCLUDED_TERMS`. Trailers with a score of 0 (no preferred term matches) are also skipped. The highest scoring trailer wins.

---

## Manual Usage

Run from inside the Radarr or Sonarr container console.

**Simulate an automatic run** by setting the same environment variables Radarr/Sonarr would pass:

```bash
# Dry run — scores and lists candidates without downloading
radarr_eventtype="Download" radarr_movie_title="Dune" \
  radarr_movie_year="2021" radarr_movie_path="/movies/Dune (2021)" \
  radarr_movie_tmdbid="438631" sh /config/scripts/trailarr-parrk.sh --dry-run

# Normal run
radarr_eventtype="Download" radarr_movie_title="Dune" \
  radarr_movie_year="2021" radarr_movie_path="/movies/Dune (2021)" \
  radarr_movie_tmdbid="438631" sh /config/scripts/trailarr-parrk.sh
```

**Force-download a specific YouTube video** (bypasses TMDB and scoring entirely):

```bash
# Download to current directory
/config/scripts/trailarr-parrk.sh --yt-id dUKFnBqlVSI --title "Parasite" --year 2019

# Download to a specific path, dry run first
/config/scripts/trailarr-parrk.sh --yt-id dUKFnBqlVSI --title "Parasite" --year 2019 \
  --output "/data/movies/Parasite (2019)" --dry-run
```

### Flags

| Flag | Description |
|---|---|
| `--yt-id <id>` | Download a specific YouTube video, bypasses TMDB and scoring |
| `--title "Title"` | Title used for the output filename (required with `--yt-id`) |
| `--year <year>` | Year used for the output filename (required with `--yt-id`) |
| `--output <path>` | Output directory (optional, defaults to current directory) |
| `--dry-run` | Log actions without downloading |

When triggered automatically by Radarr or Sonarr, no flags are needed — the script reads the event environment variables directly.

---

## Discord Notifications

Set `DISCORD_WEBHOOK_URL` in the script config to receive notifications on:

- Trailer downloaded (includes YouTube URL and score)
- No valid trailers found (all excluded or scored 0)
- Download failed

To create a webhook: **Discord Server Settings → Integrations → Webhooks → New Webhook**.

---

## Troubleshooting

**Script not triggering** — Check that the file is executable (`chmod +x`) and ownership matches the container's `PUID:PGID`.

**`yt-dlp`, `ffmpeg`, or `jq` not found** — Confirm `99-install_dependencies.sh` is in `cont-init.d` and the volume mount is correct. Restart the container and check startup logs.

**Wrong trailer selected** — Simulate a run with `--dry-run` (via env vars) to see scored candidates. Adjust `PREFERRED_TERMS` and `EXCLUDED_TERMS` in the script config.

**Private or unavailable video** — The YouTube video linked on TMDB is unavailable. Use `--yt-id` with a working public video ID.

**API errors** — Confirm `TMDB_API_KEY` is set to the v4 read access token (the long JWT string from your TMDB API settings page), not the short v3 key.