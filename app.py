import argparse
import json
import os

from flask import Flask, jsonify, redirect, render_template, request

import engine
from engine import *  # noqa: F401,F403  (see engine.py header)
import library_cache
from api import bp as api_bp


app = Flask(__name__)
app.register_blueprint(api_bp)


# ── Security headers ──────────────────────────────────────────────────────
# The front end is vanilla ES modules with self-hosted fonts, no CDN, no inline script or style and
# no outside images, so one strict policy fits every response (HTML, /api and static files).
# upgrade-insecure-requests is left out on purpose: this app is normally reached over plain HTTP on a LAN.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",       # older browsers; frame-ancestors covers the rest
}


@app.after_request
def add_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


# ── Web UI ────────────────────────────────────────────────────────────────
# One HTML shell; the front end routes between Overview, Trailers, Settings and Activity
# on the client. Everything else is the JSON API under /api (api.py).

@app.route("/", methods=["GET"])
@app.route("/trailers", methods=["GET"])
@app.route("/settings", methods=["GET"])
@app.route("/activity", methods=["GET"])
def ui_shell():
    return render_template("shell.html")


@app.route("/library/<library_id>", methods=["GET"])
@app.route("/app", defaults={"rest": ""})
@app.route("/app/<path:rest>")
def old_addresses(library_id=None, rest=""):
    """Bookmarks from before the new UI."""
    return redirect("/trailers" if library_id else f"/{rest}", code=301)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": {"code": "not_found", "message": "No such endpoint."}}), 404
    return render_template("shell.html"), 404     # the front end draws its own "not found" page


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "yt_dlp": ytdlp_versions()["active"]
    })


# ── Manual CLI ────────────────────────────────────────────────────────────

def cli():
    parser = argparse.ArgumentParser(description="Trailer Park manual trailer grabber")
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
    library_cache.start()


if __name__ == "__main__":
    cli()
