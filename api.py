"""JSON API, v1 (SPEC section 6). Thin wrappers only: parse the request, call the engine or the
cache, shape the JSON. No business logic here; if it is needed it goes in engine.py so the
CLI and the watcher can use it too.

M1: read endpoints. M2: grab/replace/force as async jobs plus the job endpoints.
"""
import datetime as dt
import os
import threading

from flask import Blueprint, jsonify, request

import engine as E
import jobs
import library_cache as cache

bp = Blueprint("api", __name__, url_prefix="/api")

PER_PAGE_ALLOWED = (10, 25, 50, 100, 250)
TYPES = ("movie", "series")
PUBLIC_FIELDS = ("key", "connection_id", "connection_name", "type", "id", "title", "year",
                 "root_folder", "folder", "presence", "name_differs", "file_count",
                 "total_size", "primary_file")


def error(code, message, status=400):
    return jsonify({"error": {"code": code, "message": message}}), status


def public(snap):
    return {k: snap[k] for k in PUBLIC_FIELDS}


def int_arg(name, default, minimum=1):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"'{name}' must be a whole number.")
    if value < minimum:
        raise ValueError(f"'{name}' must be at least {minimum}.")
    return value


# ── Items ─────────────────────────────────────────────────────────────────

@bp.get("/items")
def list_items():
    media_type = request.args.get("type") or None
    if media_type and media_type not in TYPES:
        return error("bad_type", "type must be 'movie' or 'series'.")
    connection_id = request.args.get("connection") or None
    if connection_id and not E.get_connection(connection_id):
        return error("unknown_connection", "No such connection.")
    root = request.args.get("root") or None
    query = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status") or None
    tag = request.args.get("tag") or None
    if status not in (None, "missing", "present"):
        return error("bad_status", "status must be 'missing' or 'present'.")
    if tag not in (None, "name_differs", "multiple"):
        return error("bad_tag", "tag must be 'name_differs' or 'multiple'.")
    sort = request.args.get("sort", "title")
    order = request.args.get("order", "asc")
    if sort not in ("title", "year") or order not in ("asc", "desc"):
        return error("bad_sort", "sort must be title|year and order asc|desc.")
    try:
        page = int_arg("page", 1)
        per_page = int_arg("per_page", 25)
    except ValueError as e:
        return error("bad_page", str(e))
    if per_page not in PER_PAGE_ALLOWED:
        return error("bad_page", f"per_page must be one of {', '.join(map(str, PER_PAGE_ALLOWED))}.")

    snaps, errors, scan = cache.get_view(media_type, connection_id)

    # Dropdown contents come from the type scope, not from the other filters.
    roots = sorted({s["root_folder"] for s in snaps if s["root_folder"]})
    connections = [
        {"id": c["id"], "name": c["name"], "type": c["type"]}
        for c in E.get_connections()
        if not media_type or (c["type"] == "radarr") == (media_type == "movie")
    ]

    # Counts reflect type + connection + root, but not text search, status, tag or page,
    # so tab badges stay stable while the user types (SPEC 6.3).
    scoped = [s for s in snaps if not root or s["root_folder"] == root]
    counts = {
        "missing": sum(1 for s in scoped if s["presence"] == "missing"),
        "present": sum(1 for s in scoped if s["presence"] == "present"),
        "name_differs": sum(1 for s in scoped if s["name_differs"]),
        "multiple": sum(1 for s in scoped if s["file_count"] > 1),
    }

    rows = scoped
    if query:
        rows = [s for s in rows if query in s["title"].lower()]
    if status:
        rows = [s for s in rows if s["presence"] == status]
    if tag == "name_differs":
        rows = [s for s in rows if s["name_differs"]]
    elif tag == "multiple":
        rows = [s for s in rows if s["file_count"] > 1]

    reverse = order == "desc"
    if sort == "year":
        rows.sort(key=lambda s: (s["year"] or 0, s["title"].lower()), reverse=reverse)
    else:
        rows.sort(key=lambda s: (s["title"].lower(), s["year"] or 0), reverse=reverse)

    start = (page - 1) * per_page
    return jsonify({
        "items": [public(s) for s in rows[start:start + per_page]],
        "page": page, "per_page": per_page, "total": len(rows),
        "counts": counts, "scan": scan, "errors": errors,
        "filters": {"connections": connections, "roots": roots},
    })


def _file_metadata(meta):
    if not isinstance(meta, dict):
        return None
    return {
        "youtube_id": meta.get("youtube_id"),
        "name": meta.get("tmdb_name"),
        "score": meta.get("score"),
        "source": meta.get("download_source"),
        "downloaded_at": meta.get("downloaded_at"),
    }


def _item_detail(connection_id, item_id, snap=None):
    """One item with its files; rescans that one folder first so it is always current."""
    snap = snap or cache.get_item(connection_id, item_id)
    if snap is None:
        return None
    fresh = cache.refresh_item(connection_id, item_id) or snap
    _state, files = E.trailer_state(fresh["folder"], fresh["title"], fresh["year"])
    metadata = E.load_trailer_metadata()
    return {**public(fresh), "files": [{
        "path": f["name"],
        "size": f["size"],
        "matches": f["matches"],
        "metadata": _file_metadata(metadata.get(os.path.realpath(f["path"]))),
    } for f in files]}


@bp.get("/items/<connection_id>/<int:item_id>")
def get_item(connection_id, item_id):
    detail = _item_detail(connection_id, item_id)
    if detail is None:
        return error("not_found", "No such item.", 404)
    return jsonify(detail)


@bp.post("/library/refresh")
def refresh_library():
    data = request.get_json(silent=True)
    if data is None:
        return error("bad_content_type", "Send JSON.", 415)
    connection_id = data.get("connection") or None
    if connection_id and not E.get_connection(connection_id):
        return error("unknown_connection", "No such connection.")
    cache.refresh_all(connection_id)
    return jsonify({"ok": True}), 202


# ── Overview ──────────────────────────────────────────────────────────────

def _watcher():
    minutes = E.watch_interval_seconds() // 60
    state = E.load_watch_state()
    configured = [c for c in E.get_connections() if c.get("api_key")]
    checks, last_error = [], ""
    for c in configured:
        cs = state.get(c["id"], {})
        checks.append(cs.get("last_check"))
        last_error = last_error or cs.get("last_error", "")
    last_run = next_run = None
    if configured and all(checks):
        parsed = [dt.datetime.fromisoformat(x) for x in checks]
        oldest = min(parsed)               # SPEC 6.2: oldest last_check across connections
        last_run = oldest.isoformat()
        if minutes:
            next_run = (oldest + dt.timedelta(minutes=minutes)).isoformat()
    return {"enabled": minutes > 0, "syncing": E.watch_cycle_running(), "interval_minutes": minutes,
            "last_run_at": last_run, "next_run_at": next_run, "last_error": last_error}


ACTIVITY_FIELDS = ("id", "timestamp", "status", "action", "title", "year", "detail",
                   "source", "youtube_id", "duration")


def public_activity(entry):
    out = {k: entry.get(k) for k in ACTIVITY_FIELDS}
    out["ts"] = entry.get("timestamp")
    out["kind"] = E.activity_kind(entry)
    return out


@bp.get("/overview")
def overview():
    snaps, errors, scan = cache.get_view()
    present = sum(1 for s in snaps if s["presence"] == "present")
    total = len(snaps)
    health = cache.connection_health()
    connections = []
    for c in E.get_connections():
        h = health.get(c["id"])
        connections.append({
            "id": c["id"], "name": c["name"], "type": c["type"],
            "url": c["url"],
            "online": None if h is None else h["online"],
            "checked_at": h["checked_at"] if h else None,
            "error": h["error"] if h else "",
        })
    return jsonify({
        "totals": {
            "all": total,
            "movies": sum(1 for s in snaps if s["type"] == "movie"),
            "series": sum(1 for s in snaps if s["type"] == "series"),
            "missing": total - present,
            "present": present,
            "coverage": round(present / total * 100, 1) if total else None,
            "name_differs": sum(1 for s in snaps if s["name_differs"]),
            "multiple": sum(1 for s in snaps if s["file_count"] > 1),
        },
        "scan": scan,
        "errors": errors,
        "watcher": _watcher(),
        "connections": connections,
        "activity": [public_activity(e) for e in E.read_activity(limit=8)],
    })


# ── Jobs (SPEC section 5, 6.4) ────────────────────────────────────────────

def _json_body():
    """Mutating endpoints require Content-Type: application/json (CSRF defence, D12)."""
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _item_or_error(connection_id, item_id):
    snap = cache.get_item(connection_id, item_id)
    if snap is None:
        return None, error("not_found", "No such item.", 404)
    return snap, None


def _submit(kind, connection_id, item_id, **params):
    snap, err = _item_or_error(connection_id, item_id)
    if err:
        return err
    try:
        job = jobs.submit(kind, connection_id, item_id, snap["title"], snap["year"], **params)
    except jobs.Conflict as c:
        response = error("job_active", "A job is already running for this item.", 409)
        body = response[0].get_json()
        body["error"]["job"] = c.job.summary()
        return jsonify(body), 409
    return jsonify({"job": job.summary()}), 202


@bp.post("/items/<connection_id>/<int:item_id>/grab")
def grab_item(connection_id, item_id):
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    replace = data.get("replace", False)
    if not isinstance(replace, bool):
        return error("bad_replace", "'replace' must be true or false.")
    return _submit("replace" if replace else "grab", connection_id, item_id)


@bp.post("/items/<connection_id>/<int:item_id>/force")
def force_item(connection_id, item_id):
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    yt_id = E.parse_youtube_id(data.get("video"))
    if not yt_id:
        return error("bad_video", "Enter a YouTube video ID or link.")
    return _submit("force", connection_id, item_id, youtube_id=yt_id)


@bp.get("/jobs")
def list_jobs():
    return jsonify({"jobs": jobs.list_jobs(active_only=request.args.get("active") == "1")})


@bp.get("/jobs/<job_id>")
def get_job(job_id):
    job = jobs.get(job_id)
    if job is None:
        return error("not_found", "No such job (it may have expired).", 404)
    try:
        after = int_arg("after", 0, minimum=0)
    except ValueError as e:
        return error("bad_param", str(e))
    return jsonify(jobs.view(job, after))


@bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id):
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    job = jobs.get(job_id)
    if job is None:
        return error("not_found", "No such job (it may have expired).", 404)
    if not jobs.cancel(job):
        return error("not_active", "That job has already finished.", 409)
    return jsonify({"job": job.summary()}), 202


# ── Batches and Sync now (SPEC 5.4, 6.4) ──────────────────────────────────

@bp.post("/batches")
def create_batch():
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    connection_id = data.get("connection") or None
    media_type = data.get("type") or None
    if connection_id and not E.get_connection(connection_id):
        return error("unknown_connection", "No such connection.")
    if media_type and media_type not in TYPES:
        return error("bad_type", "type must be 'movie' or 'series'.")
    snaps, _errors, scan = cache.get_view(media_type, connection_id)
    if scan["state"] != "ready" and not snaps:
        return error("scanning", "The library is still being scanned. Try again in a moment.", 409)
    missing = [s for s in snaps if s["presence"] == "missing"]
    if not missing:
        return error("nothing_to_do", "No missing trailers in this scope.", 409)
    scope = (E.get_connection(connection_id)["name"] if connection_id else "All libraries")
    if media_type:
        scope += " (movies)" if media_type == "movie" else " (series)"
    try:
        batch = jobs.start_batch(scope, [
            {"connection_id": s["connection_id"], "id": s["id"],
             "title": s["title"], "year": s["year"]} for s in missing])
    except jobs.BatchBusy:
        return error("batch_active", "A batch is already running.", 409)
    return jsonify({"batch": batch.summary()}), 202


@bp.get("/batches/current")
def current_batch():
    batch = jobs.current_batch()
    return jsonify({"batch": batch.summary() if batch else None})


@bp.post("/batches/current/cancel")
def cancel_batch():
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    batch = jobs.cancel_batch()
    if batch is None:
        return error("not_active", "No batch is running.", 409)
    return jsonify({"batch": batch.summary()}), 202


@bp.post("/watcher/run")
def run_watcher():
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    if E.watch_cycle_running():
        return error("watcher_busy", "A sync is already running.", 409)
    threading.Thread(target=lambda: E.run_watch_cycle(force=True), daemon=True,
                     name="sync-now").start()
    return jsonify({"ok": True}), 202


# ── File actions (SPEC 6.2) ───────────────────────────────────────────────

def _file_action(connection_id, item_id, action):
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    path = data.get("path")
    if not isinstance(path, str) or not path.strip():
        return error("bad_path", "'path' is required.")
    snap, err = _item_or_error(connection_id, item_id)
    if err:
        return err
    if jobs.active_for_item(connection_id, item_id):
        return error("job_active", "A download is running for this item.", 409)
    try:
        action(connection_id, item_id, path)
    except ValueError as e:
        return error("not_allowed", str(e), 400)
    except OSError as e:
        return error("file_error", f"Could not change the file: {e.strerror or e}", 500)
    return jsonify(_item_detail(connection_id, item_id, snap))


@bp.post("/items/<connection_id>/<int:item_id>/files/rename")
def rename_file(connection_id, item_id):
    return _file_action(connection_id, item_id, E.rename_item_file)


@bp.post("/items/<connection_id>/<int:item_id>/files/keep")
def keep_file(connection_id, item_id):
    return _file_action(connection_id, item_id, E.keep_item_file)


@bp.post("/items/<connection_id>/<int:item_id>/files/delete")
def delete_file(connection_id, item_id):
    return _file_action(connection_id, item_id, E.delete_item_file)


@bp.post("/items/rename-all")
def rename_all():
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    media_type = data.get("type") or None
    connection_id = data.get("connection") or None
    dry_run = data.get("dry_run", False)
    if media_type and media_type not in TYPES:
        return error("bad_type", "type must be 'movie' or 'series'.")
    if connection_id and not E.get_connection(connection_id):
        return error("unknown_connection", "No such connection.")
    if not isinstance(dry_run, bool):
        return error("bad_dry_run", "'dry_run' must be true or false.")
    snaps, _errors, scan = cache.get_view(media_type, connection_id)
    if scan["state"] != "ready" and not snaps:
        return error("scanning", "The library is still being scanned. Try again in a moment.", 409)
    candidates = [s for s in snaps if s["name_differs"]]
    scope = E.get_connection(connection_id)["name"] if connection_id else "All libraries"
    result = E.rename_all(candidates, scope, dry_run=dry_run)
    if dry_run:
        return jsonify(result)
    for entry in result["renamed"]:
        cache.refresh_item(entry["connection_id"], entry["id"])
    return jsonify(result)


# ── Naming preview ────────────────────────────────────────────────────────

@bp.post("/settings/naming-preview")
def naming_preview():
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    sample = data.get("sample") if isinstance(data.get("sample"), dict) else {}
    title = str(sample.get("title") or "Avengers: Infinity War")
    year = str(sample.get("year") or "2018")
    try:
        path = E.naming_preview(
            data.get("template", E.cfg("filename_template")),
            data.get("folder", E.cfg("trailer_folder")),
            data.get("container"), title, year)
    except ValueError as e:
        return error("invalid_naming", str(e), 400)
    return jsonify({"path": path})


# ── Activity ──────────────────────────────────────────────────────────────

@bp.get("/activity")
def list_activity():
    status = request.args.get("status") or None
    if status not in (None, "success", "warning", "error"):
        return error("bad_status", "status must be success, warning or error.")
    try:
        page = int_arg("page", 1)
        per_page = int_arg("per_page", 25)
    except ValueError as e:
        return error("bad_param", str(e))
    if per_page not in PER_PAGE_ALLOWED:
        return error("bad_param", f"per_page must be one of {', '.join(map(str, PER_PAGE_ALLOWED))}.")
    entries, total = E.read_activity_page(page, per_page, status)
    return jsonify({"items": [public_activity(e) for e in entries], "total": total,
                    "page": page, "per_page": per_page,
                    "pages": max(1, -(-total // per_page))})


@bp.post("/activity/clear")
def clear_activity():
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    E.clear_activity()
    return jsonify({"ok": True})


# ── Settings ──────────────────────────────────────────────────────────────

@bp.get("/settings")
def get_settings():
    return jsonify(E.public_settings())


@bp.put("/settings")
def put_settings():
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    try:
        return jsonify(E.apply_settings_update(data))
    except ValueError as e:
        return error("invalid_settings", str(e), 400)


@bp.post("/settings/test/<service>")
def test_service(service):
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    if service not in ("tmdb", "discord"):
        return error("not_found", "Unknown service.", 404)
    try:
        message = E.test_service(service, data)
    except Exception as e:      # noqa: BLE001 - network errors, bad tokens, bad URLs
        return error("test_failed", str(e), 400)
    return jsonify({"ok": True, "message": message, "configured": E.configured_state()})


@bp.post("/connections/test")
def test_connection():
    data = _json_body()
    if data is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    try:
        connection, version = E.test_and_save_arr_connection(data)
    except Exception as e:      # noqa: BLE001
        return error("test_failed", str(e), 400)
    return jsonify({"ok": True, "version": version,
                    "message": f"{connection['name']} connected (version {version}). Saved.",
                    "connection": E.connection_public(connection)})


# ── yt-dlp ────────────────────────────────────────────────────────────────

@bp.get("/yt-dlp")
def ytdlp_status():
    return jsonify(E.ytdlp_ui_status())


@bp.post("/yt-dlp/check")
def ytdlp_check():
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    try:
        E.check_and_store_latest_ytdlp()
    except Exception as e:      # noqa: BLE001
        return error("check_failed", str(e), 502)
    return jsonify(E.ytdlp_ui_status())


@bp.post("/yt-dlp/update")
def ytdlp_update():
    if _json_body() is None:
        return error("bad_content_type", "Send a JSON body.", 415)
    try:
        version = E.update_ytdlp_override()
    except Exception as e:      # noqa: BLE001
        return error("update_failed", str(e), 502)
    return jsonify(E.ytdlp_ui_status())
