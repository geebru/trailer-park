# Trailarr Parrk

Downloads local trailers for Radarr/Sonarr libraries using TMDB + yt-dlp.

Current release: **v0.6.2**

v0.6.2 adds a Radarr/Sonarr API watcher (no webhook needed), fixes webhooks reporting trailers as downloaded for newly added films, and finds original-language trailers for anime and other non-English titles. v0.6.1 added safe batch cancellation, automatic daily yt-dlp update checks, clearer configured-state handling and fixes trailer finalization for paths containing characters such as `[tmdbid-123456]`.

---

## Main features

- Multiple Radarr and Sonarr connections
- Custom libraries such as Movies, TV Shows, Anime Movies, Anime TV, Kids Movies, etc.
- Separate page for every library
- `Missing` and `Existing` views per library
- Per-library **Grab all missing**
- Global **Grab all missing across all libraries** under Settings
- Replace, Force or Delete an existing trailer
- Persistent trailer metadata for downloads made by v0.6.0+
- Persistent Activity / diagnostics page
- TMDB trailer scoring and exclusions
- Configurable 1–4 concurrent downloads
- Cross-process download limiting for Web UI, batch, webhook and CLI downloads
- Installed/bundled yt-dlp version display
- In-app yt-dlp update with checksum verification and persistent `/config` override
- Automatic yt-dlp update check every 24 hours; installation remains manual
- Safe cancellation of per-library and global batches
- Discord notifications
- Manual CLI

---

## Docker Compose

```yaml
services:
  trailarr-parrk:
    build: .
    container_name: trailarr-parrk

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

```bash
docker compose up -d --build
```

Open:

```text
http://SERVER-IP:8080
```

When upgrading from v0.5.x, keep the same `/config` volume. v0.6.0 reads the old Radarr/Sonarr settings and exposes them as default `Radarr`, `Sonarr`, `Movies` and `TV Shows` entries.

Before a major upgrade, backing up `config/settings.json` is still sensible.

---

## Settings

### TMDB

Add the TMDB Read Access Token and press **Test**.

A successful test saves the token. A failed test leaves the existing saved token untouched.

### Arr connections

Connections and libraries are separate concepts.

Example:

```text
Connections
├─ Radarr Main
├─ Radarr Anime
├─ Sonarr Main
└─ Sonarr Anime

Libraries
├─ Movies       → Radarr Main
├─ Anime Movies → Radarr Anime
├─ TV Shows     → Sonarr Main
└─ Anime TV     → Sonarr Anime
```

You can also create multiple libraries from one Arr instance by setting library root paths:

```text
Radarr Main
├─ Movies       → catch-all / blank root
└─ Anime Movies → /data/media/anime-movies
```

A specific root wins over the blank catch-all, so the same title is not shown in both library pages.

Default URLs for new standard installs are:

```text
Radarr: http://radarr:7878
Sonarr: http://sonarr:8989
```

For connection-specific webhook attribution, use:

```text
http://trailarr-parrk:8080/hook/CONNECTION-ID
```

The legacy generic webhook remains available:

```text
http://trailarr-parrk:8080/hook
```

**Automatic grabs** work two ways, and you can use either or both:

- **Watch Radarr/Sonarr** (Settings → Performance, default every 5 minutes): uses the API connection. Radarr grabs on import and upgrade; Sonarr grabs when a series is added, waiting for its folder if Sonarr hasn't created it yet. The first check only records a baseline — use Grab all missing for older titles.
- **Webhook** (instant): Settings shows each connection's webhook URL with a Copy button and when its last webhook arrived.

Webhook triggers:

- **Radarr:** On File Import (required), On File Upgrade (optional). Leave On Grab and On Movie Added off — they fire before the movie folder exists and Trailarr answers `deferred`.
- **Sonarr:** On Import and On Series Add. Series Add grabs right away if the series folder already exists (Sonarr's *Create empty series folders*); otherwise the first episode import grabs it.

Existing trailers are kept on upgrades and later episode imports.

### Media

`MEDIA_ROOT` must exist inside the container and be readable. This catches path typos instead of silently showing an empty library.

### Performance

Concurrent downloads can be set from **1 to 4**.

Default:

```text
1
```

The limit applies across:

- Web UI grabs
- batch grabs
- webhooks
- manual CLI processes

Waitress still runs with 4 HTTP worker threads so the UI can stay responsive while a download is running.

---

## Libraries

Each configured library gets its own page and two views:

```text
Library
├─ Missing
└─ Existing
```

### Missing

Shows only usable titles without the expected trailer file.

Radarr movies are only shown after the movie file exists. Sonarr series are shown once their mapped series folder exists.

Actions:

- **Grab** — let TMDB choose the best trailer
- **Force** — use a specific YouTube ID
- **Grab all missing** — only processes the current library
- Search and sort

### Existing

Shows titles that already have a local trailer.

Actions:

- **Replace** — run automatic selection again
- **Force** — replace with a specific YouTube ID
- **Delete** — remove the trailer so the title returns to Missing
- Search and sort

For trailers downloaded by v0.6.0+, Trailarr stores metadata such as:

- selected TMDB video name
- YouTube ID
- score
- timestamp
- automatic/manual source

Older existing trailers still appear, but display `Source information unknown` because Trailarr did not create metadata for them.

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
- library/source
- selected trailer name
- YouTube ID
- score
- excluded candidates
- download duration

Activity can be cleared from the UI.

---

## yt-dlp management

Settings shows:

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

Trailarr uses that persistent copy immediately and after container recreation. The yt-dlp version bundled in the Docker image remains the fallback.

Trailarr automatically checks for a newer yt-dlp release once every 24 hours and records the last successful check in `/config/ytdlp-status.json`. It does **not** install updates automatically; use **Update yt-dlp** when you want to activate a new release.

A future full image rebuild can still update the bundled fallback version.

---

## Global Grab All

Settings → **Global actions** contains:

```text
Grab all missing across all libraries
```

Trailarr first calculates the missing count per library and asks for confirmation before starting the batch.

The same single batch state is shown on Library / Activity / Settings pages while it runs.

### Cancel a batch

While a per-library or global batch is running, **Cancel batch** stops any additional queued trailers from starting. Downloads that are already active are allowed to finish safely. The cancelled batch is recorded in Activity.

---

## Manual CLI

The CLI still works as a separate short-lived process inside the running container:

```bash
docker exec trailarr-parrk python /app/app.py \
  --yt-id dUKFnBqlVSI \
  --title "Parasite" \
  --year 2019 \
  --output "/data/media/movies/Parasite (2019)" \
  --dry-run
```

Or use TMDB:

```bash
docker exec trailarr-parrk python /app/app.py \
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

Trailarr Parrk does not provide its own authentication.

Keep the UI on a trusted network or protect it with authentication before exposing it outside your LAN.

The config directory contains API keys/webhook credentials and is ignored by the supplied `.gitignore`.
