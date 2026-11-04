---
name: preview
description: Start a local copy of the current branch for the owner to click through before running /ship. Leaves it running and prints the URL and the pages to look at.
disable-model-invocation: true
---

Give the owner a live, locally reachable copy of the branch checked out in this worktree, so they can verify the change by hand before `/ship`. Change no code and commit nothing.

1. **Check the branch.** Run `git branch --show-current`. If it is `main`, say so and stop: there is nothing to preview. Then `git log --oneline origin/main..HEAD` and `git diff --stat origin/main...HEAD` as separate plain commands, so you know what changed. If there are no commits, say so and stop.
2. **Start it.** `python dev/stack.py up`. It reuses a healthy stack for this worktree, so running `/preview` twice is fine. If Docker is not running, tell the owner and stop. Read the URL from its output (`python dev/stack.py status` prints it again). Never stop or touch containers you did not start.
3. **Work out where to look** from the diff and give direct links, using the port from step 2:
   - `static/ui/js/pages/overview.js` is `/`; `trailers.js` is `/trailers`; `activity.js` is `/activity`; `settings.js` is `/settings?section=<id>` with id one of `connections`, `naming`, `scoring`, `tmdb`, `ytdlp`, `automation`, `notifications`. Check which settings sections the change touches.
   - `shell.js`, `dialogs.js` and shared CSS touch every page: link Overview and say which control or dialog to open.
   - Python changes (`api.py`, `engine.py`, `jobs.py`, `library_cache.py`, `app.py`) are served live from this worktree but need `docker restart <name>` to load; the container name is in `python dev/stack.py status`. The stack was just started, so it already has them.
   - If the branch came from an issue (`<type>/<N>-<slug>`), read it with `gh issue view N` and turn its "done when" or bullets into two or three concrete things to try.
4. **Set up state only if the change needs it.** The fake library has every trailer state but no configured secrets and no running jobs. If the change needs one (for example a configured TMDB key or Discord webhook to see a status), set it through the dev stack's own API with obviously fake values, such as `curl -s -X PUT -H "Content-Type: application/json" -d '{"tmdb_api_key":"test-key-not-real"}' http://localhost:<port>/api/settings`, tell the owner what you set, and give the reset call (`{"clear_tmdb_api_key":true}`). Never use a real key, never read `dev/config`, and never press Test or Send test with fake values, because they call the real services.
5. **Open it** in the built-in browser pane at the first link when the pane is available, so the owner sees it without leaving the app.
6. **Report**, briefly:
   - The URL, and the one-line command to stop it: `python dev/stack.py down` from this worktree (or ask me to).
   - Each link with what to look at and what "right" looks like.
   - A reminder to check a phone-width window as well as a wide one.
   - Anything that makes the copy differ from a real install: fake library, no real Arr connections, fake secrets if you set any.
   - That it keeps running until stopped, and that `/ship` does not stop it.
