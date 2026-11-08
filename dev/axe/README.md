# axe-core (vendored)

Accessibility checker used for the "axe AA" rule in `AGENTS.md`. Dev only: it is not in the Docker image. `docker-compose.dev.yml` mounts this folder at `/app/static/ui/axe`, so the dev stack serves it from the app's own origin (the app's CSP blocks scripts from anywhere else).

| | |
|---|---|
| Package | `axe-core` 4.14.0, published 2026-10-05 |
| License | MPL-2.0 (`LICENSE`; the notice is also in the header of `axe.min.js`) |
| Source | `npm pack axe-core@4.14.0`, file `package/axe.min.js` |
| Tarball integrity | `sha512-9WTZxEjsZ7b13TH8JPmbV2z8CHbl80/2hm3XPEG4JgNdQLK81IBRXmSxHfMAOkSqQeRxT/0dwNDz2GOm3zzpcQ==` (matches the npm registry) |

## Scan a page

1. Start the dev stack (see `dev/README.md`; in a worktree set `DEV_PORT` and `DEV_CONTAINER`) and open the page in the browser pane at 1280 px, then again at 390 px.
2. Paste `scan.js` into the page's JS. It loads `axe.min.js` from `/static/ui/axe/`, runs the WCAG 2.0-2.2 A and AA rules and returns the violations with their selectors. Do this for each page and for open dialogs when a change touches them.

`static/ui/axe/` holds only a `.gitkeep`: Docker needs the folder to exist in the read-only `static` mount before it can mount this one over it. `.dockerignore` keeps it out of the image.

A clean result is `violations: []`. `needsReview` lists checks axe could not decide automatically (usually colour contrast over images); look at those by eye.

## Update

Download into a new empty folder and verify before copying anything:

```bash
npm view axe-core@X.Y.Z dist.integrity
npm pack axe-core@X.Y.Z
```

Compare the tarball's sha512 with the registry value, then copy only `package/axe.min.js` and `package/LICENSE` here and update the table above. Prefer a release that has been public for a few weeks.
