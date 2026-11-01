#!/usr/bin/env python3
"""Start, stop and inspect this checkout's dev stack. Standard library only.

    python dev/stack.py up [--fresh-media]   # start (or reuse) the stack, print its URL
    python dev/stack.py status               # print the URL and whether it is healthy
    python dev/stack.py down                 # stop and remove this checkout's stack

Each checkout (main folder or worktree) gets its own compose project, container name and a free
port from 8100 up, so it never touches a stack on 8080 or one started from another checkout.
`up` also creates dev/config/settings.json and dev/media when they are missing.
Set TMDB_API_KEY in the environment before `up` to make Grab work.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "dev"
STATE = DEV / ".stack.json"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.dev.yml")]
PORTS = range(8100, 8200)

slug = re.sub(r"[^a-z0-9]+", "-", ROOT.name.lower()).strip("-")[:24]
NAME = f"tp-{slug}-{hashlib.sha1(str(ROOT).encode()).hexdigest()[:4]}"


def fail(msg):
    sys.exit(f"stack: {msg}")


def compose(*args, port=None, quiet=True):
    env = {**os.environ, "DEV_CONTAINER": NAME}
    if port:
        env["DEV_PORT"] = str(port)
    cmd = [*COMPOSE, "-p", NAME, *args]
    r = subprocess.run(cmd, env=env, capture_output=quiet, text=True)
    if r.returncode:
        out = (r.stdout or "") + (r.stderr or "")
        fail(f"`docker compose {' '.join(args)}` failed:\n" + "\n".join(out.strip().splitlines()[-20:]))


def port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def free_port():
    for port in PORTS:
        if port_free(port):
            return port
    fail(f"no free port in {PORTS.start}-{PORTS.stop - 1}")


def saved():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def healthy(port, wait=0):
    deadline = time.time() + wait
    while True:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(1)


def media_ready():
    media = DEV / "media"
    return media.is_dir() and any(media.iterdir())


def up(fresh_media):
    if subprocess.run(["docker", "info"], capture_output=True).returncode:
        fail("Docker is not running. Start Docker Desktop and wait until it says running.")
    settings = DEV / "config" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEV / "settings.template.json", settings)
        print("created dev/config/settings.json")
    if fresh_media or not media_ready():
        print("building dev/media ...")
        compose("run", "--rm", "make-media")
    port = saved().get("port")
    if port and healthy(port):
        print(f"already running: http://localhost:{port}")
        return
    port = port if port and port_free(port) else free_port()
    print(f"starting {NAME} on port {port} ...")
    compose("up", "-d", "--build", port=port)
    if not healthy(port, wait=90):
        fail(f"started but /health did not answer on port {port}; see `docker logs {NAME}`")
    STATE.write_text(json.dumps({"name": NAME, "port": port}))
    print(f"ready: http://localhost:{port}")


def status():
    port = saved().get("port")
    if not port:
        print(f"{NAME}: not running")
    else:
        print(f"{NAME}: http://localhost:{port} " + ("healthy" if healthy(port) else "not answering"))


def down():
    compose("down", "--remove-orphans")
    STATE.unlink(missing_ok=True)
    print(f"stopped {NAME}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up", help="start or reuse this checkout's stack")
    u.add_argument("--fresh-media", action="store_true", help="rebuild dev/media even if it exists")
    sub.add_parser("status", help="show URL and health")
    sub.add_parser("down", help="stop and remove the stack")
    args = p.parse_args()
    {"up": lambda: up(args.fresh_media), "status": status, "down": down}[args.cmd]()


if __name__ == "__main__":
    main()
