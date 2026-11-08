# Command line, script and API

[README](../README.md) · [Using the app](using.md) · [Settings](settings.md) · [How a trailer is chosen](trailer-selection.md) · Command line and API · [Security](security.md) · [Upgrading](upgrading.md)

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

## API

The interface is a client of a JSON API under `/api`, with no authentication. `GET /health` returns the status, version and yt-dlp version.

- Requests that change something need `Content-Type: application/json` (otherwise 415). Errors look like `{"error": {"code": "...", "message": "..."}}`.
- Long actions (grab, replace, batches) return 202 with a job, which you poll with `GET /api/jobs/<id>?after=<seq>`. Only one job can be active per title (409 `job_active`).
- Titles are addressed as `/api/items/<connection_id>/<item_id>`.
- Secrets (the TMDB token, the Discord webhook) are never returned, only whether they are configured. An Arr connection keeps its saved API key when you leave it blank, but only while its URL points to the same server (scheme, host and port); a different server needs the key again (`400`).

| Area | Endpoints |
|---|---|
| Titles | `GET /api/items`, `GET /api/items/<connection>/<id>`, `POST /api/library/refresh` |
| Grab, replace, manual | `POST /api/items/<connection>/<id>/grab` (send `{"replace": true}` to replace), `POST .../force` (a specific YouTube link or ID) |
| Files | `POST /api/items/<connection>/<id>/files/rename`, `.../keep`, `.../delete`, `POST /api/items/rename-all` |
| Jobs and batches | `GET /api/jobs`, `GET /api/jobs/<id>`, `POST /api/jobs/<id>/cancel`, `POST /api/batches` (a scope, or `{"items": [{"connection", "id", "replace"?}]}` for a selection: missing titles are grabbed, titles with a trailer only when `replace` is true), `GET /api/batches/current`, `POST /api/batches/current/cancel` |
| Sync | `POST /api/watcher/run` |
| Overview and activity | `GET /api/overview`, `GET /api/activity`, `POST /api/activity/clear` |
| Settings | `GET` and `PUT /api/settings`, `POST /api/settings/test/<service>`, `POST /api/settings/naming-preview`, `POST /api/connections/test` |
| yt-dlp | `GET /api/yt-dlp`, `POST /api/yt-dlp/check`, `POST /api/yt-dlp/update` |
