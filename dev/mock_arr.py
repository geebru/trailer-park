#!/usr/bin/env python3
"""Tiny stand-in for Radarr / Sonarr, for local development only.

Serves the few /api/v3 endpoints Trailer Park calls, from the catalog that
make_media.py writes. Standard library only.

    python mock_arr.py --type radarr --key main --port 7878 [--api-key devkey] [--latency-ms 0]

--key selects the catalog list: radarr_main, radarr_4k or sonarr_main.
The catalog is re-read on every request, so regenerating the media tree
updates the "Arr" immediately.
"""
import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(args):
    def items():
        with open(args.catalog, encoding="utf-8") as f:
            return json.load(f).get(args.key, [])

    def radarr_movie(i):
        return {
            "id": i["id"], "title": i["title"], "year": i["year"], "path": i["path"],
            "tmdbId": i["tmdbId"], "monitored": i.get("monitored", True), "hasFile": i["hasFile"],
            "movieFile": {"id": 1000 + i["id"]} if i["hasFile"] else None,
            "movieFileId": 1000 + i["id"] if i["hasFile"] else 0,
        }

    def sonarr_series(i):
        return {
            "id": i["id"], "title": i["title"], "year": i["year"], "path": i["path"],
            "tmdbId": i["tmdbId"], "tvdbId": None, "imdbId": "", "monitored": i.get("monitored", True),
        }

    shape = radarr_movie if args.type == "radarr" else sonarr_series
    noun = "movie" if args.type == "radarr" else "series"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            print(f"[mock-{args.type}:{args.key}] {self.command} {self.path}", flush=True)

        def send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if args.latency_ms:
                time.sleep(args.latency_ms / 1000)
            if self.headers.get("X-Api-Key") != args.api_key:
                return self.send(401, {"message": "Unauthorized"})
            path = self.path.split("?")[0].rstrip("/")
            if path == "/api/v3/system/status":
                return self.send(200, {"appName": args.type.capitalize(), "version": "99.0.0.dev"})
            if path == "/api/v3/rootfolder":
                roots = sorted({i["path"].rsplit("/", 1)[0] for i in items()})
                return self.send(200, [{"id": n + 1, "path": p} for n, p in enumerate(roots)])
            if path == f"/api/v3/{noun}":
                return self.send(200, [shape(i) for i in items()])
            m = re.fullmatch(rf"/api/v3/{noun}/(\d+)", path)
            if m:
                for i in items():
                    if i["id"] == int(m.group(1)):
                        return self.send(200, shape(i))
                return self.send(404, {"message": "NotFound"})
            return self.send(404, {"message": "NotFound"})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["radarr", "sonarr"], required=True)
    ap.add_argument("--key", required=True, help="catalog list: radarr_main | radarr_4k | sonarr_main")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--api-key", default="devkey")
    ap.add_argument("--catalog", default="/data/media/.dev-catalog.json")
    ap.add_argument("--latency-ms", type=int, default=0, help="delay every response (simulate a slow Arr)")
    args = ap.parse_args()
    print(f"mock {args.type} ({args.key}) on :{args.port}, api key '{args.api_key}'", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args)).serve_forever()


if __name__ == "__main__":
    main()
