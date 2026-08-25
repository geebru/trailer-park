# Trailarr Parrk — Changelog

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
