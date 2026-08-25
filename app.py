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

from flask import Flask, jsonify, redirect, render_template, request, url_for


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="[trailarr-parrk] %(message)s"
)
log = logging.getLogger(__name__)

APP_VERSION = "0.6.1"


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
        "official,trailer,teaser,theatrical"
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
    "max_concurrent_downloads": os.environ.get(
        "MAX_CONCURRENT_DOWNLOADS",
        "1"
    )
}

SETTINGS_LOCK = threading.RLock()
BATCH_LOCK = threading.RLock()
LOCAL_ACTIVITY_LOCK = threading.RLock()
YTDLP_STATUS_LOCK = threading.RLock()
BACKGROUND_JOBS_LOCK = threading.RLock()
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


def legacy_libraries():
    return [
        {
            "id": "movies",
            "name": "Movies",
            "connection_id": "radarr-main",
            "root_path": ""
        },
        {
            "id": "tv-shows",
            "name": "TV Shows",
            "connection_id": "sonarr-main",
            "root_path": ""
        }
    ]


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

    connections = saved.get("arr_connections")
    libraries = saved.get("libraries")

    settings["arr_connections"] = (
        connections if isinstance(connections, list) else legacy_connections(settings)
    )
    settings["libraries"] = (
        libraries if isinstance(libraries, list) else legacy_libraries()
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
    with SETTINGS_LOCK:
        return deepcopy(SETTINGS.get("libraries", []))


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


def validate_settings_scalars(values):
    media_root = validate_media_root(values.get("media_root", ""))

    quality = str(values.get("video_quality", "")).strip()
    if not quality.isdigit() or not 144 <= int(quality) <= 4320:
        raise ValueError("Video quality must be a number between 144 and 4320.")

    max_downloads = str(values.get("max_concurrent_downloads", "1")).strip()
    if not max_downloads.isdigit() or not 1 <= int(max_downloads) <= 4:
        raise ValueError("Concurrent downloads must be between 1 and 4.")

    trailer_folder = str(values.get("trailer_folder", "")).strip()
    if trailer_folder:
        if os.path.isabs(trailer_folder):
            raise ValueError("Trailer folder must be a relative folder name.")

        parts = trailer_folder.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(
                "Trailer folder cannot contain empty, '.' or '..' path parts."
            )

    filename_template = str(values.get("filename_template", "")).strip()
    if not filename_template:
        raise ValueError("Filename template cannot be empty.")
    if "/" in filename_template or "\\" in filename_template:
        raise ValueError("Filename template cannot contain path separators.")
    if ".." in filename_template:
        raise ValueError("Filename template cannot contain '..'.")
    if "{title}" not in filename_template:
        raise ValueError("Filename template must contain {title}.")

    return {
        **values,
        "media_root": media_root,
        "video_quality": quality,
        "max_concurrent_downloads": max_downloads,
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


def validate_libraries(libraries, connections, media_root):
    if not isinstance(libraries, list):
        raise ValueError("Libraries must be a list.")

    connection_ids = {c["id"] for c in connections}
    cleaned = []
    seen_ids = set()

    for raw in libraries:
        if not isinstance(raw, dict):
            raise ValueError("Invalid library entry.")

        library_id = str(raw.get("id") or unique_id("lib", raw.get("name", "")))
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", library_id):
            raise ValueError("Library ID contains invalid characters.")
        if library_id in seen_ids:
            raise ValueError("Duplicate library ID.")
        seen_ids.add(library_id)

        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Every library needs a name.")

        connection_id = str(raw.get("connection_id", "")).strip()
        if connection_id not in connection_ids:
            raise ValueError(f"Library '{name}' has no valid Arr connection.")

        root_path = str(raw.get("root_path", "") or "").strip()
        if root_path:
            if not os.path.isabs(root_path):
                raise ValueError(
                    f"Library root for '{name}' must be an absolute container path."
                )
            root_path = os.path.normpath(root_path)
            safe_under_media_root(root_path, media_root)
            if not os.path.isdir(root_path):
                raise ValueError(
                    f"Library root does not exist inside the container: {root_path}"
                )

        cleaned.append({
            "id": library_id,
            "name": name,
            "connection_id": connection_id,
            "root_path": root_path
        })

    if not cleaned:
        raise ValueError("At least one library is required.")

    return cleaned


def parse_json_form_field(form, key):
    raw = form.get(key, "")
    try:
        value = json.loads(raw)
    except Exception as e:
        raise ValueError(f"Invalid {key}: {e}") from e
    return value


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


def notify(color, title, body):
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


def tvdb_to_tmdb(tvdb_id):
    try:
        data = tmdb_get(
            f"/find/{tvdb_id}",
            {"external_source": "tvdb_id"}
        )
    except Exception as e:
        log.error(f"TVDB→TMDB lookup failed: {e}")
        return None

    results = data.get("tv_results", [])
    if not results:
        log.error(f"No TMDB match found for tvdbId {tvdb_id}.")
        return None

    return results[0].get("id")


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
            matched_term = term in name_lower

        if matched_term:
            score += points
            matched.append({"term": term, "points": points})

    return score, matched


def fetch_and_score(tmdb_id, media_type):
    try:
        data = tmdb_get(f"/{media_type}/{tmdb_id}/videos")
    except Exception as e:
        log.error(f"TMDB videos request failed: {e}")
        return [], []

    results = [
        r for r in data.get("results", [])
        if r.get("site") == "YouTube"
        and r.get("type") in ("Trailer", "Teaser")
    ]

    log.info(f"TMDB returned {len(results)} YouTube trailer/teaser(s).")

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
            scored.append({
                "score": score,
                "key": key,
                "name": name,
                "type": video.get("type", ""),
                "official": bool(video.get("official", False)),
                "matched_terms": matched
            })

    scored.sort(
        key=lambda item: (
            item["score"],
            item.get("type") == "Trailer",
            item.get("official", False)
        ),
        reverse=True
    )

    return scored, excluded


# ── Filesystem / yt-dlp ──────────────────────────────────────────────────

def out_path(base_path, title, year):
    safe_title = re.sub(r'[/:*?"<>|\\]', "_", str(title))
    name = (
        str(cfg("filename_template"))
        .replace("{title}", safe_title)
        .replace("{year}", str(year))
    )

    trailer_folder = str(cfg("trailer_folder") or "")
    if trailer_folder:
        return os.path.join(base_path, trailer_folder, name)
    return os.path.join(base_path, name)


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
    return f"{out_path(base, item['title'], item['year'])}.mkv"


def trailer_exists(base_path, title, year):
    try:
        base_path = safe_folder_path(base_path)
    except ValueError:
        return False
    return os.path.isfile(f"{out_path(base_path, title, year)}.mkv")


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


@contextlib.contextmanager
def acquire_download_slot():
    """Cross-process limiter shared by web requests, batch workers and CLI."""

    os.makedirs(DOWNLOAD_SLOT_DIR, exist_ok=True)

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

            try:
                yield slot
            finally:
                fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
                file_obj.close()
            return

        time.sleep(0.25)


def cleanup_temp_files(temp_base):
    for path in glob.glob(f"{glob.escape(temp_base)}.*"):
        try:
            os.remove(path)
        except OSError:
            pass


def download(yt_id, out_path_noext):
    """Download atomically. Existing trailer stays in place until success."""

    directory = os.path.dirname(out_path_noext)
    os.makedirs(directory, exist_ok=True)

    target_path = f"{out_path_noext}.mkv"
    unique = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:6]}"
    temp_base = f"{out_path_noext}.trailarr-new-{unique}"
    cleanup_temp_files(temp_base)

    video_quality = str(cfg("video_quality"))
    cmd = [
        ytdlp_binary(),
        "-f",
        (
            f"bestvideo[height<={video_quality}][ext=mp4]"
            f"+bestaudio[ext=m4a]/"
            f"bestvideo[height<={video_quality}]"
            f"+bestaudio/best"
        ),
        "--merge-output-format",
        "mkv",
        "--no-playlist",
        "-o",
        f"{temp_base}.%(ext)s",
        f"https://www.youtube.com/watch?v={yt_id}"
    ]

    started = time.monotonic()
    result = None

    with acquire_download_slot():
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900
            )
        except subprocess.TimeoutExpired:
            cleanup_temp_files(temp_base)
            return {
                "ok": False,
                "duration": round(time.monotonic() - started, 1),
                "error": "yt-dlp timed out after 900 seconds."
            }

    duration = round(time.monotonic() - started, 1)

    if result.stdout:
        log.info(result.stdout.strip())

    if result.returncode != 0:
        error = (result.stderr or "yt-dlp failed.").strip()
        log.error(error)
        cleanup_temp_files(temp_base)
        return {"ok": False, "duration": duration, "error": error[-3000:]}

    candidates = [
        path for path in glob.glob(f"{glob.escape(temp_base)}.*")
        if os.path.isfile(path)
    ]
    preferred = [path for path in candidates if path.lower().endswith(".mkv")]
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
        "tmdb_id": None,
        "tvdb_id": series.get("tvdbId"),
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
    trailer_path = trailer_path_for_item(item)
    item["trailer_path"] = trailer_path
    item["missing"] = not os.path.isfile(trailer_path)
    item["metadata"] = (metadata_map or {}).get(os.path.realpath(trailer_path))
    return item


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

def handle_grab(title, year, tmdb_id, media_type, folder_path, dry_run=False, context=None):
    context = context or {}
    log.info(
        f"{title} ({year}) — TMDB {tmdb_id}"
        + (" [DRY RUN]" if dry_run else "")
    )

    try:
        folder_path = safe_folder_path(folder_path)
    except ValueError as e:
        return {"status": "rejected", "reason": str(e)}, 400

    scored, excluded = fetch_and_score(tmdb_id, media_type)

    if not scored:
        if not dry_run:
            notify(
                16776960,
                f"⚠️ No matching trailers — {title} ({year})",
                "No suitable TMDB trailer/teaser matched the current rules."
            )
            record_activity({
                **context,
                "status": "warning",
                "action": "grab",
                "title": title,
                "year": year,
                "tmdb_id": tmdb_id,
                "detail": "No suitable trailer found.",
                "excluded": excluded[:10]
            })

        return {"status": "no_trailer", "excluded": excluded}, 200

    out = out_path(folder_path, title, year)
    best = scored[0]

    if dry_run:
        for candidate in scored:
            log.info(
                f"  [+{candidate['score']}] {candidate['name']} — "
                f"https://youtu.be/{candidate['key']}"
            )
        return {
            "status": "dry_run",
            "candidates": scored,
            "would_save_to": f"{out}.mkv"
        }, 200

    result = download(best["key"], out)

    if result["ok"]:
        trailer_path = result["path"]
        metadata = {
            "title": title,
            "year": year,
            "tmdb_id": tmdb_id,
            "youtube_id": best["key"],
            "tmdb_name": best["name"],
            "tmdb_type": best.get("type", ""),
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
            "detail": "Trailer downloaded.",
            "excluded": excluded[:10]
        })

        return {
            "status": "downloaded",
            "trailer": best["name"],
            "score": best["score"],
            "saved_to": trailer_path
        }, 200

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
        "detail": result["error"]
    })

    notify(
        15158332,
        f"❌ Trailer failed — {title} ({year})",
        "yt-dlp failed. Check Activity or container logs for details."
    )

    return {"status": "download_failed", "error": result["error"]}, 500


def grab_library_item(library_id, item_id, dry_run=False, trigger="Web UI"):
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

    context = context_for_item(item, library, trigger)

    if item["source"] == "radarr":
        tmdb_id = item.get("tmdb_id")
        if not tmdb_id:
            return {"status": "no_tmdb_match"}, 200
        return handle_grab(
            item["title"], item["year"], tmdb_id, "movie", item["path"],
            dry_run=dry_run, context=context
        )

    tvdb_id = item.get("tvdb_id")
    tmdb_id = tvdb_to_tmdb(tvdb_id) if tvdb_id else None
    if not tmdb_id:
        return {"status": "no_tmdb_match"}, 200

    return handle_grab(
        item["title"], item["year"], tmdb_id, "tv", item["path"],
        dry_run=dry_run, context=context
    )


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

    folder = safe_folder_path(item["path"])
    out = out_path(folder, item["title"], item["year"])
    result = download(yt_id, out)
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
            "library_id": library["id"],
            "library": library["name"],
            "arr_type": item["source"]
        }
        update_trailer_metadata(result["path"], metadata)

        record_activity({
            **context,
            "status": "success",
            "action": "force",
            "title": item["title"],
            "year": item["year"],
            "youtube_id": yt_id,
            "duration": result["duration"],
            "detail": "Forced YouTube trailer downloaded."
        })

        notify(
            3066993,
            f"✅ Trailer downloaded — {item['title']} ({item['year']})",
            f"Manual YouTube selection\nhttps://youtu.be/{yt_id}"
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


def delete_library_trailer(library_id, item_id):
    library = get_library(library_id)
    if not library:
        return {"status": "library_missing"}, 404
    connection = get_connection(library.get("connection_id"))
    if not connection:
        return {"status": "connection_missing"}, 404

    item = get_connection_item(connection, item_id)
    if not library_owns_item(library, item.get("path", "")):
        return {"status": "outside_library"}, 400

    trailer_path = trailer_path_for_item(item)
    if os.path.isfile(trailer_path):
        os.remove(trailer_path)
        update_trailer_metadata(trailer_path, remove=True)

        record_activity({
            **context_for_item(item, library, "Web UI"),
            "status": "success",
            "action": "delete",
            "title": item["title"],
            "year": item["year"],
            "detail": "Trailer deleted."
        })
        return {"status": "deleted"}, 200

    return {"status": "not_found"}, 404


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


# ── Settings helpers ──────────────────────────────────────────────────────

SECRET_FIELDS = {"tmdb_api_key", "discord_webhook_url"}


def effective_secret(form, key):
    if form.get(f"clear_{key}") == "1":
        return ""
    submitted = str(form.get(key, "") or "").strip()
    return submitted or str(cfg(key) or "")


def collect_settings_form(form):
    scalar_values = {
        "media_root": form.get("media_root", cfg("media_root")),
        "preferred_terms": form.get("preferred_terms", cfg("preferred_terms")),
        "excluded_terms": form.get("excluded_terms", cfg("excluded_terms")),
        "trailer_folder": form.get("trailer_folder", cfg("trailer_folder")),
        "filename_template": form.get("filename_template", cfg("filename_template")),
        "video_quality": form.get("video_quality", cfg("video_quality")),
        "max_concurrent_downloads": form.get(
            "max_concurrent_downloads",
            cfg("max_concurrent_downloads")
        )
    }
    scalar_values = validate_settings_scalars(scalar_values)

    for key in SECRET_FIELDS:
        scalar_values[key] = effective_secret(form, key)

    raw_connections = parse_json_form_field(form, "connections_json")
    connections = validate_connections(raw_connections)

    raw_libraries = parse_json_form_field(form, "libraries_json")
    libraries = validate_libraries(
        raw_libraries,
        connections,
        scalar_values["media_root"]
    )

    scalar_values["arr_connections"] = connections
    scalar_values["libraries"] = libraries
    return scalar_values


def configured_state():
    return {
        "tmdb": bool(cfg("tmdb_api_key")),
        "discord": bool(cfg("discord_webhook_url"))
    }


def connection_public(connection):
    return {
        "id": connection.get("id", ""),
        "name": connection.get("name", ""),
        "type": connection.get("type", "radarr"),
        "url": connection.get("url", ""),
        "configured": bool(connection.get("url") and connection.get("api_key"))
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


# ── Navigation helpers ────────────────────────────────────────────────────

def nav_libraries():
    return [library_public(lib) for lib in get_libraries()]


# ── Web UI routes ────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    library_id = first_library_id()
    if not library_id:
        return redirect(url_for("settings_page"))
    return redirect(url_for("library_page", library_id=library_id))


@app.route("/library/<library_id>", methods=["GET"])
def library_page(library_id):
    view = request.args.get("view", "missing")
    if view not in ("missing", "existing"):
        view = "missing"

    try:
        library, missing, existing, error = load_library_views(library_id)
    except ValueError:
        return redirect(url_for("index"))

    items = missing if view == "missing" else existing

    return render_template(
        "library.html",
        library=library,
        libraries=nav_libraries(),
        items=items,
        missing_count=len(missing),
        existing_count=len(existing),
        view=view,
        error=error,
        batch=batch_snapshot(),
        message=request.args.get("message", ""),
        app_version=APP_VERSION
    )


@app.route("/library/<library_id>/grab", methods=["POST"])
def library_grab(library_id):
    item_id = request.form.get("id", "")
    try:
        result, code = grab_library_item(library_id, item_id)
        status = result.get("status", "unknown")
        message = "Trailer downloaded." if status == "downloaded" else f"Result: {status}"
        if code >= 400:
            message = f"Failed: {status}"
    except Exception as e:
        log.exception("UI grab failed")
        message = f"Failed: {e}"

    return redirect(url_for("library_page", library_id=library_id, view="missing", message=message))


@app.route("/library/<library_id>/force", methods=["POST"])
def library_force(library_id):
    item_id = request.form.get("id", "")
    yt_id = request.form.get("yt_id", "")
    return_view = request.form.get("return_view", "missing")

    try:
        result, code = force_library_item(library_id, item_id, yt_id)
        status = result.get("status", "unknown")
        message = "Forced YouTube trailer downloaded." if status == "downloaded" else f"Failed: {status}"
    except Exception as e:
        log.exception("UI force failed")
        message = f"Failed: {e}"

    return redirect(url_for("library_page", library_id=library_id, view=return_view, message=message))


@app.route("/library/<library_id>/delete", methods=["POST"])
def library_delete(library_id):
    item_id = request.form.get("id", "")
    try:
        result, _ = delete_library_trailer(library_id, item_id)
        message = "Trailer deleted." if result.get("status") == "deleted" else "Trailer not found."
    except Exception as e:
        log.exception("UI delete failed")
        message = f"Failed: {e}"

    return redirect(url_for("library_page", library_id=library_id, view="existing", message=message))


@app.route("/library/<library_id>/grab-all", methods=["POST"])
def library_grab_all(library_id):
    try:
        tasks = library_missing_tasks(library_id)
        library = get_library(library_id)
        if not tasks:
            message = "No missing trailers in this library."
        elif start_batch(tasks, library.get("name", "Library")):
            message = f"Started {len(tasks)} trailer(s) for {library.get('name')}."
        else:
            message = "A batch is already running."
    except Exception as e:
        message = f"Failed: {e}"

    return redirect(url_for("library_page", library_id=library_id, view="missing", message=message))


@app.route("/activity", methods=["GET"])
def activity_page():
    return render_template(
        "activity.html",
        libraries=nav_libraries(),
        activity=read_activity(),
        batch=batch_snapshot(),
        app_version=APP_VERSION,
        message=request.args.get("message", "")
    )


@app.route("/activity/clear", methods=["POST"])
def activity_clear():
    clear_activity()
    return redirect(url_for("activity_page", message="Activity history cleared."))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    message = request.args.get("message", "")
    message_type = "success"

    if request.method == "POST":
        try:
            values = collect_settings_form(request.form)
            save_settings(values)
            message = "Settings saved."

            next_url = str(request.form.get("next_url", "") or "").strip()
            parsed = urllib.parse.urlparse(next_url)
            if next_url.startswith("/") and not parsed.netloc and not parsed.scheme:
                return redirect(next_url)

        except Exception as e:
            message = str(e)
            message_type = "error"

    return render_template(
        "settings.html",
        libraries=nav_libraries(),
        settings={
            "media_root": cfg("media_root"),
            "preferred_terms": cfg("preferred_terms"),
            "excluded_terms": cfg("excluded_terms"),
            "trailer_folder": cfg("trailer_folder"),
            "filename_template": cfg("filename_template"),
            "video_quality": cfg("video_quality"),
            "max_concurrent_downloads": cfg("max_concurrent_downloads")
        },
        connections=[connection_public(c) for c in get_connections()],
        library_settings=[library_public(lib) for lib in get_libraries()],
        configured=configured_state(),
        message=message,
        message_type=message_type,
        settings_file=SETTINGS_FILE,
        app_version=APP_VERSION,
        ytdlp=ytdlp_ui_status(),
        batch=batch_snapshot()
    )


@app.route("/settings/test/<service>", methods=["POST"])
def settings_test(service):
    try:
        if service == "tmdb":
            message = test_tmdb_connection(request.form)
        elif service == "discord":
            message = test_discord_connection(request.form)
        else:
            raise ValueError("Unknown service test.")

        return jsonify({
            "status": "ok",
            "message": message,
            "configured": configured_state()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "configured": configured_state()
        }), 400


@app.route("/settings/test-arr", methods=["POST"])
def settings_test_arr():
    payload = request.get_json(silent=True) or {}
    try:
        connection, version = test_and_save_arr_connection(payload)
        return jsonify({
            "status": "ok",
            "message": (
                f"{connection['name']} connected successfully "
                f"(version {version}). Settings saved."
            ),
            "connection": connection_public(connection)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/batch", methods=["GET"])
def api_batch():
    return jsonify(batch_snapshot())


@app.route("/ui/batch/cancel", methods=["POST"])
def ui_batch_cancel():
    cancelled, scope = request_batch_cancel()
    message = (
        f"Cancellation requested for {scope}. Active download(s) will finish safely."
        if cancelled else
        "No batch is currently running."
    )

    next_url = str(request.form.get("next_url", "") or "").strip()
    parsed = urllib.parse.urlparse(next_url)
    if next_url.startswith("/") and not parsed.netloc and not parsed.scheme:
        separator = "&" if "?" in next_url else "?"
        return redirect(
            f"{next_url}{separator}{urllib.parse.urlencode({'message': message})}"
        )

    return redirect(url_for("activity_page", message=message))


@app.route("/api/global-missing-summary", methods=["GET"])
def api_global_missing_summary():
    summary = []
    total = 0

    for library in get_libraries():
        try:
            _, missing, _, error = load_library_views(library["id"])
            count = len(missing)
            summary.append({
                "id": library["id"],
                "name": library["name"],
                "count": count,
                "error": error or ""
            })
            total += count
        except Exception as e:
            summary.append({
                "id": library["id"],
                "name": library["name"],
                "count": 0,
                "error": str(e)
            })

    return jsonify({"libraries": summary, "total": total})


@app.route("/ui/grab-all-global", methods=["POST"])
def global_grab_all():
    tasks = all_missing_items()
    if not tasks:
        message = "No missing trailers across configured libraries."
    elif start_batch(tasks, "All libraries"):
        message = f"Started global batch for {len(tasks)} trailer(s)."
    else:
        message = "A batch is already running."

    return redirect(url_for("settings_page", message=message))


@app.route("/api/yt-dlp/check", methods=["GET"])
def api_ytdlp_check():
    try:
        latest = check_and_store_latest_ytdlp()
        status = ytdlp_ui_status()
        return jsonify({
            "status": "ok",
            "latest": latest,
            **status
        })
    except Exception as e:
        status = ytdlp_ui_status()
        return jsonify({
            "status": "error",
            "message": str(e),
            **status
        }), 400


@app.route("/api/yt-dlp/update", methods=["POST"])
def api_ytdlp_update():
    try:
        version = update_ytdlp_override()
        status = ytdlp_ui_status()
        return jsonify({
            "status": "ok",
            "message": f"yt-dlp updated to {version}.",
            **status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ── Webhooks ──────────────────────────────────────────────────────────────

def match_library_for_path(connection_id, folder_path):
    candidates = [
        lib for lib in get_libraries()
        if lib.get("connection_id") == connection_id
        and path_matches_library(folder_path, lib)
    ]

    # Prefer the most specific configured root path.
    candidates.sort(key=lambda lib: len(str(lib.get("root_path", ""))), reverse=True)
    return candidates[0] if candidates else None


def webhook_handler(connection_id=None):
    payload = request.get_json(force=True, silent=True) or {}
    event_type = payload.get("eventType", "")
    dry_run = bool(payload.get("dry_run", False))

    if event_type == "Test":
        notify(3066993, "🎬 Trailarr Parrk connected", "Webhook connection confirmed.")
        return jsonify({"status": "test_ok"})

    connection = get_connection(connection_id) if connection_id else None

    if "yt_id" in payload:
        title = payload.get("title", "Unknown")
        year = payload.get("year", "")
        output = payload.get("output", cfg("media_root"))
        try:
            output = safe_folder_path(output)
        except ValueError as e:
            return jsonify({"status": "rejected", "reason": str(e)}), 400

        out = out_path(output, title, year)
        if dry_run:
            return jsonify({"status": "dry_run", "would_save_to": f"{out}.mkv"})

        result = download(payload["yt_id"], out)
        if result["ok"]:
            record_activity({
                "status": "success",
                "action": "force",
                "source": "Webhook",
                "title": title,
                "year": year,
                "youtube_id": payload["yt_id"],
                "duration": result["duration"],
                "detail": "Manual webhook YouTube trailer downloaded."
            })
            return jsonify({"status": "downloaded", "saved_to": result["path"]})
        return jsonify({"status": "download_failed", "error": result["error"]}), 500

    if "movie" in payload:
        movie = payload["movie"]
        folder_path = movie.get("folderPath", "")

        library = match_library_for_path(connection_id, folder_path) if connection_id else None
        context = {
            "source": "Webhook",
            "library_id": library.get("id") if library else "",
            "library": library.get("name") if library else "",
            "arr_type": "radarr",
            "connection_id": connection_id or "",
            "connection": connection.get("name", "") if connection else ""
        }

        result, code = handle_grab(
            movie.get("title", "Unknown"),
            movie.get("year", ""),
            movie.get("tmdbId"),
            "movie",
            folder_path,
            dry_run=dry_run,
            context=context
        )
        return jsonify(result), code

    if "series" in payload:
        series = payload["series"]
        folder_path = series.get("path", "")

        if not media_folder_exists(folder_path):
            return jsonify({"status": "folder_missing"}), 200

        tvdb_id = series.get("tvdbId")
        tmdb_id = tvdb_to_tmdb(tvdb_id) if tvdb_id else None
        if not tmdb_id:
            return jsonify({"status": "no_tmdb_match"}), 200

        library = match_library_for_path(connection_id, folder_path) if connection_id else None
        context = {
            "source": "Webhook",
            "library_id": library.get("id") if library else "",
            "library": library.get("name") if library else "",
            "arr_type": "sonarr",
            "connection_id": connection_id or "",
            "connection": connection.get("name", "") if connection else ""
        }

        result, code = handle_grab(
            series.get("title", "Unknown"),
            series.get("year", ""),
            tmdb_id,
            "tv",
            folder_path,
            dry_run=dry_run,
            context=context
        )
        return jsonify(result), code

    return jsonify({"status": "ignored", "reason": "unrecognized payload"}), 200


@app.route("/hook", methods=["POST"])
def hook():
    return webhook_handler()


@app.route("/hook/<connection_id>", methods=["POST"])
def hook_connection(connection_id):
    if not get_connection(connection_id):
        return jsonify({"status": "connection_missing"}), 404
    return webhook_handler(connection_id)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "yt_dlp": ytdlp_versions()["active"]
    })


# ── Manual CLI ────────────────────────────────────────────────────────────

def cli():
    parser = argparse.ArgumentParser(description="Trailarr Parrk manual trailer grabber")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--yt-id", help="Specific YouTube video ID")
    source.add_argument("--tmdb-id", type=int, help="TMDB movie or TV ID")

    parser.add_argument("--type", choices=["movie", "tv"], default="movie")
    parser.add_argument("--title", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--output", default=cfg("media_root"))
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    try:
        output = safe_folder_path(args.output)
    except ValueError as e:
        log.error(str(e))
        raise SystemExit(1)

    context = {
        "source": "CLI",
        "library_id": "",
        "library": "",
        "arr_type": args.type
    }

    if args.yt_id:
        out = out_path(output, args.title, args.year)
        if args.dry_run:
            log.info(f"DRY RUN — would download: https://www.youtube.com/watch?v={args.yt_id}")
            log.info(f"DRY RUN — would save to: {out}.mkv")
            return

        result = download(args.yt_id, out)
        if not result["ok"]:
            log.error(result["error"])
            raise SystemExit(1)

        update_trailer_metadata(result["path"], {
            "title": args.title,
            "year": args.year,
            "youtube_id": args.yt_id,
            "tmdb_name": "Manual CLI selection",
            "tmdb_type": "Manual",
            "score": None,
            "matched_terms": [],
            "downloaded_at": utc_now(),
            "download_source": "CLI",
            "library_id": "",
            "library": "",
            "arr_type": args.type
        })
        record_activity({
            **context,
            "status": "success",
            "action": "force",
            "title": args.title,
            "year": args.year,
            "youtube_id": args.yt_id,
            "duration": result["duration"],
            "detail": "CLI trailer downloaded."
        })
        log.info(f"Downloaded trailer to: {result['path']}")
        return

    result, code = handle_grab(
        args.title,
        args.year,
        args.tmdb_id,
        args.type,
        output,
        dry_run=args.dry_run,
        context=context
    )

    log.info(json.dumps(result, indent=2))
    if code >= 400:
        raise SystemExit(1)


if __name__ != "__main__":
    start_background_jobs()


if __name__ == "__main__":
    cli()
