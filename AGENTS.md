# Trailer Park: agent notes

Flask + Waitress app that grabs trailers (TMDB + yt-dlp) for Radarr/Sonarr titles. Owner prefers simple, direct solutions. Remote is GitHub (`geebru/trailer-park`).

## Layout
- `engine.py`: all logic, no Flask. Nothing imports `app`.
- `api.py`: JSON API blueprint at `/api`. `app.py`: HTML shell routes, `/health`, CLI.
- `jobs.py`: in-memory jobs and batches. `library_cache.py`: item snapshots, rescans in the background.
- `templates/shell.html` + `static/ui/` is the whole front end. No build step.
- `dev/`: mock Arrs, fake media, `docker-compose.dev.yml` (bind-mounts source; restart the container to pick up edits).
- `Dockerfile` copies files one by one and `.dockerignore` is an allowlist: a new module or folder the app needs must be added to both, or the image will not have it. Flask and Waitress are pinned in `requirements.txt`; yt-dlp is deliberately not.

## Front end rules
- Vanilla ES modules, `h()` element builder, client-side History router. No frameworks, no Tailwind, no CDN.
- Style only through tokens in `css/tokens.css` (palette, then semantic layer). Theme is Moss (`data-theme`).
- Icons: Font Awesome Free SVGs in `js/icons.js`. Fonts are self-hosted.
- Modals use native `<dialog>` (`dialog.js`). Filters live in the URL. Keep a11y clean (axe AA, visible focus).
- A button that can be disabled uses `setDisabled(button, reason)` from `tip.js` (empty reason enables it), never the `disabled` attribute, so every disabled action explains itself on hover, focus and tap. Native `disabled` stays for form fields, with a visible hint.
- Add a page: route in `main.js`, module in `pages/` exporting `title` and `mount(container, {query, navigate})` (may return cleanup).

## API conventions
- Mutating requests need `Content-Type: application/json` (else 415). Errors: `{"error":{"code","message"}}`.
- Long actions return 202 `{"job":{...}}`; poll `GET /api/jobs/<id>?after=<seq>`. One active job per item (409 `job_active`).
- Items are addressed `/api/items/<connection_id>/<item_id>`. No library IDs; each connection is one synthetic library.
- Secrets (TMDB key, Discord webhook) are never returned, only `configured` flags. Settings PUT is partial; `clear_<key>: true` clears a secret.

## Behavior to keep
- Missing = no trailer file under any name. File actions only touch detected trailers, never media files.
- Replace/Force delete old files only after the new download succeeds. Renames never overwrite.
- `matches_naming` ignores the extension, so changing mkv/mp4 never flags "Name mismatch".
- Batches: one at a time, children are normal jobs, one Discord summary.
- The automatic trigger is the API watcher only (no webhooks).

## Checking changes
- Python: `python -m py_compile engine.py api.py app.py jobs.py library_cache.py`, then exercise endpoints with Flask's test client or the dev stack. `engine.py` imports `fcntl`, so it only runs in Docker/Linux, not natively on Windows.
- Front end: load the page in the browser pane and check the console. Scan every page the change touches with the vendored axe-core at 1280 px and 390 px, following `dev/axe/README.md` (serve `dev/axe` on port 8090, paste `dev/axe/scan.js`). Do not download another copy of axe-core or any other script without asking the owner. Any violation is yours to explain or fix.
- Dev stack, from the checkout you are working in: `python dev/stack.py up|status|down` (creates settings and fake media if missing, picks a free port from 8100 and a name unique to this checkout; details in `dev/README.md`). Restart the app container after Python edits (`docker restart <name>`, name from `status`); refresh the browser after template/static edits. The owner's stack may run on 8080: only ever stop or remove containers you started.
- Do not leave test fixtures in `dev/media`; reset with `dev/make_media.py --reset`.

## Keep docs in step
Before every commit, ask what the change makes wrong, and fix it in the same commit. Skipping this is how information is lost. The PR says which of these were updated, or why none:
- Behavior, settings, UI, install or upgrade steps: `README.md`. `CHANGELOG.md` is generated: never edit it.
- Layout, the rules in this file (API conventions, "Behavior to keep", workflow), permissions: this file, the skills in `.claude/skills/` that restate it, and `.claude/settings.json`.
- Dev stack, mock Arrs, axe: `dev/README.md`, `dev/axe/README.md`.
- Docker, CI, release: `CONTRIBUTING.md` (release checklist) and Releases below.
- Issue and PR templates: `.github/`.

Keep these files lean: each fact lives in one place, link instead of repeating, and delete what a change makes obsolete instead of adding a note beside it. They must not grow with every change.

## GitHub
- The `gh` CLI reads and writes issues and PRs. The owner logs in with `gh auth login`; never ask for, print, read back or commit a token. Never read `dev/config`.
- Issue and PR titles use the Conventional Commit form `type(scope): subject` (types and scopes under Workflow). The "Title format" workflow checks it, fails a PR with a bad title, and sets the type label from the title: `feat` is `enhancement`, `fix` is `bug`, `docs` is `documentation`, anything else is `chore`. Do not set those labels by hand. `question` is a manual label for an issue whose deliverable is an answer, not code.
- There are no status labels. Whether an issue is ready, needs a decision or needs information lives in the conversation on the issue; `/triage` reports it and asks before posting anything.
- `main` is the only long-lived branch. Branch from it and open PRs against it. The owner protects it in the repo settings: a PR is required, squash merge only, the "Title format" check must pass, no force pushes, no deletion. The owner squash-merges on GitHub. Push to `origin` only (never `izsez` or `gitea`).

## Releases
- release-please keeps one open release PR built from the commit history on `main`. The owner merges it: that tags `vX.Y.Z`, creates the GitHub Release and rewrites `APP_VERSION` in `engine.py` and the README release line (both carry an `x-release-please-version` marker: keep it). Never edit those versions, add release changelog sections, or hand-edit the release PR: it is regenerated on every push to `main`, so get a good result from the commit instead.
- The commit type decides the changelog section and the bump (before 1.0). Visible types open or update the release PR: `feat` (✨ Features) and breaking changes bump the minor version, every other visible type bumps the patch. Visible: `feat`, `fix` (🐛 Bug fixes), `perf` (⚡ Performance), `docs` (📝 Documentation), `revert`, and `test`, `refactor`, `chore`, `style` (Other changes). Hidden, so no notes and no release: `agent` (`AGENTS.md`, `CLAUDE.md`, `.claude/`), `ci` (workflows, Dependabot, release config) and `build`. Pick the type by what users see: a change users must act on is `feat!` or `fix!`.
- A breaking change (container name, script path, settings or API shape, a removed feature) puts `!` after the type and a `BREAKING CHANGE:` note in both the commit footer and the PR description (the squash message can be built from either). Write it as a one-line headline of what changed, then what to do: it prints alone under "BREAKING CHANGES", without the commit subject.
- Config: `release-please-config.json`, `.release-please-manifest.json`, `.github/workflows/release-please.yml`. When a release is created that workflow scans the full history for secrets (`secrets-scan.yml`, TruffleHog), then builds, smoke tests and pushes the multi-arch image to GHCR (`image.yml`) as `X.Y.Z`, `X.Y`, `latest` and, from 1.0, `X`. Both also run on PRs (the image one when the image changes): a failure is real, fix it. By hand, "Secret scan" scans the whole history and "Docker image" pushes a throwaway `test` tag.
- Every third-party Action is pinned to a commit SHA with its version in a comment. Dependabot moves the pins but not the TruffleHog `version` input: change it with the action tag.

## Workflow
The skills in `.claude/skills/` hold the steps; this file holds the rules they rely on.
- `/triage` reports on the backlog and changes nothing until the owner approves.
- `/work-issue <N>` reads the issue, works in a worktree on `<type>/<issue>-<slug>` cut from a fresh `origin/main` (e.g. `fix/31-tooltip-z-index`), verifies, commits, then stops with a review package: what was wrong and why, files and commits, before/after evidence, checks run, risks, what could not be verified. It never pushes, and asks first when the issue is vague or needs a decision.
- `/preview` starts a local copy of the branch for the owner to try.
- `/ship`, only after the owner approves, pushes to `origin` and opens the PR against `main`: the title is a valid Conventional Commit under 72 characters (it becomes the squash commit; GitHub appends `(#N)`), the body follows `.github/PULL_REQUEST_TEMPLATE.md` and ends with `Resolves #N`, and the workflow sets the label. Then it stops; the owner merges.

By type (the title's prefix):
- `fix`: reproduce first (dev stack, browser at 1280 px and 390 px) and keep before-evidence. Find the root cause, make the smallest fix, confirm the repro is gone, check neighbouring behavior. If you cannot reproduce it, say what you tried instead of guessing.
- `feat`: restate the acceptance criteria in two or three lines. If it changes the API contract, anything under "Behavior to keep", or needs a design call (new page, new setting), stop and ask before building. Follow the front end and API rules and run axe.
- `docs`, `chore`, `refactor`, `ci`, `agent` and the rest: no behavior change; keep the diff small.
- Label `question`: draft the answer for the owner. No code.
- After two honest failed attempts at a fix, stop and report.

Commits (no need to ask), Conventional Commits `type(scope): subject`:
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, and `agent` (agent files only; see Releases).
- Scope is the area, lowercase (`nav`, `sidebar`, `services`, `activity`, `jobs`, `settings`, `trailers`, `api`, `engine`). Omit it for repo-wide changes.
- Subject is imperative, lowercase, no period, under 72 characters. The body says why. Footer `Resolves #N` (finishes the issue) or `Refs #N` (part of it).
- One logical change per commit; no unrelated edits or formatting churn.
- Commits are GPG-signed. If signing fails or waits on a passphrase, stop and tell the owner. Never use `--no-verify` or `--no-gpg-sign`.

Never: merge a PR (`gh pr merge`), close an issue by hand, push to `main`, force-push, rewrite pushed history, or commit secrets or media. Ask before: adding a dependency, changing a settings or API shape, deleting a feature, or touching anything outside the issue's scope.
