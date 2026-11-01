"""In-memory library cache (SPEC section 4).

Why: the old UI ran a full Arr list request plus per-item filesystem scans on every page
view and again after every click. Here a background worker does that work once, keeps the
result in memory, and every read is a dictionary walk with no I/O.

Design rules
  * Reads never block on the Arr or the disk (stale-while-revalidate).
  * One worker thread scans items sequentially. That is deliberately gentle on spinning
    disks and NAS shares. A separate small thread probes connection health.
  * Snapshots are replaced, never mutated, so a reader never sees a half-built item.
  * Imports `engine` only. Never import `app` (see engine.py header).

Public API: start, get_view, get_item, refresh_item, refresh_all, connection_health.
"""
import os
import threading
import time

import engine as E

ARR_TTL = 300            # seconds between Arr list refreshes
FULL_RESCAN_TTL = 3600   # a snapshot older than this is rescanned at the next refresh
HEALTH_TTL = 60          # seconds between connection health probes
LOOP_SLEEP = 10          # worker wake-up interval; also woken early by _wake
PUBLISH_EVERY = 200      # publish partial scan results this often while scanning

_lock = threading.RLock()
_conns = {}              # connection_id -> state dict (see _new_state)
_health = {}             # connection_id -> {"online", "checked_at", "error"}
_wake = threading.Event()
_started = False


def _new_state(connection):
    return {
        "sig": _conn_sig(connection),
        "naming_sig": None,        # naming settings the snapshots were scanned with
        "items": {},               # arr item id -> snapshot dict (replaced, not mutated)
        "arr_at": 0.0,             # monotonic time of last successful Arr list fetch
        "force_full": True,        # rescan everything at the next refresh
        "scan": {"state": "idle", "done": 0, "total": 0},
        "error": "",
        "roots": [],               # root folder paths from the Arr, for prefix fallback
    }


def _conn_sig(connection):
    return (connection.get("type"), connection.get("url"), connection.get("api_key"))


def _naming_sig():
    # Anything that changes whether a file "matches" the configured name.
    return (E.cfg("trailer_folder"), E.cfg("filename_template"), E.cfg("container"))


def _media_type(connection):
    return "movie" if connection.get("type") == "radarr" else "series"


# ── Building snapshots ────────────────────────────────────────────────────

def _root_for(raw, folder, roots):
    root = (raw.get("root_folder") or "").rstrip("/")
    if root:
        return root
    best = ""
    for candidate in roots:
        c = candidate.rstrip("/")
        if (folder == c or folder.startswith(c + "/")) and len(c) > len(best):
            best = c
    return best or os.path.dirname(folder.rstrip("/"))


def _year(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize(files):
    """Pure helper: trailer_state() file dicts -> summary fields (SPEC 3.2)."""
    if not files:
        return {"presence": "missing", "name_differs": False, "file_count": 0,
                "total_size": 0, "primary_file": None}
    primary = next((f for f in files if f["matches"]), files[0])
    return {
        "presence": "present",
        # True only when NO file sits at the configured name (decision Q1).
        "name_differs": not any(f["matches"] for f in files),
        "file_count": len(files),
        "total_size": sum(f["size"] for f in files),
        "primary_file": primary["name"],
    }


def _scan(connection, raw, roots, naming_sig):
    """Return a snapshot for one Arr item, or None if the item is not usable
    (folder not visible to this container, or a Radarr movie with no file)."""
    if not E.item_is_usable(raw):
        return None
    try:
        folder = E.safe_folder_path(raw["path"])
    except ValueError:
        return None
    _state, files = E.trailer_state(folder, raw["title"], raw["year"])
    snap = {
        "key": f"{connection['id']}:{raw['id']}",
        "connection_id": connection["id"],
        "connection_name": connection.get("name", connection["id"]),
        "type": _media_type(connection),
        "id": raw["id"],
        "title": raw["title"],
        "year": _year(raw.get("year")),
        "root_folder": _root_for(raw, folder, roots),
        "folder": folder,
        **summarize(files),
        "_path": raw.get("path", ""),
        "_has_media": bool(raw.get("has_media")),
        "_scanned_at": time.monotonic(),
        "_naming_sig": naming_sig,
        "_raw": raw,
    }
    return snap


def _reusable(old, raw, naming_sig, full):
    return (
        old is not None and not full
        and old["_path"] == raw.get("path", "")
        and old["_has_media"] == bool(raw.get("has_media"))
        and old["_naming_sig"] == naming_sig
        and time.monotonic() - old["_scanned_at"] < FULL_RESCAN_TTL
    )


def _refresh_connection(connection):
    cid = connection["id"]
    with _lock:
        st = _conns[cid]
        full = st["force_full"]
        st["force_full"] = False
        old_items = st["items"]
        st["scan"] = {"state": "scanning", "done": 0, "total": st["scan"]["total"]}

    raw_items, error = E.load_connection_items(connection)
    if error:
        with _lock:
            st["error"] = error
            st["arr_at"] = time.monotonic() - ARR_TTL + 30     # retry in ~30 s, not every loop
            st["scan"] = {"state": "ready", "done": len(old_items), "total": len(old_items)}
        _set_health(cid, False, error)
        return
    _set_health(cid, True, "")

    try:
        roots = [r.get("path", "") for r in E.arr_get(connection, "/api/v3/rootfolder") if r.get("path")]
    except Exception:
        roots = st["roots"]

    naming_sig = _naming_sig()
    if st["naming_sig"] != naming_sig:
        full = True
    total = len(raw_items)
    new_items = {}
    with _lock:
        st["scan"] = {"state": "scanning", "done": 0, "total": total}
        st["roots"] = roots

    for n, raw in enumerate(raw_items, 1):
        if _conns.get(cid) is not st:          # connection removed/replaced mid-scan
            return
        old = old_items.get(raw["id"])
        snap = old if _reusable(old, raw, naming_sig, full) else _scan(connection, raw, roots, naming_sig)
        if snap is not None:
            new_items[raw["id"]] = snap
        if n % PUBLISH_EVERY == 0:
            with _lock:
                st["items"] = dict(new_items)
                st["scan"] = {"state": "scanning", "done": n, "total": total}

    with _lock:
        if _conns.get(cid) is not st:
            return
        st["items"] = new_items                # copy-on-write: whole dict replaced at once
        st["naming_sig"] = naming_sig
        st["arr_at"] = time.monotonic()
        st["error"] = ""
        st["scan"] = {"state": "ready", "done": total, "total": total}


# ── Health ────────────────────────────────────────────────────────────────

def _set_health(cid, online, error):
    with _lock:
        _health[cid] = {"online": online, "error": error,
                        "checked_at": E.utc_now(), "_t": time.monotonic()}


def _probe(connection):
    cid = connection["id"]
    if not connection.get("api_key"):
        _set_health(cid, False, "Not configured")
        return
    try:
        E.arr_get(connection, "/api/v3/system/status")
        _set_health(cid, True, "")
    except Exception as e:
        _set_health(cid, False, str(e)[:200])


def connection_health():
    with _lock:
        return {k: {a: b for a, b in v.items() if not a.startswith("_")}
                for k, v in _health.items()}


# ── Background threads ────────────────────────────────────────────────────

def _sync_connections():
    """Add states for new connections, drop removed ones, reset edited ones."""
    connections = E.get_connections()
    ids = set()
    with _lock:
        for c in connections:
            cid = c["id"]
            ids.add(cid)
            st = _conns.get(cid)
            if st is None or st["sig"] != _conn_sig(c):
                _conns[cid] = _new_state(c)
                _health.pop(cid, None)
        for cid in list(_conns):
            if cid not in ids:
                del _conns[cid]
                _health.pop(cid, None)
    return connections


def _worker():
    while True:
        try:
            connections = _sync_connections()
            naming_sig = _naming_sig()
            for c in connections:
                with _lock:
                    st = _conns.get(c["id"])
                    due = (
                        st is not None and c.get("api_key") and (
                            st["force_full"]
                            or st["naming_sig"] != naming_sig
                            or time.monotonic() - st["arr_at"] > ARR_TTL
                        )
                    )
                if due:
                    try:
                        _refresh_connection(c)
                    except Exception as e:
                        E.log.warning(f"Library scan failed for {c.get('name')}: {e}")
                        with _lock:
                            if c["id"] in _conns:
                                _conns[c["id"]]["scan"]["state"] = "ready"
                                _conns[c["id"]]["error"] = str(e)[:200]
                elif st is not None and not c.get("api_key"):
                    with _lock:
                        st["error"] = "Not configured"
                        st["scan"] = {"state": "ready", "done": 0, "total": 0}
        except Exception as e:
            E.log.warning(f"Library cache worker error: {e}")
        _wake.wait(LOOP_SLEEP)
        _wake.clear()


def _health_worker():
    while True:
        try:
            for c in E.get_connections():
                with _lock:
                    h = _health.get(c["id"])
                if h is None or time.monotonic() - h["_t"] > HEALTH_TTL:
                    _probe(c)      # a successful Arr list refresh also refreshes health
        except Exception as e:
            E.log.warning(f"Health probe error: {e}")
        time.sleep(15)


def start():
    """Start the background threads once. Safe to call repeatedly."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_worker, name="library-cache", daemon=True).start()
    threading.Thread(target=_health_worker, name="library-health", daemon=True).start()


# ── Reads (no I/O) ────────────────────────────────────────────────────────

def get_view(media_type=None, connection_id=None):
    """Return (snapshots, per-connection errors, scan summary) for the filter.

    Cheap: copies references only. Starts the worker if needed and nudges it when settings
    that affect matching have changed since the last scan."""
    start()
    connections = _sync_connections()
    sig = _naming_sig()
    if any(st["naming_sig"] and st["naming_sig"] != sig for st in _conns.values()):
        _wake.set()       # naming settings changed: let the worker rescan now, not in 10 s
    items, errors = [], []
    done = total = 0
    scanning = False
    with _lock:
        for c in connections:
            if media_type and _media_type(c) != media_type:
                continue
            if connection_id and c["id"] != connection_id:
                continue
            st = _conns.get(c["id"])
            if st is None:
                continue
            items.extend(st["items"].values())
            if st["error"] and st["error"] != "Not configured":
                errors.append({"connection_id": c["id"], "message": st["error"]})
            done += st["scan"]["done"]
            total += st["scan"]["total"]
            scanning = scanning or st["scan"]["state"] != "ready"
    return items, errors, {"state": "scanning" if scanning else "ready", "done": done, "total": total}


def get_item(connection_id, item_id):
    with _lock:
        st = _conns.get(connection_id)
        return st["items"].get(item_id) if st else None


def refresh_item(connection_id, item_id):
    """Rescan one item's folder now (SPEC 4.3). Call from the code path that changed files,
    before reporting success, so the UI never shows a stale row. Returns the new snapshot
    or None if the item is no longer usable."""
    connection = E.get_connection(connection_id)
    if not connection:
        return None
    with _lock:
        st = _conns.get(connection_id)
        old = st["items"].get(item_id) if st else None
        roots = st["roots"] if st else []
    raw = old["_raw"] if old else E.get_connection_item(connection, item_id)
    snap = _scan(connection, raw, roots, _naming_sig())
    with _lock:
        st = _conns.get(connection_id)
        if st is not None:
            items = dict(st["items"])
            if snap is None:
                items.pop(item_id, None)
            else:
                items[item_id] = snap
            st["items"] = items
    return snap


def refresh_all(connection_id=None):
    """Schedule a full Arr re-fetch and rescan ("Refresh" button)."""
    _sync_connections()
    with _lock:
        for cid, st in _conns.items():
            if connection_id in (None, cid):
                st["force_full"] = True
    _wake.set()
