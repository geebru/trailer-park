#!/usr/bin/env python3
"""Small Gitea client for issues and pull requests. Standard library only.

    python scripts/gitea.py issues [--label bug] [--state open|closed|all]
    python scripts/gitea.py issue 31
    python scripts/gitea.py new --title "..." --body-file body.md --label bug
    python scripts/gitea.py comment 31 "text"            (use - to read the text from stdin)
    python scripts/gitea.py labels
    python scripts/gitea.py new-label --name agent-ready --color 0e8a16 --description "..."
    python scripts/gitea.py label 31 --add agent-ready --remove needs-info
    python scripts/gitea.py pr --title "fix(nav): ..." --head fix/31-slug --body-file body.md --label bug
                               [--base tp-ui]
    python scripts/gitea.py pr-status [BRANCH]           (PR for a branch, default: the current one)

Reads are public. Writes need GITEA_TOKEN (environment or .env; see .env.example).
From a worktree, the .env of the main checkout is used, so the token lives in one place.
The server and repo come from the `origin` remote unless GITEA_URL / GITEA_REPO are set.
Add --dry-run before the command to print a write instead of sending it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = "tp-ui"  # integration branch; PRs do not go to main


def main_checkout(root):
    """The primary working tree. A worktree has none of the ignored files, such as .env."""
    out = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    first = out.stdout.splitlines()[0] if out.returncode == 0 and out.stdout else ""
    return Path(first.removeprefix("worktree ")) if first.startswith("worktree ") else root


def load_dotenv():
    """Read GITEA_* settings from .env in this checkout, else in the main one. Nothing else is loaded."""
    root = Path(__file__).resolve().parent.parent
    for folder in (root, main_checkout(root)):
        path = folder / ".env"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip().startswith("GITEA_"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def server_and_repo():
    url, repo = os.environ.get("GITEA_URL"), os.environ.get("GITEA_REPO")
    if not (url and repo):
        m = re.match(r"(https?://[^/]+)/(.+?)(?:\.git)?$", git("remote", "get-url", "origin"))
        if not m:
            sys.exit("Cannot work out the Gitea server from the origin remote; set GITEA_URL and GITEA_REPO.")
        url, repo = url or m.group(1), repo or m.group(2)
    return url.rstrip("/"), repo


def request(method, path, body=None, dry_run=False):
    server, repo = server_and_repo()
    url = f"{server}/api/v1/repos/{repo}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if os.environ.get("GITEA_TOKEN"):
        headers["Authorization"] = f"token {os.environ['GITEA_TOKEN']}"
    elif method != "GET" and not dry_run:
        sys.exit("GITEA_TOKEN is not set. Create one in Gitea (Settings -> Applications) and put it in .env.")
    if dry_run and method != "GET":
        print(f"{method} {url}\n{json.dumps(body, indent=2)}")
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Gitea answered {e.code} for {method} {path}: {e.read().decode(errors='replace')[:300]}")


def label_ids(names):
    if not names:
        return []
    known = {label["name"].lower(): label["id"] for label in request("GET", "/labels?limit=100")}
    unknown = [n for n in names if n.lower() not in known]
    if unknown:
        sys.exit(f"Unknown label(s): {', '.join(unknown)}. Known: {', '.join(sorted(known))}")
    return [known[n.lower()] for n in names]


def list_labels(args):
    for label in request("GET", "/labels?limit=100"):
        print(f"{label['name']:<14} #{label['color']}  {label['description']}")


def new_label(args):
    payload = {"name": args.name, "color": args.color.lstrip("#"), "description": args.description}
    if request("POST", "/labels", payload, args.dry_run):
        print(f"created label {args.name}")


def edit_labels(args):
    """Add and remove labels on an issue; other labels are left alone."""
    path = f"/issues/{args.number}/labels"
    if args.add:
        request("POST", path, {"labels": label_ids(args.add)}, args.dry_run)
    for lid in label_ids(args.remove):
        request("DELETE", f"{path}/{lid}", None, args.dry_run)
    if not args.dry_run:
        print(", ".join(label["name"] for label in request("GET", path)) or "no labels")


def show_issue(args):
    issue = request("GET", f"/issues/{args.number}")
    labels = ", ".join(label["name"] for label in issue["labels"]) or "none"
    print(f"#{issue['number']} {issue['title']}  [{issue['state']}]  labels: {labels}")
    print(f"{issue['html_url']}\n\n{issue['body'] or '(no description)'}")
    for c in request("GET", f"/issues/{args.number}/comments"):
        print(f"\n--- {c['user']['login']} ({c['created_at'][:10]})\n{c['body']}")


def list_issues(args):
    query = {"type": "issues", "state": args.state, "limit": 50}
    if args.label:
        query["labels"] = args.label
    for i in request("GET", "/issues?" + urllib.parse.urlencode(query)):
        print(f"#{i['number']:<4} [{i['state']}] {i['title']}  ({', '.join(label['name'] for label in i['labels'])})")


def add_comment(args):
    text = sys.stdin.read() if args.text == "-" else args.text
    result = request("POST", f"/issues/{args.number}/comments", {"body": text}, args.dry_run)
    if result:
        print(result["html_url"])


def new_issue(args):
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
    payload = {"title": args.title, "body": body, "labels": label_ids(args.label)}
    result = request("POST", "/issues", payload, args.dry_run)
    if result:
        print(f"#{result['number']} {result['html_url']}")


def open_pr(args):
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
    payload = {"title": args.title, "head": args.head, "base": args.base, "body": body,
               "labels": label_ids(args.label)}
    result = request("POST", "/pulls", payload, args.dry_run)
    if result:
        print(result["html_url"])


def pr_status(args):
    branch = args.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    pulls = request("GET", "/pulls?state=all&limit=50")
    match = [p for p in pulls if p["head"]["ref"] == branch]
    if not match:
        sys.exit(f"No pull request found for branch {branch}.")
    p = match[0]
    state = "merged" if p["merged"] else p["state"]
    print(f"#{p['number']} [{state}] {p['title']} -> {p['base']['ref']}\n{p['html_url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print writes instead of sending them")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("issues")
    p.add_argument("--label")
    p.add_argument("--state", default="open", choices=["open", "closed", "all"])
    p.set_defaults(run=list_issues)

    p = sub.add_parser("issue")
    p.add_argument("number", type=int)
    p.set_defaults(run=show_issue)

    p = sub.add_parser("new")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file")
    p.add_argument("--label", action="append", default=[])
    p.set_defaults(run=new_issue)

    sub.add_parser("labels").set_defaults(run=list_labels)

    p = sub.add_parser("new-label")
    p.add_argument("--name", required=True)
    p.add_argument("--color", required=True, help="hex, e.g. 0e8a16")
    p.add_argument("--description", default="")
    p.set_defaults(run=new_label)

    p = sub.add_parser("label")
    p.add_argument("number", type=int)
    p.add_argument("--add", action="append", default=[])
    p.add_argument("--remove", action="append", default=[])
    p.set_defaults(run=edit_labels)

    p = sub.add_parser("comment")
    p.add_argument("number", type=int)
    p.add_argument("text")
    p.set_defaults(run=add_comment)

    p = sub.add_parser("pr")
    p.add_argument("--title", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--body-file")
    p.add_argument("--label", action="append", default=[])
    p.set_defaults(run=open_pr)

    p = sub.add_parser("pr-status")
    p.add_argument("branch", nargs="?")
    p.set_defaults(run=pr_status)

    args = parser.parse_args()
    load_dotenv()
    args.run(args)


if __name__ == "__main__":
    main()
