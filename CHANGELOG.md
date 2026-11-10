# Trailer Park — Changelog

## [0.12.0](https://github.com/geebru/trailer-park/compare/v0.11.0...v0.12.0) (2026-11-10)


### ✨ Features

* **shell:** add footer with a link to GitHub ([#93](https://github.com/geebru/trailer-park/issues/93)) ([0779867](https://github.com/geebru/trailer-park/commit/0779867e1fdefc67dbbf80c19aa0d28ebe03fde0))


### 🐛 Bug fixes

* **engine:** refresh the cached title after a watcher download ([#92](https://github.com/geebru/trailer-park/issues/92)) ([f157263](https://github.com/geebru/trailer-park/commit/f15726381287f0abc1908d68b8a883e29dc3cc83)), closes [#90](https://github.com/geebru/trailer-park/issues/90)


### 📝 Documentation

* **readme:** say user: must match the owner of the media ([#79](https://github.com/geebru/trailer-park/issues/79)) ([0f1f76e](https://github.com/geebru/trailer-park/commit/0f1f76e4c87565cfc62fece7c74e687f2b65674b))

## [0.11.0](https://github.com/geebru/trailer-park/compare/v0.10.0...v0.11.0) (2026-11-08)


### ✨ Features

* **engine:** add a setting to skip unmonitored titles ([#67](https://github.com/geebru/trailer-park/issues/67)) ([dc86d14](https://github.com/geebru/trailer-park/commit/dc86d143bc71e385c9b218f71a7b1e6625b1d1ad))
* **engine:** log the language of the chosen trailer ([#72](https://github.com/geebru/trailer-park/issues/72)) ([e43f72d](https://github.com/geebru/trailer-park/commit/e43f72d87dae18b1794049820eb3f594ad1f777e)), closes [#7](https://github.com/geebru/trailer-park/issues/7)
* **settings:** expose and explain the TV season fallback setting ([#66](https://github.com/geebru/trailer-park/issues/66)) ([925adc6](https://github.com/geebru/trailer-park/commit/925adc6e263174ee1df47be1bf760d95614d0e3b))
* **settings:** use /config/cookies.txt for restricted videos ([#68](https://github.com/geebru/trailer-park/issues/68)) ([b65c09c](https://github.com/geebru/trailer-park/commit/b65c09c61dc36242ecf880e91fc55f521af7e962)), closes [#16](https://github.com/geebru/trailer-park/issues/16)
* **trailers:** add ability to ignore missing trailers ([#73](https://github.com/geebru/trailer-park/issues/73)) ([d1e5d07](https://github.com/geebru/trailer-park/commit/d1e5d07e6d597032f31c69cafacfd55ce847cbae))
* **trailers:** grab hand-picked titles as one batch ([#74](https://github.com/geebru/trailer-park/issues/74)) ([2d08713](https://github.com/geebru/trailer-park/commit/2d08713794af96d23559d50e20d7e350da737128))


### 📝 Documentation

* shorten the README, move detail to docs/ and add screenshots ([36fdb84](https://github.com/geebru/trailer-park/commit/36fdb842d124d717e445b15b57e7af685e4b6c56)), closes [#11](https://github.com/geebru/trailer-park/issues/11)
* shorten the README, move detail to docs/, add screenshots ([#76](https://github.com/geebru/trailer-park/issues/76)) ([36fdb84](https://github.com/geebru/trailer-park/commit/36fdb842d124d717e445b15b57e7af685e4b6c56))


### Other changes

* **dev:** serve axe from the app origin ([#71](https://github.com/geebru/trailer-park/issues/71)) ([d1d6eb6](https://github.com/geebru/trailer-park/commit/d1d6eb6d4ea66af78073207b4852c04b02536791)), closes [#69](https://github.com/geebru/trailer-park/issues/69)

## [0.10.0](https://github.com/geebru/trailer-park/compare/v0.9.0...v0.10.0) (2026-11-08)


### ⚠ BREAKING CHANGES

* **api:** Requests with an unexpected Host header now get 421. If you open Trailer Park by your own domain, a reverse proxy name or a Tailscale name, add it to ALLOWED_HOSTS (comma separated, *.example.com allowed) and restart; IP addresses, localhost, short LAN names and .local, .lan and .home.arpa names need nothing.

### ✨ Features

* **activity:** log Sync now checks, including failures ([#41](https://github.com/geebru/trailer-park/issues/41)) ([e6d3537](https://github.com/geebru/trailer-park/commit/e6d3537b75302d6204b667b1fccbae52050bb558))


### 🐛 Bug fixes

* **api:** reject requests with an unexpected Host header ([#64](https://github.com/geebru/trailer-park/issues/64)) ([1f2e66d](https://github.com/geebru/trailer-park/commit/1f2e66de9254d1fa8963b973f554367ecda5cf02)), closes [#47](https://github.com/geebru/trailer-park/issues/47)
* **api:** send security headers ([#63](https://github.com/geebru/trailer-park/issues/63)) ([c059145](https://github.com/geebru/trailer-park/commit/c059145f37acf1a477bb3f37203fe3bfd6d9d9e8)), closes [#48](https://github.com/geebru/trailer-park/issues/48)
* **docker:** make the image work when run as a non-root user ([#65](https://github.com/geebru/trailer-park/issues/65)) ([e04aa2a](https://github.com/geebru/trailer-park/commit/e04aa2abd1d3855c4a8e4c3f70ac4b20533aa4b0)), closes [#49](https://github.com/geebru/trailer-park/issues/49)
* **engine:** keep secrets out of logs, Activity and error text ([#56](https://github.com/geebru/trailer-park/issues/56)) ([14d6ea3](https://github.com/geebru/trailer-park/commit/14d6ea3eed5a88ebee04c3b94b7ab36b6c698a43)), closes [#50](https://github.com/geebru/trailer-park/issues/50)
* **settings:** accept only Discord webhook URLs ([#55](https://github.com/geebru/trailer-park/issues/55)) ([1e49792](https://github.com/geebru/trailer-park/commit/1e49792ce554663b5d07606a16bc1216648cf903))
* **settings:** require the API key again when an Arr URL changes ([#61](https://github.com/geebru/trailer-park/issues/61)) ([d8678d8](https://github.com/geebru/trailer-park/commit/d8678d838ead2501e367a09f72e62f8344ed1d64)), closes [#45](https://github.com/geebru/trailer-park/issues/45)
* **trailers:** switch list layout by panel width ([#62](https://github.com/geebru/trailer-park/issues/62)) ([1aa2684](https://github.com/geebru/trailer-park/commit/1aa2684b1bf51b291dc794ab3b4e8ba2c53f4fde))


### 📝 Documentation

* add an AI disclaimer to the README ([#43](https://github.com/geebru/trailer-park/issues/43)) ([ce7d952](https://github.com/geebru/trailer-park/commit/ce7d9529a1091b2093747f8ebe105d9c76ef9aea))
* add SECURITY.md and say what the app does and does not protect ([#60](https://github.com/geebru/trailer-park/issues/60)) ([1d8681d](https://github.com/geebru/trailer-park/commit/1d8681dde1d030a7049e9e35ee081a74fa2cb96e))
* add the MIT license and third-party notices ([#40](https://github.com/geebru/trailer-park/issues/40)) ([d4b3d6f](https://github.com/geebru/trailer-park/commit/d4b3d6f98181758cda88133c6b8c0adf9717d952))


### Other changes

* stop signing agent commits ([#58](https://github.com/geebru/trailer-park/issues/58)) ([87e1fb7](https://github.com/geebru/trailer-park/commit/87e1fb7e3ea8638a443df4e6e87b9a15cf2df8c1))

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
