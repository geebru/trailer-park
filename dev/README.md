# Local development

A self-contained stack for testing Trailer Park on Docker Desktop (Windows, macOS or Linux)
with **no real Radarr/Sonarr and no real media**.

| Piece | What it is |
|---|---|
| `trailer-park` | the app, built from this repo, on http://localhost:8080 |
| `mock-radarr`, `mock-radarr-4k`, `mock-sonarr` | tiny fake Arr APIs (`dev/mock_arr.py`), API key `devkey` |
| `dev/media/` | fake library (`dev/make_media.py`): ~260 movies, 3 in a second "4K" Radarr, ~125 shows |
| `dev/config/` | the app's settings, activity log and trailer metadata (git-ignored) |

The fake library covers every trailer state, including names with colons, an mp4 trailer, a
`Trailers/` folder with different casing, two and three trailers in one folder, a title Radarr
reports without a file, and a title whose folder does not exist on disk.

## One command

```powershell
python dev/stack.py up      # creates settings and media if missing, starts the stack, prints the URL
python dev/stack.py status  # URL and health
python dev/stack.py down    # stop and remove this checkout's stack
```

Each checkout (main folder or worktree) gets its own compose project, container name and a free
port from 8100 up, so several can run side by side and none touches a stack on 8080. `up --fresh-media`
rebuilds `dev/media`. Set `TMDB_API_KEY` in your shell before `up` to make Grab work. The commands
below do the same thing by hand, on port 8080.

## First run by hand (Windows PowerShell, from the repo folder)

```powershell
# 1. Start Docker Desktop and wait until it says "running".

# 2. Create the dev settings (pre-wired to the mock Arrs).
New-Item -ItemType Directory -Force dev\config | Out-Null
Copy-Item dev\settings.template.json dev\config\settings.json

# 3. Build the fake media library.
docker compose -f docker-compose.dev.yml run --rm make-media

# 4. Optional: let Grab work. Use your TMDB v4 read token.
$env:TMDB_API_KEY = "paste-token-here"

# 5. Start everything.
docker compose -f docker-compose.dev.yml up --build
```

Open http://localhost:8080. Stop with Ctrl+C, or `docker compose -f docker-compose.dev.yml down`.

Grabs need internet (TMDB, YouTube) and write only into `dev/media/`.

## Daily loop

`app.py`, `engine.py` and `templates/` are mounted into the container, so there is no rebuild:

```powershell
# after editing Python:
docker compose -f docker-compose.dev.yml restart trailer-park
# templates and static files: refresh the browser after the restart.

docker compose -f docker-compose.dev.yml logs -f trailer-park     # app log
```

Rebuild (`up --build`) only when the `Dockerfile` changes.

## Reset

```powershell
docker compose -f docker-compose.dev.yml run --rm make-media    # fresh fake library (wipes downloaded trailers)
Remove-Item -Recurse -Force dev\config                          # forget settings and activity, then redo step 2
```

Change the size of the library: `docker compose -f docker-compose.dev.yml run --rm make-media python /devtools/make_media.py --out /data/media --reset --movies 1500 --shows 400`
(good for performance testing).

## Simulate a slow Arr

Add `--latency-ms 800` to a mock's `command:` in `docker-compose.dev.yml`.

## Using your real Arrs (read-only look)

In the app's Settings, point a connection at your Arr's LAN address and API key. Library and
search will behave realistically, which is useful for layout and speed at your real size.
**Do not Grab, Rename, Delete or enable the watcher this way**: the Arr reports paths from
inside its own container (e.g. `/data/media/movies/...`), which this container cannot see, so
every title will look like it has no folder. Do not mount your real media over SMB into the dev
stack.

## Port already in use?

`python dev/stack.py up` already picks a free port. For the by-hand commands, set `DEV_PORT`, e.g. `DEV_PORT=8081` (PowerShell: `$env:DEV_PORT = "8081"`) before `docker compose`. A second stack run by hand also needs a different `DEV_CONTAINER` (the default container name is `trailer-park-dev`) and `-p <project>`.
