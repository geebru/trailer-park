#!/usr/bin/env python3
"""Build a fake media library for local development.

Creates empty-ish video files in the folder layouts the engine recognises, plus
.dev-catalog.json, which dev/mock_arr.py serves as if it were Radarr/Sonarr.
Nothing here touches real media. Output is deterministic (fixed random seed).

    python make_media.py --out /data/media [--movies 250] [--shows 120] [--reset]

Trailer states produced (matching the default settings: folder "trailers",
template "{title} ({year}).trailer"):
    ok          one file at the configured name
    mismatched  one trailer file whose name does not match
    multiple    two or more trailer files
    missing     no trailer file
"""
import argparse
import json
import os
import random
import shutil

# (title, year, folder name as Radarr/Sonarr would write it, tmdb id, state)
# tmdb ids are real so Grab works with a TMDB key; verify any you rely on.
MOVIES = [
    ("Dune: Part Two", 2024, "Dune - Part Two (2024)", 693134, "ok"),
    ("The Wild Robot", 2024, "The Wild Robot (2024)", 1184918, "mismatched"),
    ("Civil War", 2024, "Civil War (2024)", 929590, "missing"),
    ("Furiosa: A Mad Max Saga", 2024, "Furiosa - A Mad Max Saga (2024)", 786892, "multiple"),
    ("The Substance", 2024, "The Substance (2024)", 933260, "missing"),
    ("Perfect Days", 2023, "Perfect Days (2023)", 976893, "ok_mp4"),
    ("Avengers: Infinity War", 2018, "Avengers - Infinity War (2018)", 299536, "ok"),
    ("Dune", 2021, "Dune (2021)", 438631, "multiple_nomatch"),
    ("Oppenheimer", 2023, "Oppenheimer (2023)", 872585, "mismatched_dir"),
]
MOVIES_NO_FILE = [("Upcoming Movie", 2027, "Upcoming Movie (2027)", 1)]   # Radarr hasFile=false
MOVIES_NO_FOLDER = [("Ghost Movie", 2022, "Ghost Movie (2022)", 2)]       # folder absent on disk
MOVIES_4K = [
    ("Blade Runner 2049", 2017, "Blade Runner 2049 (2017)", 335984, "ok"),
    ("Mad Max: Fury Road", 2015, "Mad Max - Fury Road (2015)", 76341, "missing"),
    ("Arrival", 2016, "Arrival (2016)", 329865, "mismatched"),
]
SHOWS = [
    ("Severance", 2022, "Severance (2022)", 95396, "ok"),
    ("Shōgun", 2024, "Shōgun (2024)", 126308, "mismatched"),
    ("The Bear", 2022, "The Bear (2022)", 136315, "missing"),
    ("Silo", 2023, "Silo (2023)", 125988, "multiple"),
    ("Fallout", 2024, "Fallout (2024)", 106379, "ok"),
    ("Arcane", 2021, "Arcane (2021)", 94605, "missing"),
]

WORDS_A = ["Silent", "Crimson", "Last", "Broken", "Golden", "Hidden", "Midnight", "Electric",
           "Paper", "Northern", "Burning", "Quiet", "Iron", "Velvet", "Lost", "Distant"]
WORDS_B = ["Harbor", "Empire", "Garden", "Signal", "Kingdom", "Orchard", "Voyage", "Circuit",
           "Letter", "Horizon", "Mirror", "Summit", "Archive", "Tide", "Station", "Parade"]


def write(path, size=64):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"dev-fixture\n" * max(1, size // 12))


def stem(title, year):
    # same transform as engine.filename_safe_title for the characters used here
    safe = title.replace(": ", " - ").replace(":", "-")
    return f"{safe} ({year}).trailer"


def make_trailers(folder, title, year, state):
    s = stem(title, year)
    if state in ("ok",):
        write(os.path.join(folder, "trailers", s + ".mkv"), 84_000)
    elif state == "ok_mp4":
        write(os.path.join(folder, "trailers", s + ".mp4"), 61_000)
    elif state == "mismatched":
        short = title.replace(": ", " ").replace(" ", ".")
        write(os.path.join(folder, f"{short}.{year}-trailer.mkv"), 52_000)
    elif state == "mismatched_dir":
        write(os.path.join(folder, "Trailers", f"{title}.mkv"), 47_000)
    elif state == "multiple":
        write(os.path.join(folder, "trailers", s + ".mkv"), 106_000)
        write(os.path.join(folder, f"{title.split(':')[0]}-Trailer.mp4"), 67_000)
        write(os.path.join(folder, f"{title.split(':')[0]} Official Trailer.mkv"), 46_000)
    elif state == "multiple_nomatch":
        write(os.path.join(folder, "trailers", f"{title} Official Trailer.mkv"), 40_000)
        write(os.path.join(folder, f"{title}-trailer.mp4"), 30_000)
    # "missing": nothing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/data/media")
    ap.add_argument("--movies", type=int, default=250, help="filler movies in addition to the scenario titles")
    ap.add_argument("--shows", type=int, default=120, help="filler shows in addition to the scenario titles")
    ap.add_argument("--reset", action="store_true", help="delete movies/, movies-4k/, tv/ first")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    rng = random.Random(1234)

    if a.reset:
        for d in ("movies", "movies-4k", "tv"):
            shutil.rmtree(os.path.join(out, d), ignore_errors=True)

    catalog = {"radarr_main": [], "radarr_4k": [], "sonarr_main": []}
    next_id = {"radarr_main": 1, "radarr_4k": 1, "sonarr_main": 1}

    def add(key, root, title, year, folder, tmdb, state, has_file=True, make_folder=True):
        path = f"/data/media/{root}/{folder}"
        disk = os.path.join(out, root, folder)
        if make_folder:
            os.makedirs(disk, exist_ok=True)
            if has_file and root != "tv":
                write(os.path.join(disk, f"{folder}.mkv"), 2_000)   # the "movie" itself
            if root == "tv":
                write(os.path.join(disk, "Season 01", f"{title} - S01E01.mkv"), 2_000)
            make_trailers(disk, title, year, state)
        catalog[key].append({
            "id": next_id[key], "title": title, "year": year, "path": path,
            "tmdbId": tmdb, "hasFile": has_file,
        })
        next_id[key] += 1

    for t, y, f, tm, st in MOVIES:
        add("radarr_main", "movies", t, y, f, tm, st)
    for t, y, f, tm in MOVIES_NO_FILE:
        add("radarr_main", "movies", t, y, f, tm, "missing", has_file=False)
    for t, y, f, tm in MOVIES_NO_FOLDER:
        add("radarr_main", "movies", t, y, f, tm, "missing", make_folder=False)
    for t, y, f, tm, st in MOVIES_4K:
        add("radarr_4k", "movies-4k", t, y, f, tm, st)
    for t, y, f, tm, st in SHOWS:
        add("sonarr_main", "tv", t, y, f, tm, st)

    weights = [("ok", 55), ("missing", 25), ("mismatched", 12), ("multiple", 8)]
    states = [s for s, w in weights for _ in range(w)]

    def filler(n, key, root, kind):
        seen = set()
        i = 0
        while i < n:
            title = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)}"
            year = rng.randint(1995, 2025)
            if (title, year) in seen:
                continue
            seen.add((title, year))
            add(key, root, title, year, f"{title} ({year})", 100000 + len(catalog[key]), rng.choice(states))
            i += 1

    filler(a.movies, "radarr_main", "movies", "movie")
    filler(a.shows, "sonarr_main", "tv", "show")

    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, ".dev-catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    print(f"Fake library written to {out}")
    for k, v in catalog.items():
        print(f"  {k}: {len(v)} titles")


if __name__ == "__main__":
    main()
