# Trailer Park — Changelog

## [0.10.0](https://github.com/geebru/trailer-park/compare/v0.9.0...v0.10.0) (2026-11-06)


### ✨ Features

* **activity:** log Sync now checks, including failures ([#41](https://github.com/geebru/trailer-park/issues/41)) ([e6d3537](https://github.com/geebru/trailer-park/commit/e6d3537b75302d6204b667b1fccbae52050bb558))


### 🐛 Bug fixes

* **engine:** keep secrets out of logs, Activity and error text ([#56](https://github.com/geebru/trailer-park/issues/56)) ([14d6ea3](https://github.com/geebru/trailer-park/commit/14d6ea3eed5a88ebee04c3b94b7ab36b6c698a43)), closes [#50](https://github.com/geebru/trailer-park/issues/50)
* **settings:** accept only Discord webhook URLs ([#55](https://github.com/geebru/trailer-park/issues/55)) ([1e49792](https://github.com/geebru/trailer-park/commit/1e49792ce554663b5d07606a16bc1216648cf903))


### 📝 Documentation

* add an AI disclaimer to the README ([#43](https://github.com/geebru/trailer-park/issues/43)) ([ce7d952](https://github.com/geebru/trailer-park/commit/ce7d9529a1091b2093747f8ebe105d9c76ef9aea))
* add the MIT license and third-party notices ([#40](https://github.com/geebru/trailer-park/issues/40)) ([d4b3d6f](https://github.com/geebru/trailer-park/commit/d4b3d6f98181758cda88133c6b8c0adf9717d952))

## [0.9.0](https://github.com/geebru/trailer-park/compare/v0.8.0...v0.9.0) (2026-11-04)


### ⚠ BREAKING CHANGES

* the example compose service and container are now named trailer-park (run docker compose down before pulling, so the old trailarr-parrk container does not keep port 8080). scripts/trailarr-parrk.sh is now scripts/trailer-park.sh, so repoint any Radarr or Sonarr custom script connection. Log lines now start with [trailer-park].

### ✨ Features

* publish Docker images when a release is created ([#30](https://github.com/geebru/trailer-park/issues/30)) ([d6c07d4](https://github.com/geebru/trailer-park/commit/d6c07d4577dd7cc0eeef3f164f0546c2b9d85c76))


### 📝 Documentation

* **agent:** say where breaking-change notes go and how to pick a type ([#29](https://github.com/geebru/trailer-park/issues/29)) ([e9dc14c](https://github.com/geebru/trailer-park/commit/e9dc14c2b078a1bee854834318ec83198bca88ab)), closes [#28](https://github.com/geebru/trailer-park/issues/28)
* rewrite the README for the new interface and the image install ([#38](https://github.com/geebru/trailer-park/issues/38)) ([6de6e23](https://github.com/geebru/trailer-park/commit/6de6e2351f1a9c880239a5b901d573cb9b4d9f2a))


### Other changes

* **agent:** move the issue and PR workflow from Gitea to GitHub ([#23](https://github.com/geebru/trailer-park/issues/23)) ([c1e8f75](https://github.com/geebru/trailer-park/commit/c1e8f751e4bd9dfdeece87a90bb52430f534d87b))
* rename Trailarr Parrk to Trailer Park ([#26](https://github.com/geebru/trailer-park/issues/26)) ([0e2cd07](https://github.com/geebru/trailer-park/commit/0e2cd07cd654ab4e7d3e1bacd40b263484264a71))

## v0.8.0 - New interface

### Changed
- **New web interface.** Overview, Trailers, Settings and Activity, built as a single page that talks to a JSON API (`/api`). No page reloads, live download logs with progress and Cancel, and a sidebar showing connection health, the next sync and running jobs. Everything is served from the app itself: no build step, no CDN, fonts included.
- **Libraries are gone.** Radarr connections show under Movies and Sonarr under Shows. Existing `settings.json` files keep working; the stored `libraries` list is ignored.
- Settings are saved from one page with Save/Discard. Secrets (TMDB key, Discord webhook) are never sent back to the browser.
- Old addresses redirect: `/library/<id>` and `/app/...` go to the new pages.

### Added
- Output container **mkv or mp4**, resolution **480p / 720p / 1080p / 4K**, Discord toggles for success and failure, activity retention (60 / 90 / 180 / 365 days or forever), **Sync now**, and a media-folder filter on Trailers.
- Per-file **Rename**, **Keep only this** and **Delete**; **Rename N** with a dry run; **Grab N missing** per tab and connection.
- Batches send a single Discord summary.

### Removed
- The old form-and-redirect pages, their templates and stylesheets, and the old `/api/batch`, `/ui/...` and `/api/global-missing-summary` routes.
- **Arr webhooks.** The `/hook` and `/hook/<connection id>` routes, the webhook URL and "last webhook" display in Settings, and `webhook-status.json` are gone. The API watcher is now the only automatic trigger. **If you added a webhook in Radarr or Sonarr, remove it** (Settings → Connect); the Arr will otherwise log 404 errors. Set the sync interval to Off to turn automatic grabs off.
- Discord notifications are unchanged.

### Fixed
- The watcher's "no file IDs" error no longer tells you to use the webhook; it says what to check.

## v0.7.0 — Existing-trailer detection

### Changed
- **Missing now means no trailer at all.** Any trailer file counts, whatever it's named: videos in a `trailers`/`trailer` subfolder (any case) or the configured trailer folder, and videos in the media folder whose name ends in `trailer` (`-trailer`, `.trailer`, ` trailer`, `trailer`). Root-level files over 2 GB are ignored. Previously only the exact configured folder + filename counted, so changing the naming settings swapped titles between Missing and Existing.
- Automatic grabs (watcher, webhook, Grab all missing) skip any title with a trailer under any name.
- Delete removes all detected trailer files for the title.
- Trailers not downloaded by Trailarr show as "Found on disk" instead of "Source information unknown".
- Titles with characters that can't be in filenames are cleaned the Radarr/Sonarr way instead of with underscores: `Avengers: Infinity War` → `Avengers - Infinity War`, `Face/Off` → `Face-Off`, and `* ? " < > |` are dropped. Existing underscore-named trailers show as *Name differs from settings*; **Rename N to current naming** fixes them.

### Added
- Existing tab marks each title ✓ Matches naming, ⚠ Name differs from settings, or ⚠ N trailer files, with a **Needs attention** filter and a count on the tab.
- **Rename to naming** per title and **Rename N to current naming** per library: move trailers to the current folder/filename settings without re-downloading. Keeps the file's extension and Trailarr's metadata, never overwrites, and removes the old trailer folder if it ends up empty.
- **Keep only this** for folders with several trailer files.
- **Replace** and **Force** remove old trailer files only after the new download succeeds. A failed replace keeps everything.
- File actions only accept files Trailarr itself detected as trailers, so they can never touch a main media file.

## v0.6.4 — YouTube search fallback

### Added
- **YouTube search fallback** (Settings → Matching, off by default; env `YOUTUBE_SEARCH=on`). When TMDB has no usable trailer, or every TMDB trailer is unavailable, Trailarr searches YouTube for `<title> <year> trailer` (top 15 results, metadata only).
- A search result is only used if it contains every significant word of the title, contains "trailer", "teaser" or "promo", is 20 s – 5 min long, matches no excluded term, and none of the built-in junk terms (reaction, review, recap, explained, fan made, episode, scene, clip, compilation and similar).
- Results naming a different year (more than one year off) are rejected, so same-name remakes and reboots aren't picked. Numbers that are part of the title itself ("Blade Runner 2049", "1917") are ignored.
- Ranking: the right year in the video title first, then spoiler-free, preferred-terms score, official/verified channel, view count.
- Grabs found this way are marked "found via YouTube search" with the query and channel in Activity and Discord, so they can be spot-checked.

## v0.6.3 — Fewer missed trailers

### Fixed
- When the best TMDB trailer is unavailable on YouTube (removed, private, region-blocked, age-restricted, members-only), Trailarr now tries the next candidates, up to 5. Previously one dead link meant no trailer even when TMDB listed others.
- Errors that would hit every candidate (YouTube bot check, network, timeouts) stop immediately instead of retrying.
- When every candidate is unavailable, Activity and Discord say so and list what was tried, instead of the raw yt-dlp error.
- TV shows with no show-level trailer on TMDB now fall back to season trailers. Long-running shows (Grey's Anatomy, Law & Order: SVU and similar) keep their trailers on seasons. New setting **TV season fallback** (Matching): `First season` (default, spoiler-free: season 1, then 2), `Latest season` (latest, previous, then season 1) or `Off` (report no trailer, as the original script did). Env: `SEASON_FALLBACK`.
- Default preferred terms now include `season 1`, `season 01` and `announcement` (from the original script), so first-season and announcement trailers get +10. Existing installs keep their saved terms; add these in Settings → Matching.
- Preferred terms ending in a number no longer match a longer number: `season 1` matches "Season 1" but not "Season 10" or "Season 12".
- Spoiler guard: show-level trailers whose title mentions a later season ("Season 8 Official Trailer", "S19", "Final Season") are ranked behind every spoiler-free trailer. They are still used when nothing else exists.
- The `No matching trailers` message lists which seasons were checked.
- Sonarr series now use Sonarr's own TMDB ID (Sonarr v4 API and webhooks), as the original script did. TMDB's TVDB lookup is only a fallback, followed by an IMDb lookup, so shows TMDB can't match by TVDB ID no longer end in `no_tmdb_match`.

## v0.6.2 — Watcher and webhook fixes

### Added
- **Watch Radarr/Sonarr** through the API connection, no webhook needed. Radarr: grabs on import and upgrade (detected by the movie's file ID appearing or changing). Sonarr: grabs when a series is added; if its folder doesn't exist yet it waits (up to 30 days) and grabs once it appears.
- New setting `Watch Radarr/Sonarr` (Performance), minutes between checks. Default 5, `0` turns it off. Env: `WATCH_INTERVAL_MINUTES`.
- The first check of a connection records a baseline and grabs nothing. Use Grab all missing for older titles.
- Each connection in Settings shows watcher status: last check, last triggered title and outcome, series waiting for a folder, or the last error.
- Webhooks and the watcher can run together; the second one finds the trailer and skips.
- Settings shows each Arr connection's webhook URL with a Copy button.
- Each connection shows when its last webhook arrived, the event, the title and the outcome. If no webhook has ever arrived and watching is off, it warns that automatic grabs aren't set up.
- Every incoming webhook is logged to the container log (`Webhook received: connection=… event=… item=… -> status`).
- Webhook outcomes that used to return silently (`rejected`, `no_tmdb_match`, unknown connection ID, unrecognized payload) are now recorded in Activity.

### Fixed
- Fixed Radarr webhooks reporting `Trailer downloaded` for newly added films without a usable trailer. `On Movie Added` and `On Grab` fire before the movie folder exists; Trailarr created the folder itself and wrote the trailer into it before Radarr had imported anything.
- Webhooks now only act on `Download` (Radarr/Sonarr `On File Import` / `On File Upgrade`) and Sonarr `SeriesAdd`. `Grab` and `MovieAdded` return `deferred`; all other events (`Rename`, deletes, health, etc.) return `ignored`.
- Sonarr `On Series Add` grabs immediately when the series folder exists. If it doesn't, the first episode import picks it up (requires `On Import`).
- Webhooks skipped because the media folder isn't visible inside Trailarr are now logged in Activity instead of disappearing silently.
- Successful grabs now record the full saved path in Activity.
- Radarr webhooks now require the movie folder to exist, matching Sonarr webhooks and manual grabs.
- Trailarr never creates a media folder; grabs into a missing folder return `folder_missing`.
- Webhook-triggered grabs skip titles that already have a trailer, so upgrades don't re-download it.
- Hand-crafted webhook payloads without `eventType` keep the previous behaviour.
- Fixed missing trailers for anime and other non-English titles. TMDB `/videos` only returns English videos unless asked otherwise; Trailarr now requests English, the title's original language and untagged videos. English wins ties.
- `No matching trailers` notifications now say whether TMDB has no trailers at all (use Force with a YouTube ID) or whether candidates were filtered out by the current rules.

## v0.6.1 — Batch control and diagnostics

### Added
- Cancel the currently running per-library or global batch from the Web UI.
- Cancelling stops new queued downloads from starting while active downloads finish safely.
- Cancelled batches are marked as cancelled and recorded in Activity.
- Automatic yt-dlp update check every 24 hours.
- yt-dlp Settings status now shows the installed version, latest known version and last successful check time.
- Manual `Check for update` and user-triggered `Update yt-dlp` remain available.

### Fixed
- Fixed downloads being falsely reported as failed when media paths contain glob-special characters such as square brackets, for example `[tmdbid-541671]`.
- Fixed temporary `trailarr-new` files not being found or cleaned up when paths contain glob-special characters.
- Clearing a saved TMDB token, Arr API key or Discord webhook and saving now shows the integration as `Not configured`.

## v0.6.0 — Libraries, Activity and diagnostics

### Added
- Configurable libraries with custom names.
- Multiple Radarr and Sonarr connections.
- Multiple libraries from the same Arr instance using optional root-path filtering.
- Specific library roots take priority over a blank catch-all library to avoid duplicate items.
- Separate page for every configured library.
- `Missing` and `Existing` tabs for every library.
- Existing-trailer inspection and management.
- Replace existing trailer using automatic TMDB selection.
- Force replacement using a YouTube ID.
- Delete an existing trailer.
- Per-library search and sorting.
- Per-library `Grab all missing`; it only processes the current library.
- Global `Grab all missing across all libraries` under Settings with a per-library confirmation summary.
- Persistent Activity / diagnostics page.
- Persistent metadata for trailers downloaded by v0.6.0+.
- Batch progress with active and queued items.
- Configurable concurrent downloads from 1–4, default 1.
- Cross-process file-lock limiter shared by Web UI, batch, webhook and CLI downloads.
- yt-dlp active and bundled version display.
- yt-dlp latest-release check.
- Persistent in-app yt-dlp updater under `/config/bin/yt-dlp`.
- SHA-256 verification against yt-dlp `SHA2-256SUMS` before activating an update.
- Connection-specific webhook route: `/hook/<connection-id>`.
- Automatic migration of v0.5.x single Radarr/Sonarr settings into default connections/libraries.

### Changed
- Main UI navigation is now library-based instead of one combined Missing page.
- Trailer downloads use safer atomic replacement: the existing trailer remains until the new download succeeds.
- Generic `/hook` is retained for backward compatibility.
- Waitress remains at 4 HTTP threads while download concurrency is controlled separately.


## v0.5.3 — Docker user mapping documentation
- Documented optional `UID:GID` Docker user mapping.
- Added `user: "1000:1000"` example and permission notes.

## v0.5.2 — Matching and UI refinement
- Renamed settings status from `Currently set` to `Configured`.
- Reduced `teaser` scoring from +10 to +5.
- Full trailers receive higher priority than teasers.
- Scoring: `official` +10, `trailer` +10, `theatrical` +10, `teaser` +5.

## v0.5.1 — Settings UX and validation
- Added configured-state indicators.
- Default Radarr URL set to `http://radarr:7878`.
- Default Sonarr URL set to `http://sonarr:8989`.
- Successful connection tests save only the tested service.
- Failed tests keep the last known-good settings.
- Added unsaved-settings warning before leaving Settings.
- Saving validates that `MEDIA_ROOT` exists and is readable.
- Added application version display.

## v0.5.0 — Persistent Settings UI
- Added browser-based persistent configuration.
- Added `/config/settings.json` storage.
- Added connection tests for TMDB, Radarr, Sonarr and Discord.
- Radarr requires an existing movie file and Sonarr requires an existing series folder before appearing as missing.

## v0.4.0 — Web UI
- Added the Missing page.
- Added Radarr and Sonarr API integration.
- Added Grab, Force and Grab All Missing.
- Added batch state and 4-thread Waitress server while serializing yt-dlp downloads.

## v0.3.0 — Matching and reliability
- Added Trailer + Teaser support.
- Fixed Discord User-Agent handling.
- Improved matching/configuration behavior.

## v0.2.0 — Native Python CLI
- Added `--yt-id`, `--tmdb-id`, `--type`, `--title`, `--year`, `--output` and `--dry-run`.
- Removed the separate shell CLI requirement.

## v0.1.0 — Standalone sidecar
- Initial standalone Docker sidecar for Radarr/Sonarr webhooks, TMDB lookup, yt-dlp downloads and Discord notifications.
