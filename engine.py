"""Trailarr Parrk engine: settings, Arr/TMDB clients, scoring, downloads, trailer
file handling, batch and watcher logic. No Flask imports here.

Extracted unchanged from app.py (SPEC section 8.1, milestone M0). app.py imports this
module; nothing here may import app (the CLI runs app.py as __main__, so importing it
would load a second copy and duplicate global state).
"""
import argparse
import concurrent.futures
import contextlib
import datetime as dt
import fcntl
import glob
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from collections import deque
from copy import deepcopy



logging.basicConfig(
    level=logging.INFO,
    format="[trailarr-parrk] %(message)s"
)
log = logging.getLogger(__name__)

APP_VERSION = "0.8.0"


# ── Paths / persistent state ──────────────────────────────────────────────

SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "/config/settings.json")
CONFIG_DIR = os.path.dirname(SETTINGS_FILE) or "/config"
ACTIVITY_FILE = os.environ.get(
    "ACTIVITY_FILE",
    os.path.join(CONFIG_DIR, "activity.jsonl")
)
TRAILER_METADATA_FILE = os.environ.get(
    "TRAILER_METADATA_FILE",
    os.path.join(CONFIG_DIR, "trailers.json")
)
YTDLP_OVERRIDE = os.environ.get(
    "YTDLP_OVERRIDE",
    os.path.join(CONFIG_DIR, "bin", "yt-dlp")
)
YTDLP_STATUS_FILE = os.environ.get(
    "YTDLP_STATUS_FILE",
    os.path.join(CONFIG_DIR, "ytdlp-status.json")
)
YTDLP_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
YTDLP_MONITOR_INTERVAL_SECONDS = 60 * 60

WATCH_STATE_FILE = os.environ.get(
    "WATCH_STATE_FILE",
    os.path.join(CONFIG_DIR, "watch-state.json")
)
WATCH_PENDING_DAYS = 30


DOWNLOAD_SLOT_DIR = os.environ.get(
    "DOWNLOAD_SLOT_DIR",
    os.path.join(CONFIG_DIR, "download-slots")
)


# ── Configuration ─────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "tmdb_api_key": os.environ.get("TMDB_API_KEY", ""),
    "discord_webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", ""),
    # Legacy v0.5.x fields are kept for automatic migration.
    "radarr_url": (os.environ.get("RADARR_URL") or "http://radarr:7878").rstrip("/"),
    "radarr_api_key": os.environ.get("RADARR_API_KEY", ""),
    "sonarr_url": (os.environ.get("SONARR_URL") or "http://sonarr:8989").rstrip("/"),
    "sonarr_api_key": os.environ.get("SONARR_API_KEY", ""),
    "media_root": os.environ.get("MEDIA_ROOT", "/data/media"),
    "preferred_terms": os.environ.get(
        "PREFERRED_TERMS",
        "official,trailer,teaser,theatrical,season 1,season 01,announcement"
    ),
    "excluded_terms": os.environ.get(
        "EXCLUDED_TERMS",
        (
            "fan made,fan-made,reaction,parody,review,recut,"
            "behind the scenes,featurette"
        )
    ),
    "trailer_folder": os.environ.get("TRAILER_FOLDER", "trailers"),
    "filename_template": os.environ.get(
        "FILENAME_TEMPLATE",
        "{title} ({year}).trailer"
    ),
    "video_quality": os.environ.get("VIDEO_QUALITY", "1080"),
    # Discord notification toggles: on | off.
    "notify_success": os.environ.get("NOTIFY_SUCCESS", "on"),
    "notify_failure": os.environ.get("NOTIFY_FAILURE", "on"),
    # Days of Activity history to keep; 0 = forever.
    "activity_retention_days": os.environ.get("ACTIVITY_RETENTION_DAYS", "90"),
    # Output container for downloaded trailers: mkv | mp4.
    "container": os.environ.get("CONTAINER", "mkv"),
    "max_concurrent_downloads": os.environ.get(
        "MAX_CONCURRENT_DOWNLOADS",
        "1"
    ),
    # Minutes between Arr API checks for new imports/upgrades (Radarr) and
    # newly added series (Sonarr). 0 disables the watcher.
    "watch_interval_minutes": os.environ.get("WATCH_INTERVAL_MINUTES", "5"),
    # TV shows with no show-level trailer: off | first | latest season.
    "season_fallback": os.environ.get("SEASON_FALLBACK", "first"),
    # Search YouTube directly when TMDB has no usable trailer: off | on.
    "youtube_search": os.environ.get("YOUTUBE_SEARCH", "off")
}

SETTINGS_LOCK = threading.RLock()
BATCH_LOCK = threading.RLock()
LOCAL_ACTIVITY_LOCK = threading.RLock()
YTDLP_STATUS_LOCK = threading.RLock()
BACKGROUND_JOBS_LOCK = threading.RLock()
WATCH_LOCK = threading.RLock()
BACKGROUND_JOBS_STARTED = False


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(value, fallback="item"):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return value or fallback


def unique_id(prefix, name=""):
    return f"{prefix}-{slugify(name, prefix)}-{uuid.uuid4().hex[:6]}"


def legacy_connections(settings):
    return [
        {
            "id": "radarr-main",
            "name": "Radarr",
            "type": "radarr",
            "url": settings.get("radarr_url", "http://radarr:7878"),
            "api_key": settings.get("radarr_api_key", "")
        },
        {
            "id": "sonarr-main",
            "name": "Sonarr",
            "type": "sonarr",
            "url": settings.get("sonarr_url", "http://sonarr:8989"),
            "api_key": settings.get("sonarr_api_key", "")
        }
    ]


QUALITY_CHOICES = (480, 720, 1080, 2160)
RETENTION_CHOICES = (0, 60, 90, 180, 365)


def snap_quality(value):
    """Nearest allowed resolution (ties go lower): 1440 -> 1080, 360 -> 480."""
    try:
        number = int(str(value).strip())
    except ValueError:
        return "1080"
    return str(min(QUALITY_CHOICES, key=lambda q: (abs(q - number), q)))


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    saved = {}

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)

        if not isinstance(saved, dict):
            saved = {}

    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning(f"Could not load settings: {e}")

    for key in DEFAULT_SETTINGS:
        if key in saved:
            settings[key] = str(saved[key])

    settings["video_quality"] = snap_quality(settings["video_quality"])

    connections = saved.get("arr_connections")

    settings["arr_connections"] = (
        connections if isinstance(connections, list) else legacy_connections(settings)
    )

    return settings


SETTINGS = load_settings()


def cfg(key):
    with SETTINGS_LOCK:
        return SETTINGS.get(key, DEFAULT_SETTINGS.get(key, ""))


def cfg_list(key):
    return [
        item.strip().lower()
        for item in str(cfg(key)).split(",")
        if item.strip()
    ]


def get_connections():
    with SETTINGS_LOCK:
        return deepcopy(SETTINGS.get("arr_connections", []))


def get_libraries():
    """One catch-all library per connection (SPEC 3.4). library_id == connection_id.
    A stored "libraries" key in settings.json is ignored."""
    return [
        {"id": c["id"], "name": c.get("name", ""), "connection_id": c["id"], "root_path": ""}
        for c in get_connections()
    ]


def get_connection(connection_id):
    for connection in get_connections():
        if connection.get("id") == connection_id:
            return connection
    return None


def get_library(library_id):
    for library in get_libraries():
        if library.get("id") == library_id:
            return library
    return None


def first_library_id():
    libraries = get_libraries()
    return libraries[0].get("id") if libraries else None


def sync_legacy_fields(settings):
    connections = settings.get("arr_connections", [])

    first_radarr = next((c for c in connections if c.get("type") == "radarr"), None)
    first_sonarr = next((c for c in connections if c.get("type") == "sonarr"), None)

    if first_radarr:
        settings["radarr_url"] = first_radarr.get("url", "")
        settings["radarr_api_key"] = first_radarr.get("api_key", "")

    if first_sonarr:
        settings["sonarr_url"] = first_sonarr.get("url", "")
        settings["sonarr_api_key"] = first_sonarr.get("api_key", "")


def save_settings(updated):
    with SETTINGS_LOCK:
        SETTINGS.update(deepcopy(updated))
        sync_legacy_fields(SETTINGS)

        os.makedirs(CONFIG_DIR, exist_ok=True)
        temp_file = f"{SETTINGS_FILE}.tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, indent=2, ensure_ascii=False)
            f.write("\n")

        os.chmod(temp_file, 0o600)
        os.replace(temp_file, SETTINGS_FILE)

        try:
            os.chmod(SETTINGS_FILE, 0o600)
        except OSError:
            pass


def validate_media_root(media_root):
    media_root = (media_root or "").strip()

    if not media_root or not os.path.isabs(media_root):
        raise ValueError("Media root must be an absolute container path.")

    media_root = os.path.normpath(media_root)

    if not os.path.isdir(media_root):
        raise ValueError(
            f"Media root does not exist inside the container: {media_root}"
        )

    if not os.access(media_root, os.R_OK | os.X_OK):
        raise ValueError(
            f"Media root is not readable inside the container: {media_root}"
        )

    return media_root


CONTAINERS = ("mkv", "mp4")


def validate_naming(trailer_folder, filename_template):
    """Validate the trailer folder + filename template. Returns the cleaned pair."""
    trailer_folder = str(trailer_folder or "").strip()
    if trailer_folder:
        if os.path.isabs(trailer_folder):
            raise ValueError("Trailer folder must be a relative folder name.")

        parts = trailer_folder.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(
                "Trailer folder cannot contain empty, '.' or '..' path parts."
            )

    filename_template = str(filename_template or "").strip()
    if not filename_template:
        raise ValueError("Filename template cannot be empty.")
    if "/" in filename_template or "\\" in filename_template:
        raise ValueError("Filename template cannot contain path separators.")
    if ".." in filename_template:
        raise ValueError("Filename template cannot contain '..'.")
    if "{title}" not in filename_template:
        raise ValueError("Filename template must contain {title}.")

    return trailer_folder, filename_template


def validate_settings_scalars(values):
    media_root = validate_media_root(values.get("media_root", ""))

    quality = str(values.get("video_quality", "")).strip()
    if not quality.isdigit() or not 1 <= int(quality) <= 8640:
        raise ValueError("Video quality must be 480, 720, 1080 or 2160.")
    quality = snap_quality(quality)

    notify_flags = {}
    for key in ("notify_success", "notify_failure"):
        raw = values.get(key, cfg(key))
        if isinstance(raw, bool):
            raw = "on" if raw else "off"
        raw = str(raw).strip().lower()
        if raw not in ("on", "off"):
            raise ValueError("Notification settings must be on or off.")
        notify_flags[key] = raw

    retention = str(values.get("activity_retention_days", cfg("activity_retention_days"))).strip()
    if not retention.isdigit() or int(retention) not in RETENTION_CHOICES:
        raise ValueError("Activity retention must be 60, 90, 180, 365 days or 0 (forever).")

    max_downloads = str(values.get("max_concurrent_downloads", "1")).strip()
    if not max_downloads.isdigit() or not 1 <= int(max_downloads) <= 4:
        raise ValueError("Concurrent downloads must be between 1 and 4.")

    youtube_search = str(values.get("youtube_search", "off")).strip().lower()
    if youtube_search not in ("off", "on"):
        raise ValueError("YouTube search fallback must be on or off.")

    season_fallback = str(values.get("season_fallback", "first")).strip().lower()
    if season_fallback not in SEASON_FALLBACK_MODES:
        raise ValueError("Season fallback must be off, first or latest.")

    container = str(values.get("container", cfg("container"))).strip().lower()
    if container not in CONTAINERS:
        raise ValueError("Container must be mkv or mp4.")

    watch_interval = str(values.get("watch_interval_minutes", "5")).strip()
    if not watch_interval.isdigit() or not 0 <= int(watch_interval) <= 1440:
        raise ValueError("Watch interval must be between 0 (off) and 1440 minutes.")

    trailer_folder, filename_template = validate_naming(
        values.get("trailer_folder", ""), values.get("filename_template", ""))

    return {
        **values,
        "media_root": media_root,
        "video_quality": quality,
        **notify_flags,
        "activity_retention_days": retention,
        "container": container,
        "max_concurrent_downloads": max_downloads,
        "watch_interval_minutes": watch_interval,
        "season_fallback": season_fallback,
        "youtube_search": youtube_search,
        "trailer_folder": trailer_folder,
        "filename_template": filename_template,
        "preferred_terms": str(values.get("preferred_terms", "")).strip(),
        "excluded_terms": str(values.get("excluded_terms", "")).strip()
    }


def safe_under_media_root(path, media_root=None):
    root = os.path.realpath(media_root or cfg("media_root"))
    resolved = os.path.realpath(path)

    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(f"Rejected out-of-bounds path: {path}")

    return resolved


def validate_connections(connections, existing_connections=None):
    existing_by_id = {
        c.get("id"): c for c in (existing_connections or get_connections())
    }
    cleaned = []
    seen_ids = set()

    if not isinstance(connections, list):
        raise ValueError("Arr connections must be a list.")

    for raw in connections:
        if not isinstance(raw, dict):
            raise ValueError("Invalid Arr connection entry.")

        connection_id = str(raw.get("id") or unique_id("arr", raw.get("name", "")))
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", connection_id):
            raise ValueError("Connection ID contains invalid characters.")
        if connection_id in seen_ids:
            raise ValueError("Duplicate Arr connection ID.")
        seen_ids.add(connection_id)

        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Every Arr connection needs a name.")

        source_type = str(raw.get("type", "")).strip().lower()
        if source_type not in ("radarr", "sonarr"):
            raise ValueError(f"Invalid Arr connection type for {name}.")

        url = str(raw.get("url", "")).strip().rstrip("/")
        if not url:
            url = "http://radarr:7878" if source_type == "radarr" else "http://sonarr:8989"

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid URL for {name}: {url}")

        existing = existing_by_id.get(connection_id, {})
        clear_key = bool(raw.get("clear_api_key"))
        submitted_key = str(raw.get("api_key", "") or "").strip()

        if clear_key:
            api_key = ""
        elif submitted_key:
            api_key = submitted_key
        else:
            api_key = str(existing.get("api_key", "") or "")

        cleaned.append({
            "id": connection_id,
            "name": name,
            "type": source_type,
            "url": url,
            "api_key": api_key
        })

    return cleaned


# ── Persistent activity / metadata ───────────────────────────────────────

@contextlib.contextmanager
def locked_sidecar(path):
    os.makedirs(os.path.dirname(path) or CONFIG_DIR, exist_ok=True)
    lock_path = f"{path}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def record_activity(event):
    entry = {
        "id": uuid.uuid4().hex,
        "timestamp": utc_now(),
        "app_version": APP_VERSION,
        **event
    }

    os.makedirs(os.path.dirname(ACTIVITY_FILE) or CONFIG_DIR, exist_ok=True)

    with LOCAL_ACTIVITY_LOCK:
        with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return entry


def read_activity(limit=250):
    try:
        with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=limit)
    except FileNotFoundError:
        return []

    entries = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                entries.append(item)
        except json.JSONDecodeError:
            continue

    return entries


def clear_activity():
    os.makedirs(os.path.dirname(ACTIVITY_FILE) or CONFIG_DIR, exist_ok=True)
    with open(ACTIVITY_FILE, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.truncate(0)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


ACTIVITY_KINDS = {
    "grab": "grab", "force": "grab", "rename": "rename", "delete": "delete",
    "batch": "batch", "batch cancelled": "batch", "batch finished": "batch",
    "yt-dlp update": "ytdlp", "cleanup": "cleanup",
}


def activity_kind(entry):
    """Structured kind for the UI, so it never parses text (SPEC B15)."""
    explicit = str(entry.get("kind") or "").strip().lower()
    if explicit:
        return explicit
    return ACTIVITY_KINDS.get(str(entry.get("action") or "").strip().lower(), "other")


def read_activity_page(page=1, per_page=25, status=None):
    """Newest first. Returns (entries, total_matching)."""
    try:
        with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return [], 0
    matching = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if status and item.get("status") != status:
            continue
        matching.append(item)
    start = (page - 1) * per_page
    return matching[start:start + per_page], len(matching)


def prune_activity(days):
    """Drop entries older than `days` (0 = keep all). Edits the file IN PLACE under the same
    flock record_activity uses; replacing the file would orphan concurrent appenders
    (including the CLI process). Malformed lines are dropped. Returns lines removed."""
    days = int(days or 0)
    if days <= 0 or not os.path.exists(ACTIVITY_FILE):
        return 0
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    def recent(line):
        try:
            stamp = json.loads(line).get("timestamp")
            return dt.datetime.fromisoformat(stamp) >= cutoff
        except (ValueError, TypeError, AttributeError):
            return False

    with LOCAL_ACTIVITY_LOCK:
        with open(ACTIVITY_FILE, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                kept = [line for line in lines if line.strip() and recent(line)]
                if len(kept) != len(lines):
                    f.seek(0)
                    f.writelines(kept)
                    f.truncate()
                    f.flush()
                return len(lines) - len(kept)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def prune_trailer_metadata():
    """Remove records whose file is gone. Skipped (with a warning) when the media root looks
    unmounted or when more than half the records would go. Returns removed count."""
    try:
        root = cfg("media_root")
        if not os.path.isdir(root) or not os.listdir(root):
            log.warning("Metadata cleanup skipped: media root is unreadable or empty.")
            return 0
    except OSError:
        log.warning("Metadata cleanup skipped: media root is unreadable.")
        return 0
    data = load_trailer_metadata()
    gone = [path for path in data if not os.path.exists(path)]
    if not gone:
        return 0
    if len(gone) * 2 > len(data):
        log.warning(f"Metadata cleanup skipped: {len(gone)} of {len(data)} records "
                    "would be removed, which looks like a missing mount.")
        return 0
    for path in gone:
        update_trailer_metadata(path, remove=True)
    return len(gone)


def run_maintenance():
    """One maintenance pass. Each step is isolated so one failure never blocks the other."""
    pruned = removed = 0
    try:
        pruned = prune_activity(cfg("activity_retention_days"))
    except Exception as e:      # noqa: BLE001
        log.warning(f"Activity pruning failed: {e}")
    try:
        removed = prune_trailer_metadata()
    except Exception as e:      # noqa: BLE001
        log.warning(f"Metadata cleanup failed: {e}")
    if pruned or removed:
        record_activity({
            "kind": "cleanup", "status": "success", "action": "cleanup", "source": "System",
            "title": "Maintenance", "year": "",
            "detail": f"Removed {pruned} old activity entr{'y' if pruned == 1 else 'ies'} "
                      f"and {removed} stale trailer record(s)."})
    return pruned, removed


MAINTENANCE_INTERVAL_SECONDS = 24 * 3600


def maintenance_monitor():
    time.sleep(60)
    while True:
        try:
            run_maintenance()
        except Exception as e:      # noqa: BLE001
            log.warning(f"Maintenance failed: {e}")
        time.sleep(MAINTENANCE_INTERVAL_SECONDS)


def load_trailer_metadata():
    with locked_sidecar(TRAILER_METADATA_FILE):
        try:
            with open(TRAILER_METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:
            log.warning(f"Could not read trailer metadata: {e}")
            return {}


def update_trailer_metadata(trailer_path, metadata=None, remove=False):
    trailer_path = os.path.realpath(trailer_path)

    with locked_sidecar(TRAILER_METADATA_FILE):
        try:
            with open(TRAILER_METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}

        if remove:
            data.pop(trailer_path, None)
        else:
            data[trailer_path] = metadata or {}

        os.makedirs(os.path.dirname(TRAILER_METADATA_FILE) or CONFIG_DIR, exist_ok=True)
        temp_path = f"{TRAILER_METADATA_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, TRAILER_METADATA_FILE)


# ── HTTP helpers ──────────────────────────────────────────────────────────

def json_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def arr_get(connection, path):
    url = str(connection.get("url", "")).rstrip("/")
    api_key = str(connection.get("api_key", ""))

    if not url or not api_key:
        raise RuntimeError("Service URL/API key is not configured.")

    return json_get(
        f"{url}{path}",
        headers={
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "User-Agent": f"trailarr-parrk/{APP_VERSION}"
        }
    )


def send_discord(webhook_url, color, title, body):
    if not webhook_url:
        raise RuntimeError("Discord webhook is not configured.")

    payload = json.dumps({
        "embeds": [{
            "title": title,
            "description": body,
            "color": color
        }]
    }).encode()

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"trailarr-parrk/{APP_VERSION}"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def notify_summary(title, success_lines, failure_lines, extra_failure_lines=()):
    """One Discord message for a bulk action. Each category is included only if its
    toggle is on; nothing is sent when both are empty after gating (SPEC 7.3)."""
    ok = list(success_lines) if notify_enabled("success") else []
    bad = (list(failure_lines) + list(extra_failure_lines)) if notify_enabled("failure") else []
    if not ok and not bad:
        return
    notify(3066993 if not bad else 15105570, title, "\n".join(ok + bad))


def notify_enabled(event):
    return event is None or str(cfg(f"notify_{event}")).strip().lower() != "off"


def notify(color, title, body, event=None):
    """Send a Discord embed. `event` ("success" | "failure") is checked against the
    notify_<event> setting; None always sends (tests, summaries that gate themselves)."""
    sink = current_sink()
    if sink and getattr(sink, "suppress_notifications", False):
        return      # batch child: the batch sends one summary instead
    if not notify_enabled(event):
        return
    webhook_url = str(cfg("discord_webhook_url") or "")
    if not webhook_url:
        return

    try:
        send_discord(webhook_url, color, title, body)
    except Exception as e:
        log.warning(f"Discord notification failed: {e}")


# ── TMDB / trailer scoring ────────────────────────────────────────────────

def tmdb_get_with_token(token, path, params=None):
    if not token:
        raise RuntimeError("TMDB API token is not configured.")

    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"https://api.themoviedb.org/3{path}{qs}"

    return json_get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": f"trailarr-parrk/{APP_VERSION}"
        },
        timeout=15
    )


def tmdb_get(path, params=None):
    return tmdb_get_with_token(str(cfg("tmdb_api_key") or ""), path, params)


def tmdb_find_tv(external_id, source):
    """Look up a TMDB show ID by external ID (source: tvdb_id or imdb_id)."""
    try:
        data = tmdb_get(f"/find/{external_id}", {"external_source": source})
    except Exception as e:
        log.warning(f"TMDB lookup by {source} {external_id} failed: {e}")
        return None
    results = data.get("tv_results", [])
    return results[0].get("id") if results else None


def tvdb_to_tmdb(tvdb_id):
    tmdb_id = tmdb_find_tv(tvdb_id, "tvdb_id") if tvdb_id else None
    if not tmdb_id:
        log.error(f"No TMDB match found for tvdbId {tvdb_id}.")
    return tmdb_id


def positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def resolve_tv_tmdb(tmdb_id=None, tvdb_id=None, imdb_id=None):
    """TMDB ID for a Sonarr series.

    Sonarr v4 supplies tmdbId directly (as the original script used). Older
    Sonarr or unmatched series fall back to TMDB's TVDB lookup, then IMDb.
    """
    direct = positive_int(tmdb_id)
    if direct:
        return direct

    if positive_int(tvdb_id):
        found = tmdb_find_tv(tvdb_id, "tvdb_id")
        if found:
            log_step(f"TMDB ID {found} found via TVDB {tvdb_id}.")
            return found

    imdb = str(imdb_id or "").strip()
    if re.fullmatch(r"tt\d+", imdb):
        found = tmdb_find_tv(imdb, "imdb_id")
        if found:
            log_step(f"TMDB ID {found} found via IMDb {imdb}.")
            return found

    log_step(level=logging.ERROR, text=
        f"No TMDB match for series (tmdbId={tmdb_id}, tvdbId={tvdb_id}, imdbId={imdb_id or '-'})."
    )
    return None


def term_in_name(term, name_lower):
    """Substring match, except a term ending in a digit must not be followed
    by another digit: "season 1" matches "Season 1 Trailer" but not
    "Season 12 Trailer"."""
    term = term.strip().lower()
    if not term:
        return False
    if term[-1].isdigit():
        return re.search(re.escape(term) + r"(?!\d)", name_lower) is not None
    return term in name_lower


def score_candidate(video, preferred_terms):
    name = str(video.get("name", ""))
    name_lower = name.lower()
    video_type = str(video.get("type", ""))
    is_official = bool(video.get("official", False))

    score = 0
    matched = []

    for term in preferred_terms:
        matched_term = False
        points = 10

        if term == "official":
            matched_term = is_official or "official" in name_lower
        elif term == "trailer":
            # TMDB type wins over wording in the title. A Teaser named
            # something like "Official Trailer Teaser" must not receive
            # the full-trailer bonus.
            matched_term = video_type == "Trailer"
        elif term == "teaser":
            matched_term = video_type == "Teaser"
            points = 5  # v0.5.2: teasers are deliberately lower priority.
        else:
            matched_term = term_in_name(term, name_lower)

        if matched_term:
            score += points
            matched.append({"term": term, "points": points})

    return score, matched


def tmdb_video_languages(tmdb_id, media_type, details=None):
    """Languages to request from TMDB /videos.

    Without include_video_language TMDB only returns English videos, which
    misses most trailers for anime and other non-English titles. Always ask
    for English, the title's original language and untagged (null) videos.
    """
    languages = ["en"]
    original = str((details or {}).get("original_language") or "").strip().lower()
    if re.fullmatch(r"[a-z]{2}", original) and original not in languages:
        languages.append(original)
    languages.append("null")
    return languages


def tmdb_details(tmdb_id, media_type):
    try:
        return tmdb_get(f"/{media_type}/{tmdb_id}") or {}
    except Exception as e:
        log_step(level=logging.WARNING, text=f"TMDB details lookup failed, using English only: {e}")
        return {}


def youtube_trailers(videos):
    return [
        r for r in videos
        if r.get("site") == "YouTube"
        and r.get("type") in ("Trailer", "Teaser")
    ]


SEASON_FALLBACK_MODES = ("off", "first", "latest")


def season_fallback_mode():
    mode = str(cfg("season_fallback") or "first").strip().lower()
    return mode if mode in SEASON_FALLBACK_MODES else "first"


def tv_fallback_seasons(details, mode=None):
    """Seasons to try when a show has no show-level trailer.

    first:  season 1, then season 2 (spoiler-free; the default).
    latest: latest season, the one before it, then season 1.
    off:    none — report no trailer, as the original script did.
    Specials (season 0) are skipped. At most three lookups per show.
    """
    mode = mode or season_fallback_mode()
    if mode == "off":
        return []
    numbers = sorted(
        int(season.get("season_number"))
        for season in (details.get("seasons") or [])
        if isinstance(season.get("season_number"), int)
        and season.get("season_number") > 0
    )
    if mode == "latest":
        candidates = numbers[-1:] + numbers[-2:-1] + numbers[:1]
    else:
        candidates = numbers[:2]
    ordered = []
    for number in candidates:
        if number not in ordered:
            ordered.append(number)
    return ordered


SPOILER_SEASON_PATTERNS = (
    re.compile(r"\bseason\s*(\d{1,2})\b"),
    re.compile(r"\bseries\s*(\d{1,2})\b"),
    re.compile(r"\bs(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+season\b"),
)
SPOILER_WORDS = ("final season", "last season", "series finale", "final chapter")


def later_season_in_name(name):
    """Season number > 1 mentioned in a show-level trailer title, else 0.

    Show-level TMDB lists often mix in later-season trailers ("Season 8
    Official Trailer"). Those are sorted behind spoiler-free trailers.
    """
    text = str(name or "").lower()
    if any(word in text for word in SPOILER_WORDS):
        return 99
    for pattern in SPOILER_SEASON_PATTERNS:
        for match in pattern.finditer(text):
            number = int(match.group(1))
            if number > 1:
                return number
    return 0


def fetch_and_score(tmdb_id, media_type, info=None):
    info = info if info is not None else {}
    details = tmdb_details(tmdb_id, media_type)
    languages = tmdb_video_languages(tmdb_id, media_type, details)
    info["languages"] = [lang for lang in languages if lang != "null"]
    params = {
        "language": "en-US",
        "include_video_language": ",".join(languages)
    }

    try:
        data = tmdb_get(f"/{media_type}/{tmdb_id}/videos", params)
    except Exception as e:
        log_step(level=logging.ERROR, text=f"TMDB videos request failed: {e}")
        info["error"] = str(e)
        return [], []

    all_videos = data.get("results", [])
    results = youtube_trailers(all_videos)
    info["source"] = "show" if media_type == "tv" else "movie"
    from_season = False

    # Long-running shows often have no show-level trailer on TMDB; the
    # trailers are attached to individual seasons instead.
    if media_type == "tv" and not results:
        checked = []
        for season_number in tv_fallback_seasons(details):
            checked.append(season_number)
            try:
                season_data = tmdb_get(
                    f"/tv/{tmdb_id}/season/{season_number}/videos", params
                )
            except Exception as e:
                log_step(level=logging.WARNING, text=f"TMDB season {season_number} videos failed: {e}")
                continue
            season_videos = season_data.get("results", [])
            all_videos = all_videos + season_videos
            results = youtube_trailers(season_videos)
            if results:
                info["source"] = f"season {season_number}"
                from_season = True
                break
        info["seasons_checked"] = checked

    info["total_videos"] = len(all_videos)
    info["trailer_count"] = len(results)

    log_step(
        f"TMDB returned {len(results)} YouTube trailer/teaser(s) "
        f"of {len(all_videos)} video(s) [{', '.join(info['languages'])}] "
        f"from {info['source']}."
    )

    preferred_terms = cfg_list("preferred_terms")
    excluded_terms = cfg_list("excluded_terms")

    scored = []
    excluded = []

    for video in results:
        name = str(video.get("name", ""))
        key = str(video.get("key", ""))
        name_lower = name.lower()

        matching_exclusions = [term for term in excluded_terms if term in name_lower]
        if matching_exclusions:
            excluded.append({
                "name": name,
                "key": key,
                "type": video.get("type", ""),
                "reason": ", ".join(matching_exclusions)
            })
            continue

        score, matched = score_candidate(video, preferred_terms)
        if score > 0:
            # Spoiler guard: only for a show's own list. Trailers fetched for
            # a specific season are season trailers by design.
            later = (
                later_season_in_name(name)
                if media_type == "tv" and not from_season else 0
            )
            scored.append({
                "score": score,
                "key": key,
                "name": name,
                "type": video.get("type", ""),
                "official": bool(video.get("official", False)),
                "language": video.get("iso_639_1") or "",
                "later_season": later,
                "matched_terms": matched
            })

    # Spoiler-free first, then score; equal scores prefer full trailers,
    # then official, then English. Later-season trailers stay usable when
    # nothing else exists.
    scored.sort(
        key=lambda item: (
            not item.get("later_season"),
            item["score"],
            item.get("type") == "Trailer",
            item.get("official", False),
            item.get("language") == "en"
        ),
        reverse=True
    )

    return scored, excluded


# ── Filesystem / yt-dlp ──────────────────────────────────────────────────

def filename_safe_title(title):
    """Make a title safe for filenames the way Radarr/Sonarr do by default.

    "Avengers: Infinity War" -> "Avengers - Infinity War". Slashes become
    dashes; characters Windows/SMB can't store (* ? " < > |) are dropped."""
    text = str(title)
    text = re.sub(r"\s*:\s+", " - ", text)
    text = text.replace(":", "-")
    text = re.sub(r"\s*[/\\]\s*", "-", text)
    text = re.sub(r'[*?"<>|]', "", text)
    text = re.sub(r"\s{2,}", " ", text).strip().rstrip(".")
    return text or "Trailer"


def trailer_ext():
    """Container for new downloads, as a bare extension: 'mkv' or 'mp4'."""
    value = str(cfg("container") or "mkv").strip().lower()
    return value if value in CONTAINERS else "mkv"


def build_out_path(base_path, template, trailer_folder, title, year):
    name = (
        str(template)
        .replace("{title}", filename_safe_title(title))
        .replace("{year}", str(year))
    )
    if trailer_folder:
        return os.path.join(base_path, trailer_folder, name)
    return os.path.join(base_path, name)


def out_path(base_path, title, year):
    return build_out_path(
        base_path, cfg("filename_template"), str(cfg("trailer_folder") or ""),
        title, year)


def naming_preview(template, trailer_folder, container, title, year):
    """Where a trailer would be saved, relative to the media folder. Raises ValueError."""
    trailer_folder, template = validate_naming(trailer_folder, template)
    container = str(container or trailer_ext()).strip().lower()
    if container not in CONTAINERS:
        raise ValueError("Container must be mkv or mp4.")
    path = build_out_path("", template, trailer_folder, title, year)
    return f"{path}.{container}".replace(os.sep, "/")


def safe_folder_path(folder_path):
    return safe_under_media_root(folder_path)


def media_folder_exists(folder_path):
    try:
        resolved = safe_folder_path(folder_path)
    except (ValueError, TypeError):
        return False
    return os.path.isdir(resolved)


def trailer_path_for_item(item):
    base = safe_folder_path(item["path"])
    return f"{out_path(base, item['title'], item['year'])}.{trailer_ext()}"


# ── Existing-trailer detection ───────────────────────────────────────────
#
# "Missing" means no trailer file at all, not "no file at exactly the
# configured name". A trailer is any video file:
#   - inside a trailers/trailer subfolder (any case) or the configured
#     trailer folder, or
#   - in the media folder itself when its name ends in "trailer"
#     (Plex/Jellyfin style: "-trailer", ".trailer", " trailer", "trailer").

TRAILER_VIDEO_EXTS = (".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm")
TRAILER_DIR_NAMES = {"trailers", "trailer"}
ROOT_TRAILER_STEM = re.compile(r"(?:^|[\s._-])trailer\d*$", re.IGNORECASE)
ROOT_TRAILER_MAX_BYTES = 2 * 1024 ** 3  # never mistake a main movie for a trailer


def is_video_file(name):
    return (
        name.lower().endswith(TRAILER_VIDEO_EXTS)
        and ".trailarr-new-" not in name
        and not name.startswith(".")
    )


def trailer_dirs(folder):
    """Trailer subfolders inside a media folder (case-insensitive)."""
    wanted = set(TRAILER_DIR_NAMES)
    configured = str(cfg("trailer_folder") or "").strip().strip("/")
    if configured and "/" not in configured:
        wanted.add(configured.lower())
    found = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and entry.name.lower() in wanted:
                    found.append(entry.path)
    except OSError:
        pass
    # A nested configured folder ("extras/trailers") is checked directly.
    if configured and "/" in configured:
        nested = os.path.join(folder, configured)
        if os.path.isdir(nested):
            found.append(nested)
    return found


def find_trailer_files(folder):
    """All trailer files for one media folder, sorted by path."""
    files = []
    for directory in trailer_dirs(folder):
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and is_video_file(entry.name):
                        files.append(entry.path)
        except OSError:
            continue
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False) or not is_video_file(entry.name):
                    continue
                stem = os.path.splitext(entry.name)[0]
                if not ROOT_TRAILER_STEM.search(stem):
                    continue
                try:
                    if entry.stat().st_size > ROOT_TRAILER_MAX_BYTES:
                        continue
                except OSError:
                    continue
                files.append(entry.path)
    except OSError:
        pass
    return sorted(set(files))


def target_stem_for(folder, title, year):
    return out_path(folder, title, year)


def matches_naming(path, folder, title, year):
    """True if the file is at the configured name (any video extension)."""
    stem = os.path.splitext(path)[0]
    return stem == target_stem_for(folder, title, year)


def trailer_state(folder, title, year):
    """Classify one media folder's trailers.

    Returns (state, files) where state is missing | ok | mismatched | multiple
    and files is a list of dicts: path, name, size, matches.
    """
    files = []
    for path in find_trailer_files(folder):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        files.append({
            "path": path,
            "name": os.path.relpath(path, folder),
            "size": size,
            "matches": matches_naming(path, folder, title, year)
        })
    if not files:
        return "missing", files
    if len(files) > 1:
        return "multiple", files
    return ("ok" if files[0]["matches"] else "mismatched"), files


def trailer_exists(base_path, title, year):
    """Any trailer file at all, whatever its name."""
    try:
        base_path = safe_folder_path(base_path)
    except ValueError:
        return False
    return bool(find_trailer_files(base_path))


def ytdlp_binary():
    if os.path.isfile(YTDLP_OVERRIDE) and os.access(YTDLP_OVERRIDE, os.X_OK):
        return YTDLP_OVERRIDE
    return "yt-dlp"


def command_version(binary):
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def ytdlp_versions():
    active_binary = ytdlp_binary()
    return {
        "active": command_version(active_binary),
        "bundled": command_version("yt-dlp"),
        "using_override": os.path.realpath(active_binary) == os.path.realpath(YTDLP_OVERRIDE)
        if active_binary != "yt-dlp" else False
    }


def check_latest_ytdlp():
    data = json_get(
        "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"trailarr-parrk/{APP_VERSION}"
        },
        timeout=20
    )
    latest = str(data.get("tag_name", "")).strip()
    if not latest:
        raise RuntimeError("GitHub did not return a yt-dlp release version.")
    return latest


def load_ytdlp_status():
    default = {
        "latest": "",
        "last_checked": "",
        "last_attempted": "",
        "last_error": ""
    }

    with YTDLP_STATUS_LOCK:
        try:
            with open(YTDLP_STATUS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                default.update({
                    key: str(saved.get(key, default[key]) or "")
                    for key in default
                })
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning(f"Could not load yt-dlp update status: {e}")

    return default


def save_ytdlp_status(status):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    temp_path = f"{YTDLP_STATUS_FILE}.tmp"

    with YTDLP_STATUS_LOCK:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
            f.write("\n")

        os.chmod(temp_path, 0o600)
        os.replace(temp_path, YTDLP_STATUS_FILE)

        try:
            os.chmod(YTDLP_STATUS_FILE, 0o600)
        except OSError:
            pass


def ytdlp_check_is_due(status=None):
    status = status or load_ytdlp_status()
    stamp = status.get("last_attempted") or status.get("last_checked")
    if not stamp:
        return True

    try:
        checked = dt.datetime.fromisoformat(stamp)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return True

    age = dt.datetime.now(dt.timezone.utc) - checked.astimezone(dt.timezone.utc)
    return age.total_seconds() >= YTDLP_CHECK_INTERVAL_SECONDS


def check_and_store_latest_ytdlp():
    status = load_ytdlp_status()
    attempted = utc_now()

    try:
        latest = check_latest_ytdlp()
    except Exception as e:
        status.update({
            "last_attempted": attempted,
            "last_error": str(e)
        })
        save_ytdlp_status(status)
        raise

    status.update({
        "latest": latest,
        "last_checked": attempted,
        "last_attempted": attempted,
        "last_error": ""
    })
    save_ytdlp_status(status)
    return latest


def ytdlp_ui_status():
    versions = ytdlp_versions()
    status = load_ytdlp_status()
    latest = status.get("latest", "")

    return {
        **versions,
        **status,
        "up_to_date": bool(latest) and versions.get("active") == latest
    }


def ytdlp_update_monitor():
    # Small startup delay keeps container startup independent from GitHub.
    time.sleep(5)

    while True:
        try:
            status = load_ytdlp_status()
            if ytdlp_check_is_due(status):
                latest = check_and_store_latest_ytdlp()
                log.info(f"Automatic yt-dlp update check: latest is {latest}.")
        except Exception as e:
            log.warning(f"Automatic yt-dlp update check failed: {e}")

        time.sleep(YTDLP_MONITOR_INTERVAL_SECONDS)


def start_background_jobs():
    global BACKGROUND_JOBS_STARTED

    with BACKGROUND_JOBS_LOCK:
        if BACKGROUND_JOBS_STARTED:
            return
        BACKGROUND_JOBS_STARTED = True

    thread = threading.Thread(
        target=ytdlp_update_monitor,
        name="yt-dlp-update-monitor",
        daemon=True
    )
    thread.start()

    watcher = threading.Thread(
        target=arr_watch_monitor,
        name="arr-watcher",
        daemon=True
    )
    watcher.start()

    threading.Thread(
        target=maintenance_monitor,
        name="maintenance",
        daemon=True
    ).start()


def update_ytdlp_override():
    latest = check_and_store_latest_ytdlp()
    base = f"https://github.com/yt-dlp/yt-dlp/releases/download/{latest}"

    req = urllib.request.Request(
        f"{base}/SHA2-256SUMS",
        headers={"User-Agent": f"trailarr-parrk/{APP_VERSION}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        sums_text = resp.read().decode("utf-8", errors="replace")

    expected = None
    for line in sums_text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip("*").strip() == "yt-dlp":
            expected = parts[0].strip().lower()
            break

    if not expected:
        raise RuntimeError("Could not find yt-dlp checksum in SHA2-256SUMS.")

    req = urllib.request.Request(
        f"{base}/yt-dlp",
        headers={"User-Agent": f"trailarr-parrk/{APP_VERSION}"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        binary_data = resp.read()

    actual = hashlib.sha256(binary_data).hexdigest().lower()
    if actual != expected:
        raise RuntimeError("yt-dlp checksum verification failed.")

    target_dir = os.path.dirname(YTDLP_OVERRIDE)
    os.makedirs(target_dir, exist_ok=True)
    temp_path = f"{YTDLP_OVERRIDE}.tmp"

    with open(temp_path, "wb") as f:
        f.write(binary_data)
    os.chmod(temp_path, 0o755)

    version = command_version(temp_path)
    if version == "unknown":
        os.remove(temp_path)
        raise RuntimeError("Downloaded yt-dlp binary could not be executed.")

    os.replace(temp_path, YTDLP_OVERRIDE)
    os.chmod(YTDLP_OVERRIDE, 0o755)

    record_activity({
        "status": "success",
        "action": "yt-dlp update",
        "source": "Settings",
        "title": "yt-dlp",
        "detail": f"Updated persistent yt-dlp to {version}."
    })

    return version


def max_concurrent_downloads():
    try:
        return max(1, min(4, int(str(cfg("max_concurrent_downloads")))))
    except (TypeError, ValueError):
        return 1


# ── Job output sink (SPEC section 5) ─────────────────────────────────────
#
# The job runner (jobs.py) binds a sink to the worker thread. engine.py never
# imports jobs.py; it only calls log_step(), which behaves like log.info()
# when nothing is bound (CLI, watcher). A sink offers:
#   line(stream, text)      record one output line
#   is_cancelled() -> bool  cooperative cancel check
#   attach_process(proc)    lets cancel() terminate yt-dlp (None to detach)
#   set_waiting(bool)       True while waiting for a download slot

_job_local = threading.local()
PROGRESS_RE = re.compile(r"^\[download\]\s+(\d+(?:\.\d+)?)%")


def bind_sink(sink):
    _job_local.sink = sink


def current_sink():
    return getattr(_job_local, "sink", None)


def job_cancelled():
    sink = current_sink()
    return bool(sink and sink.is_cancelled())


def log_step(text, stream="app", level=logging.INFO):
    """Log to the container log and, inside a job, to the job's output."""
    text = str(text).rstrip()
    if not text:
        return
    if not (stream == "yt-dlp" and PROGRESS_RE.match(text)):
        log.log(level, text)
    sink = current_sink()
    if sink:
        sink.line(stream, text)


class JobCancelled(Exception):
    """Raised inside a job when the user cancelled it."""


@contextlib.contextmanager
def acquire_download_slot():
    """Cross-process limiter shared by web requests, batch workers and CLI."""

    os.makedirs(DOWNLOAD_SLOT_DIR, exist_ok=True)
    announced = False

    while True:
        slots = max_concurrent_downloads()

        for slot in range(slots):
            path = os.path.join(DOWNLOAD_SLOT_DIR, f"slot-{slot}.lock")
            file_obj = open(path, "a+", encoding="utf-8")

            try:
                fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                file_obj.close()
                continue

            sink = current_sink()
            if sink:
                sink.set_waiting(False)
            try:
                yield slot
            finally:
                fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
                file_obj.close()
            return

        if not announced:
            announced = True
            log_step("Waiting for a download slot…")
            sink = current_sink()
            if sink:
                sink.set_waiting(True)
        if job_cancelled():
            raise JobCancelled()
        time.sleep(0.25)


def cleanup_temp_files(temp_base):
    for path in glob.glob(f"{glob.escape(temp_base)}.*"):
        try:
            os.remove(path)
        except OSError:
            pass


DOWNLOAD_TIMEOUT_SECONDS = 900


def format_selector(height, ext):
    """yt-dlp -f expression. mp4 prefers H.264 + AAC so players that choke on
    VP9/AV1-in-mp4 still work; above 1080p YouTube has no H.264, so it falls through."""
    if ext == "mp4":
        return (
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/best"
        )
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/best"
    )


def download(yt_id, out_path_noext):
    """Download atomically. Existing trailer stays in place until success."""

    directory = os.path.dirname(out_path_noext)
    os.makedirs(directory, exist_ok=True)

    ext = trailer_ext()
    target_path = f"{out_path_noext}.{ext}"
    unique = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:6]}"
    temp_base = f"{out_path_noext}.trailarr-new-{unique}"
    cleanup_temp_files(temp_base)

    video_quality = str(cfg("video_quality"))
    cmd = [
        ytdlp_binary(),
        "-f",
        format_selector(video_quality, ext),
        "--merge-output-format",
        ext,
        "--no-playlist",
        "--newline",
        "-o",
        f"{temp_base}.%(ext)s",
        f"https://www.youtube.com/watch?v={yt_id}"
    ]

    started = time.monotonic()
    collected = deque(maxlen=400)   # tail kept for error classification
    timed_out = threading.Event()
    returncode = None

    def elapsed():
        return round(time.monotonic() - started, 1)

    def cancelled_result():
        cleanup_temp_files(temp_base)
        return {"ok": False, "cancelled": True, "duration": elapsed(),
                "error": "Cancelled."}

    try:
        with acquire_download_slot():
            if job_cancelled():
                return cancelled_result()
            log_step(f"Downloading https://www.youtube.com/watch?v={yt_id}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                errors="replace"
            )
            sink = current_sink()
            if sink:
                sink.attach_process(proc)

            def on_timeout():
                timed_out.set()
                try:
                    proc.kill()
                except OSError:
                    pass

            watchdog = threading.Timer(DOWNLOAD_TIMEOUT_SECONDS, on_timeout)
            watchdog.daemon = True
            watchdog.start()
            try:
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if not line:
                        continue
                    if not PROGRESS_RE.match(line):
                        collected.append(line + "\n")
                    log_step(line, stream="yt-dlp")
                    if timed_out.is_set():
                        break
                returncode = proc.wait()
            finally:
                watchdog.cancel()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if sink:
                    sink.attach_process(None)
    except JobCancelled:
        return cancelled_result()
    except OSError as e:
        cleanup_temp_files(temp_base)
        return {"ok": False, "duration": elapsed(), "error": f"Could not start yt-dlp: {e}"}

    duration = elapsed()

    if job_cancelled():
        return cancelled_result()

    if timed_out.is_set():
        cleanup_temp_files(temp_base)
        error = f"yt-dlp timed out after {DOWNLOAD_TIMEOUT_SECONDS} seconds."
        return {"ok": False, "duration": duration, "error": error}

    if returncode != 0:
        error = ("".join(collected) or "yt-dlp failed.").strip()
        cleanup_temp_files(temp_base)
        return {"ok": False, "duration": duration, "error": error[-3000:]}

    candidates = [
        path for path in glob.glob(f"{glob.escape(temp_base)}.*")
        if os.path.isfile(path)
    ]
    preferred = [path for path in candidates if path.lower().endswith(f".{ext}")]
    new_file = preferred[0] if preferred else (candidates[0] if candidates else None)

    if not new_file or os.path.getsize(new_file) <= 0:
        cleanup_temp_files(temp_base)
        return {
            "ok": False,
            "duration": duration,
            "error": "yt-dlp reported success but no output file was found."
        }

    # Replace only the expected trailer target. Never delete unrelated MKV
    # files from the directory (important if TRAILER_FOLDER is blank or the
    # user keeps other extras beside the trailer). os.replace() is atomic on
    # the same filesystem, so the previous trailer remains until this point.
    os.replace(new_file, target_path)
    cleanup_temp_files(temp_base)

    return {"ok": True, "duration": duration, "error": "", "path": target_path}


# ── Arr library model ─────────────────────────────────────────────────────

def normalize_radarr(movie, connection):
    return {
        "source": "radarr",
        "connection_id": connection.get("id"),
        "connection_name": connection.get("name"),
        "id": movie.get("id"),
        "title": movie.get("title", "Unknown"),
        "year": movie.get("year", ""),
        "path": movie.get("path", ""),
        "root_folder": movie.get("rootFolderPath") or "",
        "tmdb_id": movie.get("tmdbId"),
        "tvdb_id": None,
        "monitored": movie.get("monitored", True),
        "has_media": bool(movie.get("hasFile", False))
    }


def normalize_sonarr(series, connection):
    return {
        "source": "sonarr",
        "connection_id": connection.get("id"),
        "connection_name": connection.get("name"),
        "id": series.get("id"),
        "title": series.get("title", "Unknown"),
        "year": series.get("year", ""),
        "path": series.get("path", ""),
        "root_folder": series.get("rootFolderPath") or "",
        "tmdb_id": positive_int(series.get("tmdbId")),
        "tvdb_id": series.get("tvdbId"),
        "imdb_id": series.get("imdbId") or "",
        "monitored": series.get("monitored", True),
        "has_media": True
    }


def load_connection_items(connection):
    source = connection.get("type")

    if not connection.get("api_key"):
        return [], "Not configured"

    try:
        if source == "radarr":
            data = arr_get(connection, "/api/v3/movie")
            return [normalize_radarr(movie, connection) for movie in data], None

        if source == "sonarr":
            data = arr_get(connection, "/api/v3/series")
            return [normalize_sonarr(series, connection) for series in data], None

        return [], "Unknown source"

    except Exception as e:
        log.warning(f"{connection.get('name', source)} API failed: {e}")
        return [], str(e)


def get_connection_item(connection, item_id):
    item_id = int(item_id)
    source = connection.get("type")

    if source == "radarr":
        data = arr_get(connection, f"/api/v3/movie/{item_id}")
        return normalize_radarr(data, connection)

    if source == "sonarr":
        data = arr_get(connection, f"/api/v3/series/{item_id}")
        return normalize_sonarr(data, connection)

    raise ValueError("Unknown source.")


def item_is_usable(item):
    if not media_folder_exists(item.get("path", "")):
        return False
    if item.get("source") == "radarr" and not item.get("has_media"):
        return False
    return True


def path_matches_library(item_path, library):
    root_path = str(library.get("root_path", "") or "").strip()
    if not root_path:
        return True

    try:
        item_resolved = safe_folder_path(item_path)
        root_resolved = safe_folder_path(root_path)
    except ValueError:
        return False

    return (
        item_resolved == root_resolved
        or item_resolved.startswith(root_resolved + os.sep)
    )


def library_owns_item(library, item_path):
    """Assign an item to the most specific library root on one Arr connection.

    A blank root acts as the catch-all only when no more specific library root
    on the same connection matches the item. This lets one Radarr/Sonarr feed
    Movies + Anime Movies, TV + Anime TV, etc. without duplicate rows.
    """

    same_connection = [
        lib for lib in get_libraries()
        if lib.get("connection_id") == library.get("connection_id")
    ]

    specific_matches = [
        lib for lib in same_connection
        if str(lib.get("root_path", "") or "").strip()
        and path_matches_library(item_path, lib)
    ]

    if specific_matches:
        specific_matches.sort(
            key=lambda lib: len(str(lib.get("root_path", "") or "")),
            reverse=True
        )
        return specific_matches[0].get("id") == library.get("id")

    return not str(library.get("root_path", "") or "").strip()


def decorate_item(item, metadata_map=None):
    item = dict(item)
    folder = safe_folder_path(item["path"])
    state, files = trailer_state(folder, item["title"], item["year"])
    metadata_map = metadata_map or {}

    for file in files:
        file["size_label"] = human_size(file["size"])
        file["metadata"] = metadata_map.get(os.path.realpath(file["path"]))

    primary = next((f for f in files if f["matches"]), files[0] if files else None)
    item["trailer_state"] = state
    item["trailer_files"] = files
    item["missing"] = state == "missing"
    item["trailer_path"] = primary["path"] if primary else trailer_path_for_item(item)
    item["metadata"] = primary["metadata"] if primary else None
    item["target_name"] = os.path.relpath(
        f"{target_stem_for(folder, item['title'], item['year'])}.{trailer_ext()}", folder
    )
    return item


def human_size(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024


def load_library_items(library_id):
    library = get_library(library_id)
    if not library:
        raise ValueError("Library not found.")

    connection = get_connection(library.get("connection_id"))
    if not connection:
        return library, [], "Arr connection not found"

    raw_items, error = load_connection_items(connection)
    metadata_map = load_trailer_metadata()
    items = []

    for item in raw_items:
        if not item_is_usable(item):
            continue
        if not library_owns_item(library, item.get("path", "")):
            continue
        try:
            decorated = decorate_item(item, metadata_map)
        except ValueError:
            continue
        decorated["library_id"] = library["id"]
        decorated["library_name"] = library["name"]
        items.append(decorated)

    items.sort(key=lambda x: (str(x.get("title", "")).lower(), str(x.get("year", ""))))
    return library, items, error


def load_library_views(library_id):
    library, items, error = load_library_items(library_id)
    missing = [item for item in items if item["missing"]]
    existing = [item for item in items if not item["missing"]]
    return library, missing, existing, error


# ── Existing-trailer actions ─────────────────────────────────────────────

def owned_item(library_id, item_id):
    """Load an item and confirm it belongs to the library. Raises ValueError."""
    library = get_library(library_id)
    if not library:
        raise ValueError("Library not found.")
    connection = get_connection(library.get("connection_id"))
    if not connection:
        raise ValueError("Arr connection not found.")
    item = get_connection_item(connection, item_id)
    if not item_is_usable(item) or not library_owns_item(library, item.get("path", "")):
        raise ValueError("Title is not in this library or has no media folder.")
    return library, item, safe_folder_path(item["path"])


def detected_file(folder, path):
    """Return the detected trailer path matching `path`, or raise.

    Only files Trailarr itself detected as trailers can be acted on, so a
    crafted form can never touch the main media file or anything else."""
    wanted = os.path.realpath(str(path or ""))
    for candidate in find_trailer_files(folder):
        if os.path.realpath(candidate) == wanted:
            return candidate
    raise ValueError("That file is not a detected trailer for this title.")


def remove_empty_trailer_dir(directory, folder):
    if (
        os.path.dirname(directory) == folder
        and os.path.basename(directory).lower() in TRAILER_DIR_NAMES | {str(cfg("trailer_folder") or "").lower()}
    ):
        try:
            if not os.listdir(directory):
                os.rmdir(directory)
        except OSError:
            pass


def move_trailer_metadata(old_path, new_path):
    data = load_trailer_metadata()
    entry = data.get(os.path.realpath(old_path))
    if entry is not None:
        update_trailer_metadata(old_path, remove=True)
        update_trailer_metadata(new_path, entry)


def rename_trailer_to_naming(folder, title, year, path):
    """Move one trailer to the configured name, keeping its extension.

    Returns the new path. Never overwrites an existing file."""
    source = detected_file(folder, path)
    ext = os.path.splitext(source)[1].lower() or ".mkv"
    target = f"{target_stem_for(folder, title, year)}{ext}"
    if os.path.realpath(source) == os.path.realpath(target):
        return target
    if os.path.exists(target):
        raise ValueError(f"A file already exists at {os.path.relpath(target, folder)}.")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(source, target)
    move_trailer_metadata(source, target)
    remove_empty_trailer_dir(os.path.dirname(source), folder)
    return target


def delete_trailer_files(folder, paths):
    removed = []
    for path in paths:
        source = detected_file(folder, path)
        os.remove(source)
        update_trailer_metadata(source, remove=True)
        remove_empty_trailer_dir(os.path.dirname(source), folder)
        removed.append(os.path.relpath(source, folder))
    return removed


def remove_other_trailers(folder, keep_path):
    """After a successful download: remove every other detected trailer."""
    keep = os.path.realpath(keep_path)
    others = [p for p in find_trailer_files(folder) if os.path.realpath(p) != keep]
    try:
        return delete_trailer_files(folder, others)
    except Exception as e:
        log.warning(f"Could not remove old trailer files in {folder}: {e}")
        return []


# Connection-keyed variants for API v1 (no library involved). `item` is a normalized Arr item.

def _item_context(item):
    return context_for_item(item, None, "Web UI")


def item_folder(connection_id, item_id):
    """Returns (item, folder). Raises ValueError if the title has no media folder."""
    connection = get_connection(connection_id)
    if not connection:
        raise ValueError("Arr connection not found.")
    item = get_connection_item(connection, item_id)
    if not item_is_usable(item):
        raise ValueError("Title has no media folder.")
    return item, safe_folder_path(item["path"])


def _resolve_in_folder(folder, rel_path):
    return os.path.join(folder, str(rel_path or ""))


def rename_item_file(connection_id, item_id, rel_path):
    item, folder = item_folder(connection_id, item_id)
    source = detected_file(folder, _resolve_in_folder(folder, rel_path))
    new_path = rename_trailer_to_naming(folder, item["title"], item["year"], source)
    record_activity({
        **_item_context(item),
        "status": "success", "action": "rename",
        "title": item["title"], "year": item["year"],
        "detail": f"Renamed {os.path.relpath(source, folder)} → {os.path.relpath(new_path, folder)}"
    })
    return new_path


def keep_item_file(connection_id, item_id, rel_path):
    item, folder = item_folder(connection_id, item_id)
    keep = detected_file(folder, _resolve_in_folder(folder, rel_path))
    others = [p for p in find_trailer_files(folder)
              if os.path.realpath(p) != os.path.realpath(keep)]
    removed = delete_trailer_files(folder, others)
    record_activity({
        **_item_context(item),
        "status": "success", "action": "delete",
        "title": item["title"], "year": item["year"],
        "detail": f"Kept {os.path.relpath(keep, folder)}; removed {', '.join(removed) or 'nothing'}."
    })
    return keep, removed


def delete_item_file(connection_id, item_id, rel_path):
    item, folder = item_folder(connection_id, item_id)
    source = detected_file(folder, _resolve_in_folder(folder, rel_path))
    removed = delete_trailer_files(folder, [source])
    record_activity({
        **_item_context(item),
        "status": "success", "action": "delete",
        "title": item["title"], "year": item["year"],
        "detail": f"Deleted {', '.join(removed)}."
    })
    return removed


def rename_all(snaps, scope, dry_run=False):
    """Rename every single-file title whose file is not at the configured name.

    `snaps` are cache snapshots (connection_id, id, title, year, folder, ...). Titles with
    several trailer files are skipped, never guessed at. Returns
    {"renamed": [...], "skipped": [...]} or, for dry_run, {"ready": [...], "blocked": [...]}.
    Each entry: {connection_id, id, title, year, from, to, reason?}."""
    ready, blocked, renamed = [], [], []
    for snap in snaps:
        if not snap.get("name_differs"):
            continue
        entry = {"connection_id": snap["connection_id"], "id": snap["id"],
                 "title": snap["title"], "year": snap["year"]}
        try:
            folder = safe_folder_path(snap["folder"])
            files = find_trailer_files(folder)
            if len(files) != 1:
                raise ValueError(
                    "Multiple trailer files; review them on the title." if files
                    else "No trailer file found.")
            source = files[0]
            if matches_naming(source, folder, snap["title"], snap["year"]):
                continue
            ext = os.path.splitext(source)[1].lower() or f".{trailer_ext()}"
            target = f"{target_stem_for(folder, snap['title'], snap['year'])}{ext}"
            entry["from"] = os.path.relpath(source, folder)
            entry["to"] = os.path.relpath(target, folder)
            if os.path.exists(target):
                raise ValueError(f"A file already exists at {entry['to']}.")
            if not dry_run:
                rename_trailer_to_naming(folder, snap["title"], snap["year"], source)
                renamed.append(entry)
            else:
                ready.append(entry)
        except Exception as e:      # noqa: BLE001
            blocked.append({**entry, "reason": str(e)})
    if dry_run:
        return {"ready": ready, "blocked": blocked}
    if renamed or blocked:
        record_activity({
            "source": "Web UI", "status": "success" if not blocked else "warning",
            "action": "rename", "title": f"{scope}: rename to current naming", "year": "",
            "detail": f"Renamed {len(renamed)} trailer(s)."
            + (f" Skipped {len(blocked)}: "
               + "; ".join(f"{b['title']}: {b['reason']}" for b in blocked[:10]) if blocked else "")
        })
        notify_summary(
            f"Rename — {scope}",
            [f"Renamed {len(renamed)} trailer(s)."] if renamed else [],
            [f"Skipped {len(blocked)} (multiple files or name taken)."] if blocked else [])
    return {"renamed": renamed, "skipped": blocked}


def rename_library_item_trailer(library_id, item_id, path):
    library, item, folder = owned_item(library_id, item_id)
    new_path = rename_trailer_to_naming(folder, item["title"], item["year"], path)
    record_activity({
        **context_for_item(item, library, "Web UI"),
        "status": "success",
        "action": "rename",
        "title": item["title"],
        "year": item["year"],
        "detail": f"Renamed {os.path.relpath(path, folder)} → {os.path.relpath(new_path, folder)}"
    })
    return new_path


def keep_only_library_trailer(library_id, item_id, keep_path):
    library, item, folder = owned_item(library_id, item_id)
    keep = detected_file(folder, keep_path)
    others = [p for p in find_trailer_files(folder) if os.path.realpath(p) != os.path.realpath(keep)]
    removed = delete_trailer_files(folder, others)
    record_activity({
        **context_for_item(item, library, "Web UI"),
        "status": "success",
        "action": "delete",
        "title": item["title"],
        "year": item["year"],
        "detail": f"Kept {os.path.relpath(keep, folder)}; removed {', '.join(removed) or 'nothing'}."
    })
    return keep, removed


def rename_all_in_library(library_id):
    """Rename every single, mismatched trailer in a library to the naming.

    Titles with several trailer files are left for manual review."""
    library, _missing, existing, _error = load_library_views(library_id)
    renamed, skipped = 0, []
    for item in existing:
        if item["trailer_state"] != "mismatched":
            continue
        folder = safe_folder_path(item["path"])
        try:
            rename_trailer_to_naming(folder, item["title"], item["year"], item["trailer_files"][0]["path"])
            renamed += 1
        except Exception as e:
            skipped.append(f"{item['title']}: {e}")
    if renamed or skipped:
        record_activity({
            "source": "Web UI",
            "library_id": library_id,
            "library": library.get("name", ""),
            "status": "success" if not skipped else "warning",
            "action": "rename",
            "title": f"{library.get('name', 'Library')}: rename to current naming",
            "year": "",
            "detail": (
                f"Renamed {renamed} trailer(s)."
                + (f" Skipped {len(skipped)}: " + "; ".join(skipped[:10]) if skipped else "")
            )
        })
    return renamed, skipped


def all_missing_items():
    result = []
    seen = set()

    for library in get_libraries():
        try:
            _, missing, _, _ = load_library_views(library["id"])
        except Exception as e:
            log.warning(f"Could not load {library.get('name')}: {e}")
            continue

        for item in missing:
            key = (item.get("connection_id"), item.get("id"))
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "library_id": library["id"],
                "item_id": item["id"],
                "label": f"{item['title']} ({item['year']})",
                "library_name": library["name"]
            })

    return result


def library_missing_tasks(library_id):
    library, missing, _, _ = load_library_views(library_id)
    return [
        {
            "library_id": library_id,
            "item_id": item["id"],
            "label": f"{item['title']} ({item['year']})",
            "library_name": library["name"]
        }
        for item in missing
    ]


def context_for_item(item, library=None, trigger="Web UI"):
    return {
        "source": trigger,
        "library_id": library.get("id") if library else "",
        "library": library.get("name") if library else "",
        "arr_type": item.get("source", ""),
        "connection_id": item.get("connection_id", ""),
        "connection": item.get("connection_name", ""),
        "item_id": item.get("id")
    }


# ── Core grab logic ──────────────────────────────────────────────────────

# ── YouTube search fallback ──────────────────────────────────────────────
#
# Used only when TMDB has no usable trailer, or every TMDB trailer is
# unavailable. Results must pass strict filters, because YouTube search is
# far noisier than TMDB's curated list.

SEARCH_RESULTS = 15
SEARCH_MIN_SECONDS = 20
SEARCH_MAX_SECONDS = 300
SEARCH_REQUIRED_WORDS = ("trailer", "teaser", "promo")
SEARCH_JUNK_TERMS = (
    "reaction", "review", "recap", "explained", "breakdown", "theory",
    "theories", "fan made", "fanmade", "fan-made", "concept", "parody",
    "full episode", "episode", "ending", "scene", "clip", "music video",
    "soundtrack", "ost", "compilation", "best moments", "behind the scenes",
    "interview", "honest trailer", "pitch meeting", "everything wrong",
    "easter eggs", "re-cut", "recut", "remake", "ai generated", "ai trailer",
    "4k remaster", "edit", "tribute", "vs", "comparison", "1 hour", "10 hours",
    "lyrics", "podcast", "live stream", "livestream", "shorts"
)
TITLE_STOPWORDS = {"the", "a", "an", "and", "of", "in", "on", "at", "to", "for", "&"}


def youtube_search_enabled():
    return str(cfg("youtube_search") or "off").strip().lower() == "on"


def normalize_words(text):
    text = str(text or "").lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return [word for word in text.split() if word]


def significant_title_words(title):
    words = [w for w in normalize_words(title) if w not in TITLE_STOPWORDS]
    # Very short titles ("It", "Up") keep all words so they still match.
    return words or normalize_words(title)


def title_matches(title, video_title):
    wanted = significant_title_words(title)
    have = set(normalize_words(video_title))
    return bool(wanted) and all(word in have for word in wanted)


def junk_term_in(name_lower):
    for term in SEARCH_JUNK_TERMS:
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", name_lower):
            return term
    return ""


def wrong_year_in(name, year_text, title=""):
    """A 4-digit year in the video title more than a year from ours, else ''.

    Catches remakes and reboots that share a title ("Avatar: The Last
    Airbender (2024)" when looking for the 2005 series)."""
    try:
        ours = int(year_text)
    except (TypeError, ValueError):
        return ""
    own_numbers = set(re.findall(r"\d+", str(title)))  # "Blade Runner 2049", "1917"
    for match in re.finditer(r"(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)", str(name)):
        if match.group(1) in own_numbers:
            continue
        if abs(int(match.group(1)) - ours) > 1:
            return match.group(1)
    return ""


def run_ytdlp_search(query, count=SEARCH_RESULTS):
    """Return YouTube search entries (metadata only, nothing downloaded)."""
    cmd = [
        ytdlp_binary(),
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        f"ytsearch{count}:{query}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise RuntimeError("YouTube search timed out.")
    if result.returncode != 0:
        raise RuntimeError(short_ytdlp_error(result.stderr or "YouTube search failed."))
    data = json.loads(result.stdout or "{}")
    return [e for e in (data.get("entries") or []) if isinstance(e, dict)]


def youtube_search_candidates(title, year, media_type, info=None, exclude_keys=()):
    info = info if info is not None else {}
    query = f"{title} {year} trailer".strip()
    info["search_query"] = query
    try:
        entries = run_ytdlp_search(query)
    except Exception as e:
        log_step(level=logging.WARNING, text=f"YouTube search failed for '{query}': {e}")
        info["search_error"] = str(e)
        return []

    preferred_terms = cfg_list("preferred_terms")
    excluded_terms = cfg_list("excluded_terms")
    year_text = str(year or "")
    candidates = []
    rejected = 0

    for entry in entries:
        key = str(entry.get("id") or "")
        name = str(entry.get("title") or "")
        name_lower = name.lower()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", key) or key in exclude_keys:
            continue

        duration = entry.get("duration")
        reasons = []
        if not title_matches(title, name):
            reasons.append("title mismatch")
        if not any(word in name_lower for word in SEARCH_REQUIRED_WORDS):
            reasons.append("not a trailer")
        if isinstance(duration, (int, float)) and not (
            SEARCH_MIN_SECONDS <= duration <= SEARCH_MAX_SECONDS
        ):
            reasons.append(f"duration {int(duration)}s")
        junk = junk_term_in(name_lower)
        if junk:
            reasons.append(f"junk term '{junk}'")
        other_year = wrong_year_in(name, year_text, title)
        if other_year:
            reasons.append(f"different year {other_year}")
        excluded_hit = [t for t in excluded_terms if t and t in name_lower]
        if excluded_hit:
            reasons.append(f"excluded '{excluded_hit[0]}'")
        if reasons:
            rejected += 1
            continue

        video_type = (
            "Trailer" if "trailer" in name_lower
            else "Teaser" if "teaser" in name_lower
            else ""
        )
        verified = bool(entry.get("channel_is_verified"))
        score, matched = score_candidate(
            {"name": name, "type": video_type, "official": verified},
            preferred_terms
        )
        if score <= 0:
            rejected += 1
            continue

        candidates.append({
            "score": score,
            "key": key,
            "name": name,
            "type": video_type,
            "official": verified or "official" in name_lower,
            "language": "",
            "later_season": later_season_in_name(name) if media_type == "tv" else 0,
            "matched_terms": matched,
            "via_search": True,
            "channel": str(entry.get("channel") or entry.get("uploader") or ""),
            "has_year": bool(year_text) and year_text in name,
            "views": int(entry.get("view_count") or 0)
        })

    # The right year in the title beats everything else: it separates the
    # original from a same-name remake. Then spoiler-free, score, official
    # channel and views.
    candidates.sort(
        key=lambda c: (
            c["has_year"],
            not c["later_season"],
            c["score"],
            c["official"],
            c["views"]
        ),
        reverse=True
    )
    info["search_found"] = len(candidates)
    info["search_rejected"] = rejected
    log_step(
        f"YouTube search '{query}': {len(candidates)} usable of {len(entries)} "
        f"result(s), {rejected} rejected."
    )
    return candidates


# yt-dlp errors that mean "this particular video can't be had", so the next
# TMDB candidate is worth trying. Anything else (bot checks, network, timeouts,
# yt-dlp breakage) would fail the same way for every candidate.
VIDEO_GONE_PATTERNS = (
    "video unavailable",
    "this video is unavailable",
    "is not available",
    "not available in your country",
    "uploader has not made this video available",
    "blocked it in your country",
    "private video",
    "video has been removed",
    "account associated with this video has been terminated",
    "copyright",
    "sign in to confirm your age",
    "age-restricted",
    "members-only",
    "join this channel",
    "premieres in",
    "this live event will begin",
)
MAX_CANDIDATE_ATTEMPTS = 5


def video_is_gone(error):
    text = str(error or "").lower()
    if "confirm you're not a bot" in text or "confirm you’re not a bot" in text:
        return False
    return any(pattern in text for pattern in VIDEO_GONE_PATTERNS)


def short_ytdlp_error(error):
    lines = [line.strip() for line in str(error or "").splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR")]
    return (errors[-1] if errors else (lines[-1] if lines else "yt-dlp failed."))[:300]


def try_candidates(candidates, out, attempts):
    """Download the first available candidate. Returns (result, best)."""
    result, best = None, None
    for candidate in candidates[:MAX_CANDIDATE_ATTEMPTS]:
        best = candidate
        log_step(f"Trying {candidate['name']} ({candidate['key']})")
        result = download(candidate["key"], out)
        if result.get("cancelled"):
            break
        attempts.append({
            "key": candidate["key"],
            "name": candidate["name"],
            "via_search": bool(candidate.get("via_search")),
            "ok": result["ok"],
            "error": "" if result["ok"] else short_ytdlp_error(result["error"])
        })
        if result["ok"] or not video_is_gone(result["error"]):
            break
        log_step(f"  {candidate['key']} unavailable, trying next candidate.")
    return result, best


def handle_grab(title, year, tmdb_id, media_type, folder_path, dry_run=False,
                context=None, skip_existing=False, replace_others=False):
    context = context or {}
    log_step(
        f"{title} ({year}) — TMDB {tmdb_id}"
        + (" [DRY RUN]" if dry_run else "")
    )

    try:
        folder_path = safe_folder_path(folder_path)
    except ValueError as e:
        return {"status": "rejected", "reason": str(e)}, 400

    # Never create the media folder itself. If the Arr hasn't imported
    # anything yet, writing here would create an orphan folder (owned by the
    # container user) that the Arr may later fail to import into or ignore.
    if not os.path.isdir(folder_path):
        log_step(f"Media folder does not exist yet, skipping: {folder_path}")
        return {"status": "folder_missing", "folder": folder_path}, 200

    if skip_existing and trailer_exists(folder_path, title, year):
        log_step(f"Trailer already exists, skipping: {title} ({year})")
        return {"status": "exists"}, 200

    fetch_info = {}
    search_info = {}
    scored, excluded = fetch_and_score(tmdb_id, media_type, fetch_info)
    searched = False

    if not scored and youtube_search_enabled() and not fetch_info.get("error"):
        scored = youtube_search_candidates(title, year, media_type, search_info)
        searched = True

    if not scored:
        langs = ", ".join(fetch_info.get("languages", ["en"]))
        if fetch_info.get("error"):
            reason = f"TMDB request failed: {fetch_info['error']}"
        elif not fetch_info.get("trailer_count"):
            seasons = fetch_info.get("seasons_checked") or []
            season_note = (
                f"; also checked season{'s' if len(seasons) > 1 else ''} "
                f"{', '.join(str(n) for n in seasons)}"
                if seasons else ""
            )
            reason = (
                f"TMDB lists no YouTube trailers or teasers for this title "
                f"(languages checked: {langs}{season_note})."
            )
        else:
            reason = (
                f"TMDB has {fetch_info['trailer_count']} trailer/teaser(s), "
                f"but none passed the current rules ({len(excluded)} excluded)."
            )
        if searched:
            if search_info.get("search_error"):
                reason += f" YouTube search failed: {search_info['search_error']}"
            else:
                reason += (
                    f" YouTube search found nothing suitable "
                    f"({search_info.get('search_rejected', 0)} result(s) rejected)."
                )
        reason += " Use Force with a YouTube ID."

        if not dry_run:
            notify(
                16776960,
                f"⚠️ No matching trailers — {title} ({year})",
                reason,
                event="failure"
            )
            record_activity({
                **context,
                "status": "warning",
                "action": "grab",
                "title": title,
                "year": year,
                "tmdb_id": tmdb_id,
                "detail": reason,
                "excluded": excluded[:10]
            })

        return {"status": "no_trailer", "reason": reason, "excluded": excluded}, 200

    out = out_path(folder_path, title, year)

    if dry_run:
        for candidate in scored:
            log.info(
                f"  [+{candidate['score']}] {candidate['name']} — "
                f"https://youtu.be/{candidate['key']}"
                + (" (YouTube search)" if candidate.get("via_search") else "")
            )
        return {
            "status": "dry_run",
            "candidates": scored,
            "would_save_to": f"{out}.{trailer_ext()}"
        }, 200

    attempts = []
    result, best = try_candidates(scored, out, attempts)
    if result and result.get("cancelled"):
        return {"status": "cancelled"}, 200

    # Every TMDB trailer is dead: search YouTube before giving up.
    if (
        not result["ok"]
        and not searched
        and youtube_search_enabled()
        and all(video_is_gone(a["error"]) for a in attempts)
    ):
        searched = True
        tried = {a["key"] for a in attempts}
        found = youtube_search_candidates(
            title, year, media_type, search_info, exclude_keys=tried
        )
        if found:
            result, best = try_candidates(found, out, attempts)
            if result and result.get("cancelled"):
                return {"status": "cancelled"}, 200

    skipped = [a for a in attempts if not a["ok"]]
    via_search = bool(best and best.get("via_search"))

    if result["ok"]:
        notes = []
        if replace_others:
            removed = remove_other_trailers(folder_path, result["path"])
            if removed:
                notes.append(f"removed old: {', '.join(removed)}")
        if via_search:
            channel = best.get("channel") or "unknown channel"
            notes.append(f"found via YouTube search ('{search_info.get('search_query', '')}', {channel})")
        if skipped:
            notes.append(
                f"skipped {len(skipped)} unavailable: "
                + ", ".join(f"{a['name']} ({a['key']})" for a in skipped)
            )
        note = (" — " + "; ".join(notes) + ".") if notes else ""

        trailer_path = result["path"]
        metadata = {
            "title": title,
            "year": year,
            "tmdb_id": tmdb_id,
            "youtube_id": best["key"],
            "tmdb_name": best["name"],
            "tmdb_type": "YouTube search" if via_search else best.get("type", ""),
            "score": best["score"],
            "matched_terms": best.get("matched_terms", []),
            "downloaded_at": utc_now(),
            "download_source": context.get("source", "automatic"),
            "library_id": context.get("library_id", ""),
            "library": context.get("library", ""),
            "arr_type": context.get("arr_type", "")
        }
        update_trailer_metadata(trailer_path, metadata)

        notify(
            3066993,
            f"✅ Trailer downloaded — {title} ({year})",
            f"**{best['name']}**\nhttps://youtu.be/{best['key']}"
            + ("\n_Found via YouTube search_" if via_search else ""),
            event="success"
        )

        record_activity({
            **context,
            "status": "success",
            "action": "grab",
            "title": title,
            "year": year,
            "tmdb_id": tmdb_id,
            "youtube_id": best["key"],
            "trailer_name": best["name"],
            "score": best["score"],
            "duration": result["duration"],
            "saved_to": trailer_path,
            "via_search": via_search,
            "detail": f"Trailer downloaded to {trailer_path}{note}",
            "attempts": attempts if skipped else [],
            "excluded": excluded[:10]
        })

        return {
            "status": "downloaded",
            "trailer": best["name"],
            "score": best["score"],
            "via_search": via_search,
            "saved_to": trailer_path
        }, 200

    all_gone = all(video_is_gone(a["error"]) for a in attempts)
    if all_gone:
        detail = (
            f"All {len(attempts)} candidate(s) tried are unavailable on YouTube: "
            + "; ".join(
                f"{a['name']} ({a['key']}{', search' if a['via_search'] else ''}): {a['error']}"
                for a in attempts
            )
            + "."
        )
        if searched and not any(a["via_search"] for a in attempts):
            detail += (
                " YouTube search found nothing suitable."
                if not search_info.get("search_error")
                else f" YouTube search failed: {search_info['search_error']}"
            )
        detail += " Use Force with a YouTube ID."
    else:
        detail = result["error"]

    record_activity({
        **context,
        "status": "error",
        "action": "grab",
        "title": title,
        "year": year,
        "tmdb_id": tmdb_id,
        "youtube_id": best["key"],
        "trailer_name": best["name"],
        "score": best["score"],
        "duration": result["duration"],
        "attempts": attempts,
        "detail": detail
    })

    notify(
        15158332,
        f"❌ Trailer failed — {title} ({year})",
        (
            f"All {len(attempts)} trailer(s) tried are unavailable on YouTube. "
            "Use Force with a YouTube ID."
            if all_gone else
            "yt-dlp failed. Check Activity or container logs for details."
        ),
        event="failure"
    )

    return {"status": "download_failed", "error": result["error"]}, 500


def _grab_item(item, library, dry_run, trigger, replace, skip_existing=False):
    context = context_for_item(item, library, trigger)

    if item["source"] == "radarr":
        tmdb_id = item.get("tmdb_id")
        if not tmdb_id:
            return {"status": "no_tmdb_match"}, 200
        return handle_grab(
            item["title"], item["year"], tmdb_id, "movie", item["path"],
            dry_run=dry_run, context=context, replace_others=replace,
            skip_existing=skip_existing
        )

    tmdb_id = resolve_tv_tmdb(
        item.get("tmdb_id"), item.get("tvdb_id"), item.get("imdb_id")
    )
    if not tmdb_id:
        return {"status": "no_tmdb_match"}, 200

    return handle_grab(
        item["title"], item["year"], tmdb_id, "tv", item["path"],
        dry_run=dry_run, context=context, replace_others=replace,
            skip_existing=skip_existing
    )


def grab_library_item(library_id, item_id, dry_run=False, trigger="Web UI", replace=False):
    library = get_library(library_id)
    if not library:
        return {"status": "library_missing"}, 404

    connection = get_connection(library.get("connection_id"))
    if not connection:
        return {"status": "connection_missing"}, 404

    item = get_connection_item(connection, item_id)

    if not item_is_usable(item):
        return {"status": "media_missing"}, 200
    if not library_owns_item(library, item.get("path", "")):
        return {"status": "outside_library"}, 400

    return _grab_item(item, library, dry_run, trigger, replace)


def grab_connection_item(connection_id, item_id, trigger="Web UI", replace=False,
                         skip_existing=False):
    """Grab by connection + item id (API v1 keys; no library involved)."""
    connection = get_connection(connection_id)
    if not connection:
        return {"status": "connection_missing"}, 404
    item = get_connection_item(connection, item_id)
    if not item_is_usable(item):
        return {"status": "media_missing"}, 200
    return _grab_item(item, None, False, trigger, replace, skip_existing)


def parse_youtube_id(value):
    """Accept a bare 11-char ID or any common YouTube URL. Returns '' if none."""
    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    try:
        parsed = urllib.parse.urlparse(text if "//" in text else f"//{text}")
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("v"):
            candidate = query["v"][0]
        else:
            parts = [p for p in parsed.path.split("/") if p]
            candidate = parts[1] if len(parts) > 1 and parts[0] in ("embed", "shorts", "live", "v") else ""
    else:
        return ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""


def _force_item(item, library, yt_id, trigger):
    folder = safe_folder_path(item["path"])
    out = out_path(folder, item["title"], item["year"])
    log_step(f"{item['title']} ({item['year']}) — manual YouTube {yt_id}")
    result = download(yt_id, out)
    if result.get("cancelled"):
        return {"status": "cancelled"}, 200
    context = context_for_item(item, library, trigger)

    if result["ok"]:
        metadata = {
            "title": item["title"],
            "year": item["year"],
            "youtube_id": yt_id,
            "tmdb_name": "Manual YouTube selection",
            "tmdb_type": "Manual",
            "score": None,
            "matched_terms": [],
            "downloaded_at": utc_now(),
            "download_source": trigger,
            "library_id": library["id"] if library else "",
            "library": library["name"] if library else item.get("connection_name", ""),
            "arr_type": item["source"]
        }
        update_trailer_metadata(result["path"], metadata)
        removed = remove_other_trailers(folder, result["path"])

        record_activity({
            **context,
            "status": "success",
            "action": "force",
            "title": item["title"],
            "year": item["year"],
            "youtube_id": yt_id,
            "duration": result["duration"],
            "detail": "Forced YouTube trailer downloaded."
            + (f" Removed old: {', '.join(removed)}." if removed else "")
        })

        notify(
            3066993,
            f"✅ Trailer downloaded — {item['title']} ({item['year']})",
            f"Manual YouTube selection\nhttps://youtu.be/{yt_id}",
            event="success"
        )
        return {"status": "downloaded", "saved_to": result["path"]}, 200

    record_activity({
        **context,
        "status": "error",
        "action": "force",
        "title": item["title"],
        "year": item["year"],
        "youtube_id": yt_id,
        "duration": result["duration"],
        "detail": result["error"]
    })
    return {"status": "download_failed", "error": result["error"]}, 500


def force_library_item(library_id, item_id, yt_id, trigger="Web UI"):
    yt_id = str(yt_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", yt_id):
        return {"status": "invalid_youtube_id"}, 400

    library = get_library(library_id)
    if not library:
        return {"status": "library_missing"}, 404
    connection = get_connection(library.get("connection_id"))
    if not connection:
        return {"status": "connection_missing"}, 404

    item = get_connection_item(connection, item_id)
    if not item_is_usable(item) or not library_owns_item(library, item["path"]):
        return {"status": "media_missing"}, 400

    return _force_item(item, library, yt_id, trigger)


def force_connection_item(connection_id, item_id, yt_id, trigger="Web UI"):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(yt_id or "")):
        return {"status": "invalid_youtube_id"}, 400
    connection = get_connection(connection_id)
    if not connection:
        return {"status": "connection_missing"}, 404
    item = get_connection_item(connection, item_id)
    if not item_is_usable(item):
        return {"status": "media_missing"}, 400
    return _force_item(item, None, yt_id, trigger)


def delete_library_trailer(library_id, item_id):
    """Delete every detected trailer file for one title."""
    try:
        library, item, folder = owned_item(library_id, item_id)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}, 400

    files = find_trailer_files(folder)
    if not files:
        return {"status": "not_found"}, 404

    removed = delete_trailer_files(folder, files)
    record_activity({
        **context_for_item(item, library, "Web UI"),
        "status": "success",
        "action": "delete",
        "title": item["title"],
        "year": item["year"],
        "detail": f"Deleted {', '.join(removed)}."
    })
    return {"status": "deleted", "removed": removed}, 200


# ── Batch jobs ────────────────────────────────────────────────────────────

BATCH_STATE = {
    "running": False,
    "scope": "",
    "total": 0,
    "done": 0,
    "success": 0,
    "failed": 0,
    "active": [],
    "queued": 0,
    "last_error": "",
    "cancel_requested": False,
    "cancelled": False,
    "cancelled_count": 0
}


def batch_snapshot():
    with BATCH_LOCK:
        return deepcopy(BATCH_STATE)


def batch_cancel_requested():
    with BATCH_LOCK:
        return bool(BATCH_STATE.get("cancel_requested"))


def request_batch_cancel():
    with BATCH_LOCK:
        if not BATCH_STATE["running"]:
            return False, ""

        BATCH_STATE["cancel_requested"] = True
        scope = BATCH_STATE.get("scope", "Batch")

    log.info(f"Batch cancellation requested: {scope}")
    return True, scope


def run_batch_task(task):
    label = task["label"]

    with BATCH_LOCK:
        BATCH_STATE["active"].append(label)
        BATCH_STATE["queued"] = max(
            0,
            BATCH_STATE["total"] - BATCH_STATE["done"] - len(BATCH_STATE["active"])
        )

    try:
        result, code = grab_library_item(
            task["library_id"],
            task["item_id"],
            trigger="Batch"
        )
        ok = code < 400 and result.get("status") == "downloaded"

        with BATCH_LOCK:
            if ok:
                BATCH_STATE["success"] += 1
            else:
                BATCH_STATE["failed"] += 1
                BATCH_STATE["last_error"] = (
                    f"{label}: {result.get('status', 'failed')}"
                )

    except Exception as e:
        log.exception(f"Batch grab failed for {label}")
        with BATCH_LOCK:
            BATCH_STATE["failed"] += 1
            BATCH_STATE["last_error"] = f"{label}: {e}"

    finally:
        with BATCH_LOCK:
            if label in BATCH_STATE["active"]:
                BATCH_STATE["active"].remove(label)
            BATCH_STATE["done"] += 1
            BATCH_STATE["queued"] = max(
                0,
                BATCH_STATE["total"]
                - BATCH_STATE["done"]
                - len(BATCH_STATE["active"])
            )


def batch_worker(tasks):
    workers = max_concurrent_downloads()
    task_iter = iter(tasks)
    futures = {}

    def submit_next(executor):
        if batch_cancel_requested():
            return False

        try:
            task = next(task_iter)
        except StopIteration:
            return False

        future = executor.submit(run_batch_task, task)
        futures[future] = task
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in range(min(workers, len(tasks))):
            if not submit_next(executor):
                break

        while futures:
            done_futures, _ = concurrent.futures.wait(
                tuple(futures),
                return_when=concurrent.futures.FIRST_COMPLETED
            )

            for future in done_futures:
                futures.pop(future, None)
                try:
                    future.result()
                except Exception as e:
                    log.exception(f"Batch worker error: {e}")

            while len(futures) < workers and submit_next(executor):
                pass

    with BATCH_LOCK:
        was_cancelled = bool(BATCH_STATE.get("cancel_requested"))
        cancelled_count = (
            max(0, BATCH_STATE["total"] - BATCH_STATE["done"])
            if was_cancelled else 0
        )
        scope = BATCH_STATE.get("scope", "Batch")
        completed = BATCH_STATE["done"]

        BATCH_STATE["running"] = False
        BATCH_STATE["active"] = []
        BATCH_STATE["queued"] = 0
        BATCH_STATE["cancelled"] = was_cancelled
        BATCH_STATE["cancelled_count"] = cancelled_count
        BATCH_STATE["cancel_requested"] = False

    if was_cancelled:
        record_activity({
            "status": "warning",
            "action": "Batch cancelled",
            "source": "Web UI",
            "title": scope,
            "detail": (
                f"Batch cancelled after {completed} completed task(s). "
                f"{cancelled_count} queued task(s) were not started."
            )
        })


def start_batch(tasks, scope):
    if not tasks:
        return False

    with BATCH_LOCK:
        if BATCH_STATE["running"]:
            return False

        BATCH_STATE.update({
            "running": True,
            "scope": scope,
            "total": len(tasks),
            "done": 0,
            "success": 0,
            "failed": 0,
            "active": [],
            "queued": len(tasks),
            "last_error": "",
            "cancel_requested": False,
            "cancelled": False,
            "cancelled_count": 0
        })

    thread = threading.Thread(target=batch_worker, args=(tasks,), daemon=True)
    thread.start()
    return True


# ── Arr watcher ───────────────────────────────────────────────────────────
#
# Polls each configured Arr connection through its API. This is the only
# automatic trigger (Arr webhooks are no longer supported):
#
# - Radarr: a movie's file ID appearing (import) or changing (upgrade).
# - Sonarr: a series ID appearing (series added). Its folder may not exist
#   yet, so it stays pending and is retried until the folder appears.
#
# The first check of a connection only records a baseline. Nothing already in
# the library is grabbed — use Grab all missing for that.

def watch_interval_seconds():
    try:
        minutes = int(str(cfg("watch_interval_minutes")))
    except (TypeError, ValueError):
        minutes = 5
    return max(0, min(1440, minutes)) * 60


def load_watch_state():
    with WATCH_LOCK:
        try:
            with open(WATCH_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:
            log.warning(f"Could not read watcher state: {e}")
            return {}


def save_watch_state(state):
    with WATCH_LOCK:
        try:
            os.makedirs(os.path.dirname(WATCH_STATE_FILE) or ".", exist_ok=True)
            tmp = f"{WATCH_STATE_FILE}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(tmp, WATCH_STATE_FILE)
        except Exception as e:
            log.warning(f"Could not save watcher state: {e}")


def radarr_file_id(movie):
    movie_file = movie.get("movieFile")
    if isinstance(movie_file, dict) and movie_file.get("id"):
        return int(movie_file["id"])
    try:
        return int(movie.get("movieFileId") or 0)
    except (TypeError, ValueError):
        return 0


def library_for_item(connection_id, item_path):
    for library in get_libraries():
        if (
            library.get("connection_id") == connection_id
            and library_owns_item(library, item_path)
        ):
            return library
    return None


def watcher_grab(connection, item, reason):
    """Grab one item found by the watcher. Returns the result status."""

    library = library_for_item(connection.get("id"), item.get("path", ""))
    if not library:
        log.info(f"Watcher: {item['title']} is outside every library, skipping.")
        return "outside_library"

    context = context_for_item(item, library, "API watcher")
    context["watch_reason"] = reason

    if item["source"] == "radarr":
        tmdb_id = item.get("tmdb_id")
        media_type = "movie"
    else:
        tmdb_id = resolve_tv_tmdb(
            item.get("tmdb_id"), item.get("tvdb_id"), item.get("imdb_id")
        )
        media_type = "tv"

    if not tmdb_id:
        record_activity({
            **context,
            "status": "warning",
            "action": "grab",
            "title": item["title"],
            "year": item["year"],
            "detail": f"{reason}: no TMDB match for this title."
        })
        return "no_tmdb_match"

    log.info(f"Watcher: {reason} — {item['title']} ({item['year']})")
    result, _code = handle_grab(
        item["title"], item["year"], tmdb_id, media_type, item["path"],
        context=context, skip_existing=True
    )
    return result.get("status", "unknown")


def watch_radarr(connection, conn_state, first_run):
    movies = arr_get(connection, "/api/v3/movie")
    known = conn_state.get("movies", {})
    current = {}
    triggers = []

    for movie in movies:
        movie_id = str(movie.get("id"))
        file_id = radarr_file_id(movie)
        current[movie_id] = file_id

        if first_run or not file_id:
            continue

        previous = known.get(movie_id, 0)
        if file_id == previous:
            continue

        reason = "Imported" if not previous else "Upgraded"
        triggers.append((normalize_radarr(movie, connection), reason))

    with_files = [m for m in movies if m.get("hasFile")]
    if with_files and not any(radarr_file_id(m) for m in with_files):
        raise RuntimeError(
            "Radarr returned movies with files but no file IDs; "
            "the watcher cannot detect imports on this Radarr. Check the Radarr "
            "version, and that the API key can read /api/v3/movie. Automatic grabs "
            "are off for this connection until it works; use Sync now after fixing."
        )

    conn_state["movies"] = current
    return triggers


def watch_sonarr(connection, conn_state, first_run):
    series_list = arr_get(connection, "/api/v3/series")
    known = set(str(x) for x in conn_state.get("series", []))
    pending = dict(conn_state.get("pending", {}))
    current = []
    triggers = []
    now = dt.datetime.now(dt.timezone.utc)
    by_id = {}

    for series in series_list:
        series_id = str(series.get("id"))
        current.append(series_id)
        by_id[series_id] = series

        if not first_run and series_id not in known:
            pending[series_id] = utc_now()

    for series_id, since in list(pending.items()):
        series = by_id.get(series_id)
        if not series:
            pending.pop(series_id, None)  # removed from Sonarr
            continue

        item = normalize_sonarr(series, connection)
        if media_folder_exists(item.get("path", "")):
            pending.pop(series_id, None)
            triggers.append((item, "Series added"))
            continue

        try:
            age = now - dt.datetime.fromisoformat(since)
        except (TypeError, ValueError):
            age = dt.timedelta(0)
        if age > dt.timedelta(days=WATCH_PENDING_DAYS):
            pending.pop(series_id, None)
            record_activity({
                "source": "API watcher",
                "arr_type": "sonarr",
                "connection_id": connection.get("id", ""),
                "connection": connection.get("name", ""),
                "status": "warning",
                "action": "grab",
                "title": item["title"],
                "year": item["year"],
                "detail": (
                    f"Series folder never appeared within {WATCH_PENDING_DAYS} "
                    f"days: {item.get('path', '')}. Stopped waiting."
                )
            })

    conn_state["series"] = current
    conn_state["pending"] = pending
    return triggers


def watch_connection(connection, state):
    connection_id = connection.get("id")
    conn_state = state.setdefault(connection_id, {})
    first_run = not conn_state.get("initialized")
    source = connection.get("type")

    try:
        if source == "radarr":
            triggers = watch_radarr(connection, conn_state, first_run)
        elif source == "sonarr":
            triggers = watch_sonarr(connection, conn_state, first_run)
        else:
            return
    except Exception as e:
        conn_state["last_check"] = utc_now()
        conn_state["last_error"] = str(e)[:300]
        log.warning(f"Watcher: {connection.get('name', connection_id)} check failed: {e}")
        return

    conn_state["initialized"] = True
    conn_state["last_check"] = utc_now()
    conn_state["last_error"] = ""

    if first_run:
        log.info(
            f"Watcher: baseline recorded for {connection.get('name', connection_id)}. "
            "Existing items are not grabbed."
        )
        return

    # Save the new baseline before downloading, so a crash mid-download
    # doesn't re-trigger everything on restart.
    save_watch_state(state)

    for item, reason in triggers:
        try:
            status = watcher_grab(connection, item, reason)
        except Exception as e:
            log.error(f"Watcher grab failed for {item.get('title')}: {e}")
            status = "error"
        conn_state["last_trigger"] = {
            "time": utc_now(),
            "event": reason,
            "title": item.get("title", ""),
            "year": item.get("year", ""),
            "status": status
        }
        save_watch_state(state)


WATCH_RUN_LOCK = threading.Lock()


def watch_cycle_running():
    return WATCH_RUN_LOCK.locked()


def run_watch_cycle(force=False):
    """Run one watcher pass. Returns False if one is already running."""
    if not WATCH_RUN_LOCK.acquire(blocking=False):
        return False
    try:
        _run_watch_cycle(force)
    finally:
        WATCH_RUN_LOCK.release()
    return True


def _run_watch_cycle(force=False):
    interval = watch_interval_seconds()
    if not interval and not force:
        return

    state = load_watch_state()
    configured = [c for c in get_connections() if c.get("api_key")]
    configured_ids = {c.get("id") for c in configured}

    # Forget connections that were removed from Settings.
    for connection_id in list(state.keys()):
        if connection_id not in configured_ids:
            state.pop(connection_id, None)

    now = time.time()
    for connection in configured:
        conn_state = state.get(connection.get("id"), {})
        last = conn_state.get("last_check")
        if last and not force and conn_state.get("initialized"):
            try:
                elapsed = now - dt.datetime.fromisoformat(last).timestamp()
                if elapsed < interval:
                    continue
            except (TypeError, ValueError):
                pass
        watch_connection(connection, state)
        save_watch_state(state)


def arr_watch_monitor():
    # Let the web server come up first.
    time.sleep(20)
    while True:
        try:
            run_watch_cycle()
        except Exception as e:
            log.warning(f"Watcher cycle failed: {e}")
        time.sleep(30)


# ── Settings helpers ──────────────────────────────────────────────────────

SECRET_FIELDS = {"tmdb_api_key", "discord_webhook_url"}


def effective_secret(form, key):
    if form.get(f"clear_{key}") == "1":
        return ""
    submitted = str(form.get(key, "") or "").strip()
    return submitted or str(cfg(key) or "")


PUBLIC_SETTING_KEYS = (
    "media_root", "preferred_terms", "excluded_terms", "trailer_folder",
    "filename_template", "video_quality", "container", "max_concurrent_downloads",
    "watch_interval_minutes", "youtube_search", "notify_success", "notify_failure",
    "activity_retention_days",
)
SECRET_SETTING_KEYS = ("tmdb_api_key", "discord_webhook_url")


def public_settings():
    """Everything the Settings screen shows. Secrets appear only as configured flags."""
    return {
        "settings": {key: cfg(key) for key in PUBLIC_SETTING_KEYS},
        "configured": configured_state(),
        "connections": [connection_public(c, load_watch_state()) for c in get_connections()],
        "app_version": APP_VERSION,
    }


def apply_settings_update(body):
    """Partial update (SPEC 6.1). Omitted keys stay as they are. Secrets: empty or omitted
    keeps the stored value, `clear_<key>: true` clears it. Raises ValueError."""
    allowed = set(PUBLIC_SETTING_KEYS) | set(SECRET_SETTING_KEYS) | {
        "connections", *(f"clear_{k}" for k in SECRET_SETTING_KEYS)}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ValueError(f"Unknown setting: {', '.join(unknown)}.")

    values = {key: body.get(key, cfg(key)) for key in PUBLIC_SETTING_KEYS}
    cleaned = validate_settings_scalars(values)
    update = {key: cleaned[key] for key in PUBLIC_SETTING_KEYS}

    for key in SECRET_SETTING_KEYS:
        if body.get(f"clear_{key}") is True:
            update[key] = ""
        else:
            submitted = str(body.get(key, "") or "").strip()
            update[key] = submitted or str(cfg(key) or "")

    if "connections" in body:
        update["arr_connections"] = validate_connections(body["connections"])

    save_settings(update)
    return public_settings()


def test_service(service, body):
    """Test TMDB or Discord with the submitted (or stored) secret, saving it on success."""
    form = {k: v for k, v in body.items()}
    for key in SECRET_SETTING_KEYS:
        form[f"clear_{key}"] = "1" if body.get(f"clear_{key}") is True else ""
    if service == "tmdb":
        return test_tmdb_connection(form)
    if service == "discord":
        return test_discord_connection(form)
    raise ValueError("Unknown service.")


def configured_state():
    return {
        "tmdb": bool(cfg("tmdb_api_key")),
        "discord": bool(cfg("discord_webhook_url"))
    }


def connection_public(connection, watch_state=None):
    connection_id = connection.get("id", "")
    watch = (watch_state or {}).get(connection_id) or {}
    return {
        "id": connection_id,
        "name": connection.get("name", ""),
        "type": connection.get("type", "radarr"),
        "url": connection.get("url", ""),
        "configured": bool(connection.get("url") and connection.get("api_key")),
        "saved": True,
        "watch": {
            "initialized": bool(watch.get("initialized")),
            "last_check": watch.get("last_check", ""),
            "last_error": watch.get("last_error", ""),
            "last_trigger": watch.get("last_trigger"),
            "pending": len(watch.get("pending", {}) or {})
        }
    }


def library_public(library):
    return {
        "id": library.get("id", ""),
        "name": library.get("name", ""),
        "connection_id": library.get("connection_id", ""),
        "root_path": library.get("root_path", "")
    }


def test_tmdb_connection(form):
    token = effective_secret(form, "tmdb_api_key")
    data = tmdb_get_with_token(token, "/configuration")
    if not data.get("images"):
        raise RuntimeError("TMDB returned an unexpected response.")
    save_settings({"tmdb_api_key": token})
    return "TMDB connected successfully. Settings saved."


def test_discord_connection(form):
    webhook = effective_secret(form, "discord_webhook_url")
    send_discord(
        webhook,
        3066993,
        "🎬 Trailarr Parrk connected",
        "Discord webhook test successful."
    )
    save_settings({"discord_webhook_url": webhook})
    return "Discord test message sent successfully. Settings saved."


def test_and_save_arr_connection(payload):
    existing = get_connections()
    existing_by_id = {c.get("id"): c for c in existing}

    connection_id = str(payload.get("id") or unique_id("arr", payload.get("name", "")))
    raw = dict(payload)
    raw["id"] = connection_id

    tested = validate_connections([raw], existing_connections=existing)[0]
    data = arr_get(tested, "/api/v3/system/status")
    version = data.get("version", "unknown")

    new_connections = []
    replaced = False
    for connection in existing:
        if connection.get("id") == connection_id:
            new_connections.append(tested)
            replaced = True
        else:
            new_connections.append(connection)

    if not replaced:
        new_connections.append(tested)

    save_settings({"arr_connections": new_connections})
    return tested, version
