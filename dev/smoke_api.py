#!/usr/bin/env python3
"""Quick check of the read API against a running dev stack. Standard library only.

    python dev/smoke_api.py [http://localhost:8080]

Prints scan progress, counts, and the response time of repeated list requests.
"""
import json
import statistics
import sys
import time
import urllib.request

base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")


def get(path):
    t = time.perf_counter()
    with urllib.request.urlopen(base + path, timeout=30) as r:
        data = json.load(r)
    return data, (time.perf_counter() - t) * 1000


for _ in range(120):
    data, _ms = get("/api/items?per_page=10")
    if data["scan"]["state"] == "ready" and data["scan"]["total"]:
        break
    print(f"scanning... {data['scan']['done']}/{data['scan']['total']}")
    time.sleep(1)

ov, _ = get("/api/overview")
t = ov["totals"]
print(f"{t['all']} titles ({t['movies']} movies, {t['series']} shows): "
      f"{t['missing']} missing, {t['present']} with trailers, coverage {t['coverage']}%")
print("connections:", ", ".join(f"{c['name']}={'online' if c['online'] else 'OFFLINE'}" for c in ov["connections"]))
times = [get("/api/items?type=movie&per_page=25&page=1")[1] for _ in range(30)]
print(f"GET /api/items (25 rows): median {statistics.median(times):.1f} ms, worst {max(times):.1f} ms")
