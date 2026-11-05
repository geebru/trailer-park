# Trailer Park

Downloads local trailers for your Radarr and Sonarr titles. It looks each title up on TMDB, picks the best trailer, downloads it from YouTube with yt-dlp, and saves it next to the media in a layout that Plex and Jellyfin pick up. Everything is managed from one web interface.

Current release: **v0.9.0** <!-- x-release-please-version -->

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE)

## What it does

- Connects to any number of Radarr and Sonarr instances. Each title appears once, under **Movies** or **Shows**.
- Shows which titles have no trailer, whatever a trailer file is called and wherever it sits.
- Grabs a trailer for one title, for every missing title at once, or automatically when new titles arrive.
- Replaces, renames, keeps or deletes trailer files. It only ever touches files it recognizes as trailers, never the media itself.
- Live download logs, a persistent activity log, and optional Discord notifications.
- Updates yt-dlp from inside the app.

---

## Install

You need Docker with Compose, a free [TMDB](https://www.themoviedb.org/) account, and the API keys of your Radarr and Sonarr. Save this as `docker-compose.yml` and set your media path:

```yaml
services:
  trailer-park:
    image: ghcr.io/geebru/trailer-park:latest
    container_name: trailer-park
    volumes:
      - /path/to/media:/data/media
      - ./config:/config
    ports:
      - "8080:8080"
```

Then start it and open `http://SERVER-IP:8080`:

```bash
docker compose up -d
```

The image is published for `linux/amd64` and `linux/arm64`. Tags are `X.Y.Z`, `X.Y` and `latest` (from 1.0 also `X`). `latest` is the newest release; pin a version tag such as `0.9.0` if you want to choose when to upgrade.

**Media paths must match.** Trailer Park uses the folder paths your Radarr and Sonarr report, so your media has to be visible inside this container at the same path the Arrs see. If Radarr says `/data/media/movies/Dune (2021)`, mount the same media at `/data/media`. The **Media folder** setting is the top-level folder those paths must sit under (default `/data/media`). Path mapping between the Arrs and Trailer Park is not supported yet.

**User mapping.** `user:` takes `UID:GID`, for example `"1000:1000"`. Do not assume that is right for your server. The user must be able to read and write both the media folders used for trailers and the `/config` volume. On Unraid, `99:100` (`nobody:users`) is common, but use the IDs that match your share permissions.

### Upgrade

```bash
docker compose pull
docker compose up -d
```

Keep the same `/config` volume across upgrades. Before a major upgrade, back up `config/settings.json`.

To build from source instead, clone the repository, replace `image:` with `build: .` in your compose file, and use `docker compose up -d --build` (after `git pull` to upgrade).

### Upgrading from an older version

- **From Trailarr Parrk** (the project's former name): your `/config` volume and settings are unchanged. If you use the example compose file, rename the service and container to `trailer-park` and use the image above. Run `docker compose down` **before** you change the file, so the old `trailarr-parrk` container does not keep port 8080, then `docker compose up -d`. A compose file of your own can keep its old names. If you run the manual script from Radarr or Sonarr, point the connection at `scripts/trailer-park.sh` (it was `trailarr-parrk.sh`). Log lines are now prefixed `[trailer-park]`.
- **From v0.7.x:** keep the same `/config` volume. Connections and settings carry over. The old `libraries` list in `settings.json` is ignored, and old bookmarks such as `/library/movies` redirect to `/trailers`. Arr webhooks are gone: if you added one in Radarr or Sonarr, remove it under **Settings → Connect**, or the Arr will log 404 errors.

---

## First run

1. **Settings → TMDB:** paste your TMDB **API Read Access Token** (the long one, not the short v3 key), then press **Test key**. A successful test saves it.
2. **Settings → Connections:** press **Add connection**, choose Radarr or Sonarr, and enter a name, the base URL (for example `http://radarr:7878` or `http://sonarr:8989`) and the API key. **Test and save** checks both first.
3. **Settings → Naming:** make sure **Media folder** is the folder your libraries sit under, and check the **Output preview**.
4. Open **Trailers**, find a title in the Missing view and press **Grab**. Or press **Grab N missing** to do them all.
5. **Settings → Automation:** the default **Sync interval** is 5 minutes, so new imports are grabbed automatically from then on.

---

## Using the app

### Overview

Total titles, how many have no trailer (with a **Review** link to the Missing view), coverage as a percentage, and your most recent activity. The sidebar on every page shows each service's connection state, the next sync, and any running downloads or batch.

### Trailers

**Movies** and **Shows** tabs list every title. Search by name, and filter by connection, media folder, and **All titles / Available / Missing / Name mismatch / Multiple found**. The filters and page live in the address, so you can bookmark a view such as `/trailers?status=missing`.

**What counts as a trailer.** A title has a trailer when its media folder contains **any** trailer file, whatever it is called:

- any video file (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`) inside a `trailers` or `trailer` subfolder (any capitalization) or your configured trailer folder
- a video file in the media folder itself whose name ends in `trailer`, such as `-trailer.mkv`, `.trailer.mkv`, `Title trailer.mp4` or `trailer.mkv` (files over 2 GB are ignored there, so a main movie is never mistaken for a trailer)

Changing the folder or file name settings never moves a title between Missing and Available.

**Missing** lists titles with no trailer file at all. Radarr movies appear once the movie file exists, Sonarr series once their series folder exists.

- **Grab** lets TMDB choose the best trailer. **Manual** uses a YouTube link or ID you give it.
- **Grab N missing** (top right) grabs every missing title in the current tab and connection filter, one after another, after a confirmation. Progress and **Cancel batch** are in the sidebar.

**Available** lists titles that have a trailer, marked **Name mismatch** (the file does not match your naming template) and/or **Multiple found** (several trailer files; allowed, not an error).

- **Replace** downloads a new trailer. The old files are removed only if the new download succeeds. **Manual** replaces with a specific YouTube link or ID.
- **Files** opens per-file **Rename** (to the current naming, keeps the extension, never overwrites), **Keep only this** (deletes the others) and **Delete**.
- **Rename N** (top right) renames every flagged single-file title in the current tab and connection. A dry run shows what is ready or blocked first, and titles with several files are skipped.

Trailer Park stores metadata for trailers it downloads (TMDB video name, YouTube ID, score, time, source). Renames keep that metadata. Trailers it did not download show as **Found on disk**.

A download opens a live log with progress. **Run in background** closes it without stopping anything; **Cancel** stops the download and removes partial files.

**Batches.** Only one batch runs at a time. Each title in it is a normal download, so you can open any running one from the sidebar. **Cancel batch** stops further titles from starting; downloads already running finish safely. When a batch ends, one summary goes to Discord (if enabled) and the batch is recorded in Activity.

### Activity

A paged log of what happened: trailers downloaded (including manual ones), no suitable match found, failed downloads, renames, removed files, batches finished or cancelled, yt-dlp updates and maintenance. Entries older than the retention period are removed automatically.

---

## Settings

Settings are saved with **Save changes** (or **Discard**). Connections are saved as you add them.

| Section | What it controls |
|---|---|
| **Connections** | Radarr and Sonarr instances: name, type, base URL, API key. Radarr connections feed Movies, Sonarr connections feed Shows. |
| **Naming** | **Media folder** (default `/data/media`). **Trailer folder** (default `trailers`; leave blank to save beside the media file). **File name template** (default `{title} ({year}).trailer`; variables `{title}` and `{year}`). A live **Output preview**. |
| **Scoring** | **Positive keywords** and **Negative keywords** (see below), and the **YouTube search fallback** (off by default). |
| **TMDB** | Your TMDB Read Access Token, with **Test key**. |
| **Downloads** | yt-dlp version and updates. **Resolution** (maximum: 480p, 720p, **1080p**, 4K), **Output container** (**mkv** or mp4; mp4 prefers H.264 so files play on more devices) and **Concurrent downloads** (**1** to 4). Changes only affect new downloads. |
| **Automation** | **Sync interval** (Off, **5**, 10, 15, 30 minutes, 1, 6 or 24 hours), **Sync now**, and **Activity retention** (60, **90** or 180 days, 1 year, or forever). |
| **Notifications** | An optional Discord webhook URL with **Send test** (a successful test saves it), and toggles for **Trailer downloaded** and **Grab failed** (both on by default). Batches and Sync now send one summary instead of one message per title. |

**Automatic grabs** come from a watcher that polls each connection's API at the sync interval (Off turns automatic grabs off). Radarr grabs on import and upgrade. Sonarr grabs when a series is added, and if its folder does not exist yet it waits (up to 30 days). The first check of a connection only records a baseline, so use **Grab N missing** for titles that were already there. **Sync now** runs a check immediately. Existing trailers are kept on upgrades and on later episode imports.

The download limit applies across the web interface, batches, the watcher and the command line.

---

## How a trailer is chosen

1. Trailer Park asks TMDB for the title's videos (English, the title's original language, and untagged ones) and keeps YouTube trailers and teasers.
2. A video whose name contains a **negative keyword** is rejected outright. Defaults: `fan made, fan-made, reaction, parody, review, recut, behind the scenes, featurette`.
3. The rest are scored with the **positive keywords**. Defaults: `official, trailer, teaser, theatrical, season 1, season 01, announcement`.

   | Keyword | Matches | Points |
   |---|---|---|
   | `official` | TMDB's official flag, or the word in the video name | +10 |
   | `trailer` | TMDB's type is Trailer (the video name is not used) | +10 |
   | `teaser` | TMDB's type is Teaser | +5 |
   | any other keyword | the video name contains it, ignoring case (a keyword ending in a digit does not match a longer number, so `season 1` does not match `season 10`) | +10 |

   An official trailer therefore scores 20 and an official teaser 15. A video must score above 0 to be considered.
4. Candidates are ordered spoiler-free first (for shows, a title naming a later season or a "final season" sorts behind the rest, but stays usable if nothing else exists), then by score, then full trailers over teasers, then official, then English.
5. The best candidate is downloaded. If YouTube says it is unavailable (removed, private, region-blocked, age-restricted, members-only), the next candidate is tried, up to five.

**Shows with no show-level trailer** fall back to season trailers. `first` (the default) tries season 1, then season 2. `latest` tries the latest season, the one before it, then season 1. `off` tries none. This has no control in the interface yet: to change it, set `"season_fallback"` in `/config/settings.json` and restart the container.

**YouTube search fallback** (Settings → Scoring, off by default). When TMDB has no usable trailer, or every TMDB trailer is unavailable, Trailer Park searches YouTube for `<title> <year> trailer` (top 15 results, metadata only) and scores the results with the same keywords. A title containing the right year ranks first, which separates an original from a remake with the same name.

Downloads go to a temporary file and replace an existing trailer only after they succeed.

---

## yt-dlp

**Settings → Downloads** shows the active yt-dlp version and whether a newer one is available. Trailer Park checks the official yt-dlp releases about once a day, but never installs automatically. **Update** downloads the official release file, verifies it against the release `SHA2-256SUMS`, and stores it at `/config/bin/yt-dlp`. That copy is used immediately and after the container is recreated. The version bundled in the image stays as the fallback.

---

## Command line and script

The CLI runs as a separate short-lived process inside the running container. It reads `/config/settings.json` on its own, and shares the download limit with the app:

```bash
docker exec trailer-park python /app/app.py \
  --yt-id dUKFnBqlVSI \
  --title "Parasite" \
  --year 2019 \
  --output "/data/media/movies/Parasite (2019)" \
  --dry-run
```

Use `--tmdb-id 496243 --type movie` (or `--type tv`) instead of `--yt-id` to let TMDB choose. Drop `--dry-run` to download. `--output` defaults to the media folder.

`scripts/trailer-park.sh` is a standalone alternative that runs inside the Radarr or Sonarr container as a custom script (Settings → Connect → Custom Script; Radarr events On Import and On Upgrade, Sonarr event On Series Add). It has its own settings at the top of the file and does not use the web interface.

---

## API

The interface is a client of a JSON API under `/api`, with no authentication. `GET /health` returns the status, version and yt-dlp version.

- Requests that change something need `Content-Type: application/json` (otherwise 415). Errors look like `{"error": {"code": "...", "message": "..."}}`.
- Long actions (grab, replace, batches) return 202 with a job, which you poll with `GET /api/jobs/<id>?after=<seq>`. Only one job can be active per title (409 `job_active`).
- Titles are addressed as `/api/items/<connection_id>/<item_id>`.
- Secrets (the TMDB token, the Discord webhook) are never returned, only whether they are configured.

| Area | Endpoints |
|---|---|
| Titles | `GET /api/items`, `GET /api/items/<connection>/<id>`, `POST /api/library/refresh` |
| Grab, replace, manual | `POST /api/items/<connection>/<id>/grab` (send `{"replace": true}` to replace), `POST .../force` (a specific YouTube link or ID) |
| Files | `POST /api/items/<connection>/<id>/files/rename`, `.../keep`, `.../delete`, `POST /api/items/rename-all` |
| Jobs and batches | `GET /api/jobs`, `GET /api/jobs/<id>`, `POST /api/jobs/<id>/cancel`, `POST /api/batches`, `GET /api/batches/current`, `POST /api/batches/current/cancel` |
| Sync | `POST /api/watcher/run` |
| Overview and activity | `GET /api/overview`, `GET /api/activity`, `POST /api/activity/clear` |
| Settings | `GET` and `PUT /api/settings`, `POST /api/settings/test/<service>`, `POST /api/settings/naming-preview`, `POST /api/connections/test` |
| yt-dlp | `GET /api/yt-dlp`, `POST /api/yt-dlp/check`, `POST /api/yt-dlp/update` |

---

## Files and environment

The `/config` volume holds the app's state. Do not commit it to a public repository.

| File | What it holds |
|---|---|
| `settings.json` | Settings, connections, and secrets (readable only by its owner) |
| `activity.jsonl` | The Activity log |
| `trailers.json` | Metadata for trailers Trailer Park downloaded |
| `watch-state.json` | What the watcher has already seen |
| `ytdlp-status.json` | The last yt-dlp update check |
| `bin/yt-dlp` | The updated yt-dlp copy, only after an in-app update |
| `download-slots/` | Lock files for the concurrent download limit |

Every setting also has an environment variable that gives it its initial value: the setting's name in capitals, such as `TMDB_API_KEY`, `MEDIA_ROOT`, `VIDEO_QUALITY`, `WATCH_INTERVAL_MINUTES`, `SEASON_FALLBACK` or `YOUTUBE_SEARCH`. Once settings have been saved they live in `settings.json` and that file wins, so use the interface after the first save.

---

## Security

Trailer Park has no authentication of its own. Keep it on a trusted network, or put it behind something that authenticates before you expose it beyond your LAN. The config directory contains your API keys and the Discord webhook URL.

---

## License

Trailer Park is released under the [MIT License](LICENSE). Third-party material keeps its own license:

- Font Awesome Free icons (`static/ui/js/icons.js`): CC BY 4.0.
- DM Sans and IBM Plex Mono (`static/ui/fonts/`): SIL Open Font License 1.1, with the license files alongside.
- axe-core (`dev/axe/`): MPL-2.0. It is a development tool and is not part of the image.
- The Docker image also contains ffmpeg, deno, yt-dlp, Flask, Waitress and Alpine Linux packages, each under its own license.
