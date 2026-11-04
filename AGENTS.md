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
- Front end: load the page in the browser pane and check the console. Scan every page the change touches with the vendored axe-core at 1280 px and 390 px, following `dev/axe/README.md` (serve `dev/axe` on port 8090, paste `dev/axe/scan.js`). Do not download another copy. Any violation is yours to explain or fix.
- Dev stack (from the checkout you are working in): `python dev/stack.py up` creates the settings and fake media if missing, picks a free port (8100 up) and a name unique to this checkout, and prints the URL. `status` shows it; `down` stops it when finished. Restart the app container after Python edits (`docker restart <name>`, name from `status`); refresh the browser after template/static edits. Details in `dev/README.md`.
- The owner's own stack may be running on 8080. The script never touches it, and you must only ever stop or remove containers you started.
- Do not leave test fixtures in `dev/media`; reset with `dev/make_media.py --reset`.

## GitHub
- The `gh` CLI reads and writes issues and PRs. The owner logs in with `gh auth login`; never ask for, print, read back or commit a token. Never read `dev/config`.
- Issue and PR titles use the Conventional Commit form `type(scope): subject` (types and scopes under Work phase). The "Title format" workflow checks it, fails a PR with a bad title, and sets the type label from the title: `feat` is `enhancement`, `fix` is `bug`, `docs` is `documentation`, anything else is `chore`. Do not set those labels by hand. `question` is a manual label for an issue whose deliverable is an answer, not code.
- There are no status labels. Whether an issue is ready, needs a decision or needs information lives in the conversation on the issue; `/triage` reports it and asks before posting anything.
- `main` is the only long-lived branch. Branch from it and open PRs against it. The owner protects it in the repo settings: a PR is required, squash merge only (default message is the PR title and description), the "Title format" check must pass, no force pushes, no deletion. The owner squash-merges on GitHub. Push to `origin` only (never `izsez` or `gitea`).

## Releases
- release-please keeps one open release PR built from the commit history on `main`. Merging it (the owner only) tags `vX.Y.Z`, creates the GitHub Release and rewrites the version in `engine.py` (`APP_VERSION`) and the README release line. Both carry an `x-release-please-version` marker: keep it, and never edit those versions or add changelog sections for a release by hand. To fix awkward generated notes, edit the release PR itself (its `CHANGELOG.md` and its description, which becomes the GitHub Release notes) shortly before the owner merges it; release-please rewrites that PR whenever another commit lands on `main`.
- The commit type decides the bump (before 1.0) and the changelog heading: `feat` is a minor bump under Features, `fix` and `perf` a patch, and `docs`, `chore`, `ci`, `style`, `refactor`, `test` and `build` do not release. Pick the type by what users see: a change users must act on is `feat!` or `fix!`, because `chore!` and `refactor!` land under "Miscellaneous Chores" or a hidden heading.
- A breaking change (container name, script path, settings or API shape, a removed feature) puts `!` after the type, as in `feat!: ...`, and a `BREAKING CHANGE:` note. release-please reads the squash commit message, which is built from the commit messages or from the PR description depending on the repo's squash default, so put the note in both: in the footer of the commit that makes the change and in the PR description.
- Write that note as a one-line headline of what changed, then what to do. It is printed under "BREAKING CHANGES" on its own, without the commit subject.
- Config is in `release-please-config.json` and `.release-please-manifest.json`; the workflow is `.github/workflows/release-please.yml`.
- When a release is created, that workflow scans the full history for secrets (`secrets-scan.yml`, TruffleHog) and then builds, smoke tests and pushes the multi-arch image to GHCR (`image.yml`), tagged `X.Y.Z`, `X.Y`, `latest`, and `X` from 1.0. The scan runs on every PR too, and `image.yml` runs on any PR that touches the image, so a failing check there is a real problem: fix it, do not skip it. Running either workflow by hand: "Secret scan" scans the whole history, "Docker image" pushes a throwaway `test` tag.
- Every third-party Action is pinned to a full commit SHA with its version in a comment; Dependabot moves the pins. The TruffleHog `version` input is not moved by Dependabot: change it together with the action tag.

## Workflow
Four skills drive it: `/triage` reports on the backlog (changes nothing until the owner approves); `/work-issue <N>` does the work and stops for review; `/preview` starts a local copy of the current branch for the owner to try by hand; `/ship` runs only after the owner approves. Point `/work-issue` at any issue; it asks first when the issue is vague or needs a decision.

**Work phase (`/work-issue`)**
1. Read the issue and its comments (`gh issue view N --comments`). Work in an isolated worktree on branch `<type>/<issue>-<slug>` cut from a fresh `origin/main`, e.g. `fix/31-tooltip-z-index`.
2. By type (the title's prefix):
   - `fix`: reproduce first (dev stack, browser at 1280 px and 390 px) and keep before-evidence. Find the root cause, make the smallest fix, confirm the repro is gone, check neighbouring behavior. If you cannot reproduce it, say what you tried instead of guessing.
   - `feat`: restate the acceptance criteria in two or three lines. If it changes the API contract, anything under "Behavior to keep", or needs a design call (new page, new setting), stop and ask before building. Follow the front end and API rules, run axe, update README/CHANGELOG when user-visible.
   - `docs`, `chore`, `refactor`, `ci` and the rest: no behavior change; keep the diff small.
   - Label `question`: draft the answer for the owner. No code.
3. Verify with the checks above that fit the change. If something still fails after two honest attempts, stop and report.
4. Commit on the branch, no need to ask. Conventional Commits, `type(scope): subject`:
   - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
   - Scope is the area, lowercase (`nav`, `sidebar`, `services`, `activity`, `jobs`, `settings`, `trailers`, `api`, `engine`). Omit it for repo-wide changes.
   - Subject is imperative, lowercase, no period, under 72 characters. The body says why. Footer `Resolves #N` (finishes the issue) or `Refs #N` (part of it).
   - One logical change per commit; no unrelated edits or formatting churn.
   - Commits are GPG-signed. If signing fails or waits on a passphrase, stop and tell the owner. Never use `--no-verify` or `--no-gpg-sign`.
5. **Stop and hand over a review package**: what was wrong and why, what changed (files and commit list), before/after evidence, checks run and results, risks, and what you could not verify. Do not push.

**Ship phase (`/ship`)**, only after the owner says the work is approved: push the branch to `origin`, open a PR against `main` with `gh pr create`, and report the link. The PR title must be a valid Conventional Commit under 72 characters (it becomes the squash commit; GitHub appends `(#N)`). The body follows `.github/PULL_REQUEST_TEMPLATE.md` and ends with `Resolves #N`. The workflow labels the PR, so do not set a label. Then stop; the owner merges.

Never: merge a PR (`gh pr merge`), close an issue by hand, push to `main`, force-push, rewrite pushed history, or commit secrets or media. Ask before: adding a dependency, changing a settings or API shape, deleting a feature, or touching anything outside the issue's scope.
