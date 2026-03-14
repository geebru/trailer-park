# 🎬 Trailarr Parrk

Downloads trailers for movies and TV shows via TMDB and yt-dlp, triggered automatically by Radarr and Sonarr on import, or run manually. Mostly useful for Jellyfin, which doesn't handle trailers natively outside of loading YouTube searches in iFrames.

---

## Requirements

- Linuxserver.io Radarr and/or Sonarr
- A free [TMDB API Read Access Token](https://www.themoviedb.org/settings/api)

---

## Files

| File | Purpose |
|---|---|
| `fetch-trailer.conf` | All configuration — edit this file only |
| `fetch-trailer.sh` | Main script, triggered automatically by Radarr/Sonarr |
| `fetch-trailer-manual.sh` | Manual script for adding or replacing individual trailers |
| `install_dependencies.sh` | Container init script that installs `jq` and `yt-dlp` on startup |

All four files must live in the same directory.

---

## Security Notes

- **`fetch-trailer.conf` contains your TMDB API key.** Keep this file private and do not share it.
- Your API key is sent as an HTTP `Authorization` header, not as a URL query parameter, so it will not appear in process listings or log output.
- `YTDLP_EXTRA_ARGS` is word-split at runtime to allow passing multiple flags. Do not store secrets in this value.

---

## Dependencies

Both Linuxserver.io Radarr and Sonarr images run Alpine Linux. Dependencies must be installed inside each container on startup using a custom init script.

**1. Create the required directories:**
```bash
mkdir -p /mnt/user/appdata/{radarr,sonarr}/{cont-init.d,scripts}
```

**2. Add `install_dependencies.sh` to each `cont-init.d` folder.**

**3. Update your Docker Compose volume mounts:**

Radarr:
```yaml
- /mnt/user/appdata/radarr/cont-init.d:/custom-cont-init.d
```
Sonarr:
```yaml
- /mnt/user/appdata/sonarr/cont-init.d:/custom-cont-init.d
```

`jq` and `yt-dlp` will be available in the container's PATH automatically on every container start.

---

## Configuration

1. Place the remaining fetch-trailer files into the scripts directory for each app:
```
/mnt/user/appdata/radarr/scripts/
/mnt/user/appdata/sonarr/scripts/
```

2. Add your TMDB API key in `fetch-trailer.conf` and make any other desired config changes.

3. Make the scripts executable:
```bash
chmod +x fetch-trailer.sh fetch-trailer-manual.sh
```

4. Set correct ownership on the scripts and conf per your system setup.:
```bash
chown PUID:PGID fetch-trailer.sh fetch-trailer-manual.sh fetch-trailer.conf
```

---

## Connecting to Radarr and Sonarr

In each app: **Settings → Connect → Custom Script → Add New**

| App | Script path | Events to enable |
|---|---|---|
| Radarr | `/config/scripts/fetch-trailer.sh` | On Import, On Upgrade (optional) |
| Sonarr | `/config/scripts/fetch-trailer.sh` | On Series Add |

Sonarr's **On Series Add** fires once when a show is added, not once per episode — this is intentional. This requires also enabling "Create Empty Series Folders" in Settings > Media Management. If used on import or upgrade, it would fire the trailer script on every _episode_ imported, which isn't wanted.

Use the **Test** button to verify the script is found and executable. A green checkmark confirms the connection is working.

---

## Dry Run

Before running in automation, test selection logic without downloading anything:

```bash
# From inside the Radarr or Sonarr container console
radarr_eventtype="Download" \
radarr_movie_title="Parasite" \
radarr_movie_year="2019" \
radarr_movie_tmdbid="496243" \
radarr_movie_path="/data/media/movies/Parasite (2019)" \
bash /config/scripts/fetch-trailer.sh --dry-run
```

The dry-run report shows all available trailers, which would be selected, which are excluded, and the output path — without writing any files or sending Discord notifications.

---

## Manual Usage

Run from inside the container console (Radarr or Sonarr):

```bash
# Auto — TMDB lookup, same selection logic as automated runs
bash /config/scripts/fetch-trailer-manual.sh \
  --path "/data/media/movies/Parasite (2019)"

# Manual — provide a specific YouTube ID, bypasses TMDB entirely
bash /config/scripts/fetch-trailer-manual.sh \
  --path "/data/media/movies/Parasite (2019)" \
  --ytid dUKFnBqlVSI

# TV show
bash /config/scripts/fetch-trailer-manual.sh \
  --path "/data/media/shows/The Bear (2022)" \
  --type tv

# Dry-run — show selection without downloading
bash /config/scripts/fetch-trailer-manual.sh \
  --path "/data/media/movies/Parasite (2019)" \
  --dry-run
```

The manual script always replaces existing trailers. The automated script skips media that already has a trailer (`SKIP_IF_EXISTS=true`).

If the folder name does not follow the `Title (Year)` format, pass `--title` and `--year` explicitly.

---

## Trailer Selection

The script fetches trailer candidates from TMDB and picks the best match using a priority system:

1. English trailers with "Subtitled" in the title (for non-English media)
2. Original-language trailers matching a `PREFERRED_TERMS` entry
3. Any trailer matching a `PREFERRED_TERMS` entry
4. First non-excluded trailer (fallback)
5. First available trailer regardless of exclusions (last resort)

`PREFERRED_TERMS` and `EXCLUDED_TERMS` in `fetch-trailer.conf` control selection globally. Per-app overrides (`RADARR_PREFERRED_TERMS`, `SONARR_EXCLUDED_TERMS`, etc.) are merged additively at runtime — per-app preferred terms are checked first, per-app excluded terms are appended to the global list.

---

## Troubleshooting

**Script not triggering** — Verify ownership is matches the same user in charge of the Arrs and that the file is executable.

**`yt-dlp` or `jq` not found** — Check that `install_dependencies.sh` is in `cont-init.d` and the volume mount is correct. Restart the container and check logs for failures.

**Wrong trailer selected** — Run with `--dry-run` to see the full candidate list and adjust `PREFERRED_TERMS`/`EXCLUDED_TERMS` in the conf.

**Age-restricted video fails** — Export a `cookies.txt` from your browser and set `YTDLP_COOKIES_FILE` in the conf. Or pick another trailer.

**Private video error** — The YouTube video linked on TMDB is private. Use `--ytid` with the manual script to provide a working public video ID.