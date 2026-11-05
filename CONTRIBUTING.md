# Contributing to Trailer Park

Thank you for helping improve Trailer Park. This project downloads and manages local trailers for Radarr and Sonarr libraries using TMDB and yt-dlp.

This guide applies to the v0.7.0 codebase. Please read the [README](README.md) and [CHANGELOG](CHANGELOG.md) before making changes.

Issues, pull requests and releases are handled in the project's Git repository (the one you cloned from).

## Before you start

- Check existing issues and pull requests before starting substantial work.
- For significant features or behavioral changes, open an issue first to discuss the intended behavior and compatibility implications.
- Keep pull requests focused. Separate unrelated bug fixes, refactoring, and features.
- Never include API keys, TMDB tokens, Discord webhook URLs, personal media paths, or downloaded media in issues, logs, or commits.

## Project structure

| Path | Purpose |
| --- | --- |
| `app.py` | Flask application, integrations, download handling, batch processing, and CLI |
| `templates/` | Web UI templates for libraries, settings, and activity |
| `Dockerfile` | Python 3.12 Alpine container with runtime dependencies |
| `docker-compose.yml` | Example deployment configuration |
| `README.md` | Setup, configuration, and usage documentation |
| `CHANGELOG.md` | Release history |

Runtime state is stored under `/config` and must not be committed.

## Local development

Docker is the recommended way to reproduce the supported runtime.

1. Clone the repository and enter its directory:

   ```bash
   git clone https://github.com/geebru/trailer-park.git
   cd trailer-park
   ```

2. Copy or adapt `docker-compose.yml` for your environment.
3. Replace `/path/to/media` with a **test media directory** that you can safely modify. Keep `./config:/config` for persistent settings.
4. Ensure the external Docker network `media-network` exists, or adjust the Compose network configuration for your setup.
5. Build and start the application:

   ```bash
   docker compose up -d --build
   ```

6. Open `http://localhost:8080` (or your Docker host's address) and configure test integrations.
7. Follow application logs while developing:

   ```bash
   docker compose logs -f trailer-park
   ```

8. Rebuild after modifying application code or templates:

   ```bash
   docker compose up -d --build
   ```

The container uses Python 3.12, Flask, Waitress, yt-dlp, ffmpeg, and Deno. If you modify dependencies or the runtime, update the Dockerfile and document why.

**Important:** Trailer Park does not include built-in authentication. Do not expose a development instance directly to the public internet.

## Coding guidelines

- Follow the existing Python style and naming conventions in `app.py`; favor readable, narrowly scoped changes.
- Preserve compatibility with the existing Flask routes, HTML templates, CLI arguments, and documented settings wherever possible.
- Validate external input, including settings, webhook payloads, IDs, paths, and API responses.
- Avoid adding new dependencies unless necessary. Explain additions in the pull request.
- Keep user-visible messages clear and actionable.
- Do not log secrets or include sensitive values in exception messages.
- If changing settings formats, provide backward-compatible handling or an explicit migration path. Existing v0.5.x settings migration must continue to work.

## File safety and download behavior

Media operations require extra care:

- Keep every trailer write, replacement, and deletion within the configured media root. Do not weaken path validation or containment checks.
- Test filenames containing spaces, Unicode, brackets, and other special characters. In particular, paths such as `[tmdbid-123456]` must work without shell or glob expansion problems.
- Preserve safe temporary-file handling and cleanup when downloads fail or are cancelled.
- Do not overwrite or delete an existing trailer unless the requested operation explicitly permits it.
- Respect the cross-process download-slot locking used by the web UI, batch jobs, webhooks, and CLI. The configured concurrency limit is 1–4 downloads.
- Preserve cancellation semantics: cancellation prevents queued downloads from starting but allows already-active downloads to finish safely.
- Keep activity logging and trailer metadata consistent with actual file outcomes.
- Never create a media folder. Trailers are only written into a folder the Arr has already created; a missing folder is a `folder_missing` result, not something to fix by `makedirs`.
- Every path that gives up on a grab must leave a trace: an Activity entry, or at least a container log line. No silent `return`.

## Integrations and persistent data

- **Radarr/Sonarr:** Support multiple connections and libraries, including root-path filters. Avoid duplicate library matches and preserve connection-specific webhook behavior.
- **Automatic grabs:** there are two triggers, and both must stay safe to run together. The webhook acts only on `Download` (Radarr/Sonarr import/upgrade) and Sonarr `SeriesAdd`; `Grab` and `MovieAdded` are deferred, everything else is ignored. The API watcher detects Radarr file-ID changes (import/upgrade) and new Sonarr series, records a baseline on its first check, and never backfills. Both pass `skip_existing=True`, so whichever runs second is a no-op.
- **TMDB languages:** `/videos` returns English only unless `include_video_language` is set. Keep requesting English, the title's original language and `null`.
- **TV trailers:** show-level trailers always come first. Only when there are none, fall back to season trailers per the `season_fallback` setting (`first` default, `latest`, `off`), capped at three lookups. Never let a later-season trailer (`later_season_in_name`) outrank a spoiler-free one.
- **Sonarr TMDB IDs:** use the series' own `tmdbId` first; fall back to TMDB `/find` by TVDB ID, then IMDb ID (`resolve_tv_tmdb`).
- **Existing trailers:** "missing" means `find_trailer_files()` found nothing, never "the configured filename is absent". Rename, keep and delete must go through `detected_file()`, and Replace/Force may only remove old files after a successful download.
- **YouTube search fallback:** opt-in only, and only after TMDB has nothing usable. Keep every filter in `youtube_search_candidates` (title words, trailer word, duration, junk/excluded terms, wrong year); loosening them trades misses for wrong-show grabs. Always mark search grabs (`via_search`) in Activity.
- **Unavailable videos:** only errors about the video itself (`video_is_gone`) move on to the next candidate (max 5). Bot checks, network errors and timeouts must stop the loop.
- **TMDB:** Preserve trailer selection/scoring behavior unless a change is intentional and documented. Handle missing or malformed external responses safely.
- **yt-dlp:** Preserve the distinction between the bundled binary and the persistent `/config/bin/yt-dlp` override. Do not bypass checksum verification for in-app updates. Automatic update checks must not silently install a release.
- **Discord:** Treat webhook URLs as secrets; notification failures must not compromise media operations.
- **`/config`:** Preserve existing settings, activity history, trailer metadata, webhook status (`webhook-status.json`), watcher state (`watch-state.json`) and download lock behavior across container recreation and upgrades. Losing `watch-state.json` is safe: the watcher re-baselines without grabbing.

## Testing changes

There is no dedicated automated test suite included in the v0.7.0 archive. Contributors should describe the manual tests performed and add automated tests when practical, especially for bug fixes and path handling.

At a minimum, verify relevant cases before opening a pull request:

1. The Docker image builds and the web UI loads.
2. Existing configuration survives a container restart/recreation.
3. Affected Radarr/Sonarr libraries and TMDB lookups behave as expected.
4. Downloads work with ordinary and special-character paths.
5. Existing trailers are not modified unexpectedly; replacement and deletion affect only the intended file.
6. Batch progress, concurrency limits, cancellation, and activity records remain accurate when affected.
7. CLI, webhook and API-watcher download paths still work when shared download code changes.
8. Webhook events: `Download` grabs, `Grab`/`MovieAdded` defer, other events are ignored, a missing folder is logged and not created.
9. Watcher: first check grabs nothing; a Radarr import and upgrade are detected; a new Sonarr series grabs once its folder exists.
10. yt-dlp update checking, checksum validation, and persistent overrides remain safe when affected.

Use disposable test media and sanitized test settings. Never run destructive test cases against your only copy of a media library.

For a basic Python syntax check:

```bash
python -m py_compile app.py
```

This is only a syntax check, not a substitute for functional testing.

## Docker development, updates, and releases

These instructions match the Dockerfile and Compose file supplied with **v0.7.0**. They describe a maintainer workflow; they do **not** imply that an automated CI pipeline, Docker Hub organization, or GitHub Container Registry publisher is already configured.

### Prerequisites and first-time setup

Install Docker Engine with the Docker Compose and Buildx plugins. Run commands from the repository root (where `Dockerfile`, `app.py`, and `docker-compose.yml` are located):

```bash
docker --version
docker compose version
docker buildx version
```

The provided Compose file uses an **external** Docker network called `media-network`. If it does not exist on your machine, create it:

```bash
docker network create media-network
```

Skip that command if the network already exists. Edit `docker-compose.yml` to point `/path/to/media` at a disposable test media folder. `./config:/config` persists application configuration. Do not test destructive trailer operations on your live media library.

### Rebuild and update an existing installation

To rebuild the application from local source and recreate its container:

```bash
docker compose up -d --build
docker compose logs --tail=100 trailer-park
```

To fetch an updated base image and rebuild (including updated Alpine packages and Python dependencies available at build time):

```bash
docker compose build --pull --no-cache
docker compose up -d
docker compose logs --tail=100 trailer-park
```

**Important:** `--pull` and `--no-cache` do not guarantee reproducible or vulnerability-free builds. The current Dockerfile uses floating Alpine package and Python package versions, so rebuilding at different times can produce different dependency versions. For predictable releases, consider pinning dependencies (and testing any base-image digest or version changes) in a separate contribution.

The bind-mounted `./config` directory persists when the container is rebuilt. Never use `docker compose down -v` casually, and back up your configuration and important media before upgrades. Check file permissions if you change the Compose `user:` mapping.

### Edit or create a Dockerfile

The repository currently uses one Dockerfile at its root. It:

1. Starts from `python:3.12-alpine`.
2. Installs `ffmpeg`, `curl`, and `deno` with `apk`.
3. Installs `yt-dlp`, `flask`, and `waitress` with `pip`.
4. Configures yt-dlp remote EJS components via `/etc/yt-dlp.conf`.
5. Copies `app.py` and `templates/` to `/app`, exposes TCP port 8080, and starts Flask through Waitress.

There is **no Dockerfile generator** in v0.7.0. To create an alternative image definition, copy the existing Dockerfile and adapt it deliberately:

```bash
cp Dockerfile Dockerfile.dev
# Edit Dockerfile.dev, then build it explicitly:
docker build -f Dockerfile.dev -t trailer-park:dev .
```

If you add Python requirements, system packages, entrypoint logic, or application files, update the corresponding `RUN`/`COPY` commands and test the result. Preserve the `/config` and `/data/media` mount conventions and port 8080 unless a breaking change is intentional and documented. Changing Alpine to Debian, switching Python versions, or replacing Deno needs a separate compatibility check; do not blindly substitute package-manager commands.

To build the normal production Dockerfile without Compose:

```bash
docker build --pull -t trailer-park:dev .
docker image inspect trailer-park:dev --format '{{.Id}}'
```

### Check the image before releasing it

At minimum, check syntax, run the service with safe test mounts, and inspect logs:

```bash
python3 -m py_compile app.py
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 trailer-park
```

Open `http://localhost:8080` (or the appropriate Docker-host address), verify that the UI loads, and exercise the affected workflows against **test** Radarr/Sonarr data and disposable media. Confirm persistence across a restart and test downloads, cancellation, path handling, and replacement/deletion when relevant. The v0.7.0 archive does not ship an automated test suite, so a successful build alone is not release validation.

### Build and tag a new version

Versions and tags come from the release PR (see the checklist below), so do not pick or edit a version by hand. To try a build locally, tag it yourself. The commands below create local image tags; they do not publish anything:

```bash
docker build --pull -t trailer-park:v0.7.1 -t trailer-park:latest .
docker image ls trailer-park
```

The example version is illustrative, not an announcement that v0.7.1 exists. Use the actual approved release version and avoid moving `latest` unless the release is stable.

### Multi-platform images: amd64 and arm64

Docker Buildx supports multi-platform builds. Install and configure Buildx and ensure your builder can execute both target architectures (for example, a compatible builder with QEMU emulation or native nodes). To create a builder if required:

```bash
docker buildx create --name trailer-park-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

If that builder already exists, select it with `docker buildx use trailer-park-builder` instead. Verify the reported platforms before continuing. CI builds both platforms and smoke tests the amd64 image on every pull request that touches the image, and the release workflow publishes both. `deno`, `ffmpeg` and `curl` are available on Alpine for amd64 and arm64 (checked with an arm64 build), but a change to the Dockerfile or its packages should still be confirmed with real builds.

A multi-platform image is normally pushed directly to a registry rather than imported with `--load` into the classic Docker image store. The following is an **optional publishing example**—replace the registry path with one you control:

```bash
export IMAGE=YOUR-GIT-HOST/OWNER/trailer-park
export VERSION=v0.7.0

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "$IMAGE:$VERSION" \
  -t "$IMAGE:latest" \
  --push .
```

Only use `--push` after authenticating, verifying registry permissions, and obtaining maintainer approval. If multi-platform dependencies fail, stop and fix the relevant Dockerfile/package issue rather than claiming ARM support.

### Publish to a container registry (optional)

Publishing requires registry credentials and an authorized image namespace. Never commit registry tokens.

Release images are published automatically to the **GitHub Container Registry** (`ghcr.io/geebru/trailer-park`) by the release workflow when a release PR is merged; do not push release tags by hand. The steps below are for testing a build in your own namespace. Authenticate with a personal access token that has the `write:packages` scope (GitHub → Settings → Developer settings). Pass it through standard input, not on the command line:

```bash
export IMAGE=ghcr.io/OWNER/trailer-park
export VERSION=v0.7.0

# Provide the token securely in your environment as REGISTRY_TOKEN.
printf '%s' "$REGISTRY_TOKEN" | docker login ghcr.io -u OWNER --password-stdin

docker build --pull -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
docker push "$IMAGE:$VERSION"
docker push "$IMAGE:latest"
```

Only the release workflow publishes to the project's registry. To test a published image, push to your own namespace. A conventional single-platform `docker push` does not produce a multi-platform manifest; use the Buildx procedure above for that.

### End-to-end release checklist

1. Merge the approved changes into the intended release branch and verify the working tree.
2. Review the open release PR that release-please keeps up to date. It bumps the version (`APP_VERSION` in `engine.py`, the README release line) and adds the new `CHANGELOG.md` section from the commit history. Edit its notes so upgrade instructions are included. Do not bump the version by hand.
3. Build a fresh image and complete functional tests using test media and persistent `/config`.
4. Test the supported platforms separately, especially if claiming `arm64` compatibility.
5. Merge the release PR. That creates the `vX.Y.Z` tag and the GitHub release. The release workflow then scans the full history for secrets and, if that is clean, builds and smoke tests the image and pushes it to GHCR as `X.Y.Z`, `X.Y` and `latest` (and `X` from 1.0), with the same version as the tag.
6. Check the release run in the Actions tab: the secret scan and image jobs should be green, and the package page should list the new tags for both `linux/amd64` and `linux/arm64`.
7. Check that the GitHub release carries the matching `CHANGELOG.md` section, including any deployment/upgrade instructions.
8. Recreate a test installation using the published image (or rebuilt source), check logs, confirm `/config` persistence, and verify media permissions.

**Rollback:** Keep the previous known-good image tag and a backup of `/config`. To revert a registry-based deployment, change its image reference to the previous version tag and recreate the container. For a compose file that builds from source, restore the previous tested source revision before rebuilding. Restoring an older application version does not automatically reverse changes made to settings or media; test rollback compatibility and restore backups when necessary.

## Pull requests

Create a branch from `main` and commit your changes with [Conventional Commit](https://www.conventionalcommits.org/) messages. Issue and pull request titles use the same form, `type(scope): subject` (for example `fix(sidebar): stop the tooltip being clipped`), and a check on every PR enforces it because the title becomes the squash commit. A pull request should explain:

- **What changed:** the behavior or defect addressed.
- **Why:** the problem being solved, with an issue reference if available.
- **How tested:** commands, environments, and manual or automated scenarios.
- **Compatibility:** changes to Docker, volumes, settings, migrations, APIs, webhooks, or CLI behavior.
- **Documentation:** README and changelog updates for user-facing changes.

Screenshots are helpful for UI changes. Redact credentials, hostnames, and private media information.

By contributing, you agree that your contribution is licensed under the project's [MIT License](LICENSE).

## Documentation and releases

- Update `README.md` when setup steps, configuration, UI behavior, or documented commands change.
- Add an entry to `CHANGELOG.md` for meaningful user-facing fixes or features, following its existing style.
- Do not change release numbers or publish images/releases as part of a routine contribution unless release coordination has been agreed upon.

## Reporting bugs and security issues

Open bugs as issues in the project repository. For ordinary bugs, provide the Trailer Park version, Docker environment, reproduction steps, expected behavior, actual behavior, and sanitized logs.

For vulnerabilities involving unauthenticated access, path traversal, arbitrary file modification, credential disclosure, or command execution, avoid posting exploit details or secrets in a public issue. Contact the repository maintainer privately through an available repository security-reporting channel instead. If no private channel is published, request one without disclosing the vulnerability details.

## Review expectations

Contributions are reviewed for correctness, clarity, backward compatibility, file safety, and maintainability. Changes may require revisions before merging; submission does not guarantee acceptance.
