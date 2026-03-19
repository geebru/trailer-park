# Trailarr Parrk

Downloads trailers for movies and TV shows via TMDB and yt-dlp. Triggered automatically by Radarr on import/upgrade and Sonarr on series add, or run manually from the container console. Primarily useful for Jellyfin, which has no native trailer support.

---

## Requirements

- Linuxserver.io Radarr and/or Sonarr
- A free [TMDB v3 API key](https://www.themoviedb.org/settings/api) — the short hex string, not the JWT read access token

---

## Files

| File | Purpose |
|---|---|
| `trailarr-parrk.conf` | All configuration — edit this file only |
| `trailarr-parrk.sh` | Main script, handles both automated and manual runs |
| `99-install-dependencies.sh` | Container init script, installs `jq` and `yt-dlp` on startup |

One set of files per Arr instance.

---

## Setup

### 1. Create directories

```bash
mkdir -p /path/to/appdata/{radarr,sonarr}/{cont-init.d,scripts}
```

### 2. Install dependencies

Copy `99-install-dependencies.sh` into each `cont-init.d` folder and mount it in your Docker Compose:

Radarr:
```yaml
- /path/to/appdata/radarr/cont-init.d:/etc/cont-init.d
```
Sonarr:
```yaml
- /path/to/appdata/sonarr/cont-init.d:/etc/cont-init.d
```

Restart each container. `jq` and `yt-dlp` will be installed automatically on every start.

### 3. Configure

Copy `trailarr-parrk.conf` and `trailarr-parrk.sh` into each scripts directory:
```
/path/to/appdata/radarr/scripts/
/path/to/appdata/sonarr/scripts/
```

Add your TMDB API key to `trailarr-parrk.conf` and adjust any other settings.

### 4. Set permissions

```bash
chmod +x trailarr-parrk.sh
chown PUID:PGID trailarr-parrk.sh trailarr-parrk.conf
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

All options live in `trailarr-parrk.conf`.

| Option | Default | Description |
|---|---|---|
| `TMDB_API_KEY` _(required)_ | _(empty)_ | TMDB v3 API key |
| `DRY_RUN` | `false` | Log actions without downloading |
| `TRAILER_SUBDIR` | `trailers` | Subdirectory within the media folder. Leave empty to save alongside media |
| `FILENAME_OVERRIDE` | _(empty)_ | Override output filename. Auto-generates `Title (Year).trailer.mkv` if empty |
| `PREFERRED_TERMS` | `("official" "trailer")` | At least one term must appear in the trailer name. Leave empty to allow any |
| `EXCLUDED_TERMS` | `("teaser" "clip" "reaction" "interview" "tv spot" "behind the scenes" "b&w" "fan" "fanmade")` | Trailers containing any of these terms are skipped |
| `DISCORD_WEBHOOK` | _(empty)_ | Webhook URL for download and failure notifications. Leave empty to disable |
| `YT_COOKIES` | _(empty)_ | Path to a Netscape-format cookies file for yt-dlp, for age-restricted videos |
| `MAX_CALLS` | `30` | TMDB API calls allowed per window |
| `WINDOW_SECONDS` | `10` | Rate limit window in seconds |

---

## Trailer Selection

The script fetches all videos linked to a title on TMDB and scores each candidate:

| Points | Condition |
|---|---|
| +60 | Trailer language matches the title's original language |
| +40 | Trailer language is English (fallback) |
| +20 | Each `PREFERRED_TERMS` match in the trailer name |

Trailers are skipped entirely if their name contains any `EXCLUDED_TERMS`, or if no `PREFERRED_TERMS` match when the list is non-empty. The highest scoring trailer wins.

Note: TMDB tags most trailers as `en` regardless of actual language, including foreign-language prints with burned-in subtitles. The language scoring reflects this reality — it will prefer a correctly tagged original-language trailer when one exists, but most titles will resolve to English.

---

## Manual Usage

Run from inside the Radarr or Sonarr container console.

```bash
# Dry run — show what would be selected without downloading
bash /config/scripts/trailarr-parrk.sh --movie "Parasite" --path "/data/movies/Parasite (2019)" --dry-run

# Normal run — TMDB lookup and scoring as usual
bash /config/scripts/trailarr-parrk.sh --movie "Parasite" --path "/data/movies/Parasite (2019)"

# Override with a specific YouTube ID — skips TMDB entirely
bash /config/scripts/trailarr-parrk.sh --movie "Parasite" --path "/data/movies/Parasite (2019)" --yt-id dUKFnBqlVSI

# Look up by TMDB ID instead of title
bash /config/scripts/trailarr-parrk.sh --id 496243 --path "/data/movies/Parasite (2019)"

# TV show
bash /config/scripts/trailarr-parrk.sh --series "The Bear" --path "/data/shows/The Bear (2022)"
```

### Flags

| Flag | Description |
|---|---|
| `--movie "Title"` | Search TMDB by movie title |
| `--series "Title"` | Search TMDB by series title |
| `--id <tmdb_id>` | Look up by TMDB ID directly, skips title search |
| `--path "/path"` | Media folder path, used to resolve output location |
| `--yt-id <id>` | Download a specific YouTube video, bypasses TMDB and scoring |
| `--dry-run` | Log actions without downloading |

`--movie` or `--series` with `--path` is the minimum required for a manual run. If a title search returns multiple matches, the script will list them with their TMDB IDs and ask you to re-run with `--id`.

When triggered automatically by Radarr or Sonarr, no flags are needed — the script reads the event environment variables directly.

---

## Discord Notifications

Set `DISCORD_WEBHOOK` in the conf to receive notifications on:

- Trailer downloaded (includes YouTube URL and score)
- Trailer manually replaced via `--yt-id`
- No trailers found on TMDB
- No trailer passed filtering
- Download failed

To create a webhook: **Discord Server Settings → Integrations → Webhooks → New Webhook**.

---

## Troubleshooting

**Script not triggering** — Check that the file is executable (`chmod +x`) and ownership matches the container's `PUID:PGID`.

**`yt-dlp` or `jq` not found** — Confirm `99-install-dependencies.sh` is in `cont-init.d` and the volume mount is correct. Restart the container and check startup logs.

**Wrong trailer selected** — Run with `--dry-run` to see candidates. Adjust `PREFERRED_TERMS` and `EXCLUDED_TERMS` in the conf.

**Age-restricted video fails** — Export a `cookies.txt` from your browser using a browser extension and set `YT_COOKIES` in the conf to the file path.

**Private video error** — The YouTube video linked on TMDB is unavailable. Use `--yt-id` with a working public video ID.

**Multiple title matches** — Re-run with `--id` using one of the TMDB IDs listed in the output.