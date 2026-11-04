# Trailer Park

Downloads local trailers for Radarr and Sonarr titles using TMDB + yt-dlp.

Current release: **v0.8.0** <!-- x-release-please-version -->

v0.8.0 replaces the web interface: one app with Overview, Trailers, Settings and Activity, live download logs, and a JSON API. Libraries are gone; every Radarr/Sonarr connection is simply listed under Movies or Shows. See the [changelog](CHANGELOG.md) for upgrade notes. v0.7.0 detects existing trailers under any name or folder, so Missing only lists titles with no trailer at all, and adds rename/keep/replace actions for them. v0.6.4 added an optional YouTube search fallback for titles TMDB has no working trailer for. v0.6.3 tries the next TMDB trailer when YouTube says a video is unavailable, falls back to season trailers for shows with no show-level trailer (first season by default, configurable), and ranks later-season trailers behind spoiler-free ones. v0.6.2 added a Radarr/Sonarr API watcher (no webhook needed), fixes webhooks reporting trailers as downloaded for newly added films, and finds original-language trailers for anime and other non-English titles. v0.6.1 added safe batch cancellation, automatic daily yt-dlp update checks, clearer configured-state handling and fixes trailer finalization for paths containing characters such as `[tmdbid-123456]`.

---

## Main features

- Multiple Radarr and Sonarr connections, merged into **Movies** and **Shows**
- Trailers page with search, filters (connection, folder, Missing, Available, Name mismatch, Multiple found) and paging
- **Grab**, **Replace**, **Manual** (YouTube link or ID), per-file **Rename / Keep only this / Delete**
- **Rename N** and **Grab N missing** for the current view
- Live download log with progress and Cancel; closing it never stops the download
- Overview with totals, coverage and recent Activity
- Settings for connections, naming, scoring, TMDB, downloads (resolution, mkv/mp4, concurrency), yt-dlp, sync schedule and notifications
- Automatic grabs from a watcher (no webhooks), plus **Sync now**
- Persistent Activity log with retention
- Discord notifications (per-event toggles; batches send one summary)
- In-app yt-dlp update with checksum verification and a persistent `/config` override
- Cross-process download limiting (1-4), safe batch cancellation
- Manual CLI
- JSON API under `/api` (see `SPEC.md`)

---

## Docker Compose

```yaml
services:
  trailer-park:
    build: .
    container_name: trailer-park

    networks:
      - media-network

    volumes:
      - /path/to/media:/data/media
      - ./config:/config

    # Optional: run as a specific host UID:GID.
    # 1000 = user ID, 1000 = group ID.
    # Check the correct values on your host with: id
    # user: "1000:1000"

    ports:
      - "8080:8080"

    restart: unless-stopped

networks:
  media-network:
    external: true
```

### User mapping

`user:` uses Docker's `UID:GID` format:

```text
user: "1000:1000"
       │    │
       │    └─ group ID (GID)
       └────── user ID (UID)
```

Do **not** assume `1000:1000` is correct for every server. The selected user must be able to:

- read/write the mapped media directories used for trailers
- read/write the `/config` volume

On Unraid, `99:100` (`nobody:users`) is a common mapping, but use the IDs that match your own share/permission setup.

---

## Start / upgrade

First install:

```bash
git clone https://github.com/geebru/trailer-park.git
cd trailer-park
docker compose up -d --build
```

Upgrade an existing install:

```bash
cd trailer-park
git pull
docker compose up -d --build
```

Open:

```text
http://SERVER-IP:8080
```

Upgrading from Trailarr Parrk: the project was renamed Trailer Park. Your `/config` volume and settings are unchanged. The example compose file now names the service and container `trailer-park`. If you use the example as it is, run `docker compose down` **before** `git pull`, so the old `trailarr-parrk` container does not keep port 8080, then `docker compose up -d --build`. A compose file of your own can keep its old names. If you run the manual script from Radarr or Sonarr, point the connection at `scripts/trailer-park.sh` (it was `trailarr-parrk.sh`). Log lines are now prefixed `[trailer-park]`.

Upgrading from v0.7.x: keep the same `/config` volume. Your connections and settings carry over. The old `libraries` list in `settings.json` is no longer used (it stays in the file, ignored). Old bookmarks such as `/library/movies` redirect to `/trailers`.

When upgrading from v0.5.x, keep the same `/config` volume. v0.6.0 reads the old Radarr/Sonarr settings and exposes them as default `Radarr`, `Sonarr`, `Movies` and `TV Shows` entries.

Before a major upgrade, backing up `config/settings.json` is still sensible.

---

## Settings

### TMDB

Add the TMDB Read Access Token and press **Test**.

A successful test saves the token. A failed test leaves the existing saved token untouched.

### Arr connections

Add any number of Radarr and Sonarr connections under **Settings → Connections** (**Test and save** checks the URL and key first). Radarr connections feed **Movies**, Sonarr connections feed **Shows**. Each title is shown once, under the connection it belongs to, and the Trailers page can filter by connection or media folder.

Default URLs for new standard installs are:

```text
Radarr: http://radarr:7878
Sonarr: http://sonarr:8989
```

**Automatic grabs** come from the watcher, which polls each connection's API (Settings → Automation, default every 5 minutes; Off turns automatic grabs off). **Sync now** runs one check immediately. Radarr grabs on import and upgrade; Sonarr grabs when a series is added, waiting for its folder if Sonarr hasn't created it yet. The first check only records a baseline — use Grab all missing for older titles.

Arr webhooks are no longer used. If you had a webhook pointing at `/hook` in Radarr or Sonarr, remove it under **Settings → Connect**; it now returns 404.

Existing trailers are kept on upgrades and later episode imports.

### Media

`MEDIA_ROOT` must exist inside the container and be readable. This catches path typos instead of silently showing an empty library.

### Downloads

Resolution (480p, 720p, 1080p, 4K), output container (mkv or mp4) and concurrent downloads (1-4) are under **Settings → Downloads**. Changes apply to new downloads. mp4 prefers H.264 video so the files play on more devices.

The concurrency limit applies across Web UI grabs, batches, the watcher and the CLI. Waitress still runs 4 HTTP worker threads so the UI stays responsive during a download.

---

## Trailers page

Movies and Shows tabs list every title. Filters: connection, media folder, and **All titles / Available / Missing / Name mismatch / Multiple found**. The filters and page are in the address, so you can bookmark a view (for example `/trailers?status=missing`).

### What counts as a trailer

A title has a trailer when its media folder contains **any** trailer file, whatever it's called:

- any video file (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`) inside a `trailers` or `trailer` subfolder (any capitalisation) or your configured trailer folder
- a video file in the media folder itself whose name ends in `trailer` — `-trailer.mkv`, `.trailer.mkv`, `Title trailer.mp4`, `trailer.mkv` (files over 2 GB are ignored there, so a main movie file is never mistaken for a trailer)

Changing the folder or filename settings never moves titles between Missing and Existing.

### Missing

Titles with no trailer file at all. Radarr movies appear once the movie file exists; Sonarr series once their series folder exists.

- **Grab**: let TMDB choose the best trailer
- **Manual**: use a specific YouTube link or ID
- **Grab N missing** (top right): grabs every missing title in the current tab and connection filter, one after another, after a confirmation. Progress and **Cancel batch** are in the sidebar.

### Available

Titles that have a trailer. Each is marked **Name mismatch** (a trailer exists under another name or folder) and/or **Multiple found** (several trailer files).

- **Replace**: download a new trailer. Old files are removed **only if the download succeeds**.
- **Manual**: replace with a specific YouTube link or ID
- **Files**: per-file **Rename** (to the current naming, keeps the extension, never overwrites), **Keep only this** (delete the others), **Delete**
- **Rename N** (top right): rename every flagged single-file title in the current tab and connection. A dry run shows what is ready or blocked first. Titles with several files are skipped.

Trailer Park stores metadata for trailers it downloads (TMDB video name, YouTube ID, score, timestamp, source). Renames keep that metadata. Trailers it didn't download show as **Found on disk**.

---

## Trailer scoring

Baseline preferred terms remain:

```text
official,trailer,teaser,theatrical
```

Trailer scoring:

```text
official   +10
trailer    +10
theatrical +10
teaser      +5
```

TMDB's actual `Trailer` / `Teaser` type and `official` flag are used for the baseline terms as well as the video name.

Typical result:

```text
Official Trailer = +20
Official Teaser  = +15
```

Excluded terms still reject a candidate completely.

---

## Activity

The **Activity** page stores recent actions in `/config/activity.jsonl`.

It can show:

- successful downloads
- no-match warnings
- failed yt-dlp downloads
- forced downloads
- deletes
- yt-dlp updates
- connection
- selected trailer name
- YouTube ID
- score
- excluded candidates
- download duration

Old entries are removed automatically after the retention period (Settings → Automation; 60, 90, 180 or 365 days, or forever).

---

## yt-dlp management

**Settings → Downloads** shows:

```text
Active version
Bundled Docker-image version
Latest version (after Check)
```

**Check for update** queries the official yt-dlp GitHub release.

**Update yt-dlp** downloads the official `yt-dlp` release file, verifies it against the release `SHA2-256SUMS`, then stores it at:

```text
/config/bin/yt-dlp
```

Trailer Park uses that persistent copy immediately and after container recreation. The yt-dlp version bundled in the Docker image remains the fallback.

Trailer Park automatically checks for a newer yt-dlp release once every 24 hours and records the last successful check in `/config/ytdlp-status.json`. It does **not** install updates automatically; use **Update yt-dlp** when you want to activate a new release.

A future full image rebuild can still update the bundled fallback version.

---

## Batches

**Grab N missing** on the Trailers page starts a batch for the current tab and connection filter. Only one batch runs at a time. Each title is a normal download, so you can open any running one from the sidebar to see its log. **Cancel batch** in the sidebar stops further titles from starting; downloads already running finish safely. When a batch ends, one summary (not one message per title) goes to Discord if notifications are on, and the batch is recorded in Activity.

---

## Manual CLI

The CLI still works as a separate short-lived process inside the running container:

```bash
docker exec trailer-park python /app/app.py \
  --yt-id dUKFnBqlVSI \
  --title "Parasite" \
  --year 2019 \
  --output "/data/media/movies/Parasite (2019)" \
  --dry-run
```

Or use TMDB:

```bash
docker exec trailer-park python /app/app.py \
  --tmdb-id 496243 \
  --type movie \
  --title "Parasite" \
  --year 2019 \
  --output "/data/media/movies/Parasite (2019)" \
  --dry-run
```

The CLI loads `/config/settings.json` independently of the running Flask process, but the v0.6.0 file-lock download limiter is shared across processes.

---

## Persistent files

The `/config` volume now contains runtime state such as:

```text
/config/settings.json
/config/activity.jsonl
/config/trailers.json
/config/bin/yt-dlp        # only after an in-app yt-dlp update
/config/download-slots/   # lock files used for concurrency control
```

Do not commit this directory to a public repository.

---

## Security

Trailer Park does not provide its own authentication.

Keep the UI on a trusted network or protect it with authentication before exposing it outside your LAN.

The config directory contains API keys and the Discord webhook URL and is ignored by the supplied `.gitignore`.
