# Contributing to Trailarr Parrk

Thank you for helping improve Trailarr Parrk. This project downloads and manages local trailers for Radarr and Sonarr libraries using TMDB and yt-dlp.

This guide applies to the v0.6.3 codebase. Please read the [README](README.md) and [CHANGELOG](CHANGELOG.md) before making changes.

The project lives at **https://gitea.icarus-ii.com/izsez/trailarr-parrk**. Issues, pull requests and releases are handled there.

## Before you start

- Check existing [issues](https://gitea.icarus-ii.com/izsez/trailarr-parrk/issues) and [pull requests](https://gitea.icarus-ii.com/izsez/trailarr-parrk/pulls) before starting substantial work.
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
   git clone https://gitea.icarus-ii.com/izsez/trailarr-parrk.git
   cd trailarr-parrk
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
   docker compose logs -f trailarr-parrk
   ```

8. Rebuild after modifying application code or templates:

   ```bash
   docker compose up -d --build
   ```

The container uses Python 3.12, Flask, Waitress, yt-dlp, ffmpeg, and Deno. If you modify dependencies or the runtime, update the Dockerfile and document why.

**Important:** Trailarr Parrk does not include built-in authentication. Do not expose a development instance directly to the public internet.

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
- **Unavailable videos:** only errors about the video itself (`video_is_gone`) move on to the next candidate (max 5). Bot checks, network errors and timeouts must stop the loop.
- **TMDB:** Preserve trailer selection/scoring behavior unless a change is intentional and documented. Handle missing or malformed external responses safely.
- **yt-dlp:** Preserve the distinction between the bundled binary and the persistent `/config/bin/yt-dlp` override. Do not bypass checksum verification for in-app updates. Automatic update checks must not silently install a release.
- **Discord:** Treat webhook URLs as secrets; notification failures must not compromise media operations.
- **`/config`:** Preserve existing settings, activity history, trailer metadata, webhook status (`webhook-status.json`), watcher state (`watch-state.json`) and download lock behavior across container recreation and upgrades. Losing `watch-state.json` is safe: the watcher re-baselines without grabbing.

## Testing changes

There is no dedicated automated test suite included in the v0.6.3 archive. Contributors should describe the manual tests performed and add automated tests when practical, especially for bug fixes and path handling.

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

These instructions match the Dockerfile and Compose file supplied with **v0.6.3**. They describe a maintainer workflow; they do **not** imply that an automated CI pipeline, Docker Hub organization, or GitHub Container Registry publisher is already configured.

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
docker compose logs --tail=100 trailarr-parrk
```

To fetch an updated base image and rebuild (including updated Alpine packages and Python dependencies available at build time):

```bash
docker compose build --pull --no-cache
docker compose up -d
docker compose logs --tail=100 trailarr-parrk
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

There is **no Dockerfile generator** in v0.6.3. To create an alternative image definition, copy the existing Dockerfile and adapt it deliberately:

```bash
cp Dockerfile Dockerfile.dev
# Edit Dockerfile.dev, then build it explicitly:
docker build -f Dockerfile.dev -t trailarr-parrk:dev .
```

If you add Python requirements, system packages, entrypoint logic, or application files, update the corresponding `RUN`/`COPY` commands and test the result. Preserve the `/config` and `/data/media` mount conventions and port 8080 unless a breaking change is intentional and documented. Changing Alpine to Debian, switching Python versions, or replacing Deno needs a separate compatibility check; do not blindly substitute package-manager commands.

To build the normal production Dockerfile without Compose:

```bash
docker build --pull -t trailarr-parrk:dev .
docker image inspect trailarr-parrk:dev --format '{{.Id}}'
```

### Check the image before releasing it

At minimum, check syntax, run the service with safe test mounts, and inspect logs:

```bash
python3 -m py_compile app.py
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 trailarr-parrk
```

Open `http://localhost:8080` (or the appropriate Docker-host address), verify that the UI loads, and exercise the affected workflows against **test** Radarr/Sonarr data and disposable media. Confirm persistence across a restart and test downloads, cancellation, path handling, and replacement/deletion when relevant. The v0.6.3 archive does not ship an automated test suite, so a successful build alone is not release validation.

### Build and tag a new version

After making and testing release changes, select a new version (example: `v0.6.4`) and update `README.md` and `CHANGELOG.md` consistently. The commands below create local image tags; they do not publish anything:

```bash
docker build --pull -t trailarr-parrk:v0.6.4 -t trailarr-parrk:latest .
docker image ls trailarr-parrk
```

The example version is illustrative, not an announcement that v0.6.4 exists. Use the actual approved release version and avoid moving `latest` unless the release is stable.

### Multi-platform images: amd64 and arm64

Docker Buildx supports multi-platform builds. Install and configure Buildx and ensure your builder can execute both target architectures (for example, a compatible builder with QEMU emulation or native nodes). To create a builder if required:

```bash
docker buildx create --name trailarr-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

If that builder already exists, select it with `docker buildx use trailarr-builder` instead. Verify the reported platforms before continuing. The dependencies in this image, especially the availability of `deno` in Alpine for the target platform, **must be confirmed with actual builds and runtime tests**; multi-architecture support is not established merely by specifying both platforms.

A multi-platform image is normally pushed directly to a registry rather than imported with `--load` into the classic Docker image store. The following is an **optional publishing example**—replace the registry path with one you control:

```bash
export IMAGE=gitea.icarus-ii.com/izsez/trailarr-parrk
export VERSION=v0.6.3

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "$IMAGE:$VERSION" \
  -t "$IMAGE:latest" \
  --push .
```

Only use `--push` after authenticating, verifying registry permissions, and obtaining maintainer approval. If multi-platform dependencies fail, stop and fix the relevant Dockerfile/package issue rather than claiming ARM support.

### Publish to a container registry (optional)

Publishing requires registry credentials and an authorized image namespace. Never commit registry tokens.

The project's registry is the **Gitea container registry** on the project host. Images appear under the repository owner's *Packages* tab. Authenticate with a Gitea access token that has package write permission (Settings → Applications → Generate Token). Pass it through standard input, not on the command line:

```bash
export IMAGE=gitea.icarus-ii.com/izsez/trailarr-parrk
export VERSION=v0.6.3

# Provide the token securely in your environment as GITEA_TOKEN.
printf '%s' "$GITEA_TOKEN" | docker login gitea.icarus-ii.com -u izsez --password-stdin

docker build --pull -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
docker push "$IMAGE:$VERSION"
docker push "$IMAGE:latest"
```

Only the maintainer publishes to this registry. Contributors who want to test a published image should push to their own namespace instead.

No automated release workflow (Gitea Actions) is configured yet; images are built and pushed manually. For multi-platform publication, use the Buildx procedure above with your chosen image name; a conventional single-platform `docker push` does not produce a multi-platform manifest by itself.

### End-to-end release checklist

1. Merge the approved changes into the intended release branch and verify the working tree.
2. Update the documented release version and add the user-facing changes to `CHANGELOG.md`.
3. Build a fresh image and complete functional tests using test media and persistent `/config`.
4. Test the supported platforms separately, especially if claiming `arm64` compatibility.
5. Tag the source and image with the **same** version. For example, after reviewing the commit:

   ```bash
   git tag v0.6.4
   # Push only when authorized and the correct remote/branch is confirmed:
   git push origin v0.6.4
   ```

6. If you maintain published images, push the intended tags to your configured registry; update `latest` only when appropriate.
7. Tag the release (`git tag v0.6.x && git push --tags`) and publish a Gitea release from that tag (Releases → New Release), using the matching `CHANGELOG.md` section as the notes, including any deployment/upgrade instructions.
8. Recreate a test installation using the published image (or rebuilt source), check logs, confirm `/config` persistence, and verify media permissions.

**Rollback:** Keep the previous known-good image tag and a backup of `/config`. To revert a registry-based deployment, change its image reference to the previous tag and recreate the container. For the supplied `build: .` Compose setup, restore the previous tested source revision before rebuilding. Restoring an older application version does not automatically reverse changes made to settings or media; test rollback compatibility and restore backups when necessary.

## Pull requests

Create a branch from your intended base branch and commit your changes with descriptive messages. A pull request should explain:

- **What changed:** the behavior or defect addressed.
- **Why:** the problem being solved, with an issue reference if available.
- **How tested:** commands, environments, and manual or automated scenarios.
- **Compatibility:** changes to Docker, volumes, settings, migrations, APIs, webhooks, or CLI behavior.
- **Documentation:** README and changelog updates for user-facing changes.

Screenshots are helpful for UI changes. Redact credentials, hostnames, and private media information.

## Documentation and releases

- Update `README.md` when setup steps, configuration, UI behavior, or documented commands change.
- Add an entry to `CHANGELOG.md` for meaningful user-facing fixes or features, following its existing style.
- Do not change release numbers or publish images/releases as part of a routine contribution unless release coordination has been agreed upon.

## Reporting bugs and security issues

Open bugs at https://gitea.icarus-ii.com/izsez/trailarr-parrk/issues. For ordinary bugs, provide the Trailarr Parrk version, Docker environment, reproduction steps, expected behavior, actual behavior, and sanitized logs.

For vulnerabilities involving unauthenticated access, path traversal, arbitrary file modification, credential disclosure, or command execution, avoid posting exploit details or secrets in a public issue. Contact the repository maintainer privately through an available repository security-reporting channel instead. If no private channel is published, request one without disclosing the vulnerability details.

## Review expectations

Contributions are reviewed for correctness, clarity, backward compatibility, file safety, and maintainability. Changes may require revisions before merging; submission does not guarantee acceptance.
