# Upgrading

[README](../README.md) · [Using the app](using.md) · [Settings](settings.md) · [How a trailer is chosen](trailer-selection.md) · [Command line and API](cli-and-api.md) · [Security](security.md) · Upgrading

```bash
docker compose pull
docker compose up -d
```

Keep the same `/config` volume across upgrades. Before a major upgrade, back up `config/settings.json`.

To build from source instead, clone the repository, replace `image:` with `build: .` in your compose file, and use `docker compose up -d --build` (after `git pull` to upgrade).

## From an older version

- **From Trailarr Parrk** (the project's former name): your `/config` volume and settings are unchanged. If you use the example compose file, rename the service and container to `trailer-park` and use the image from the [README](../README.md#install). Run `docker compose down` **before** you change the file, so the old `trailarr-parrk` container does not keep port 8080, then `docker compose up -d`. A compose file of your own can keep its old names. If you run the manual script from Radarr or Sonarr, point the connection at `scripts/trailer-park.sh` (it was `trailarr-parrk.sh`). Log lines are now prefixed `[trailer-park]`.
- **From v0.9.x or older:** if you open Trailer Park by your own domain name, a reverse proxy name or a Tailscale name, it now answers `421` until you add that name to `ALLOWED_HOSTS` (see Host names under [Install](../README.md#install)). Opening it by IP address, `localhost` or a short LAN name needs nothing.
- **From v0.7.x:** keep the same `/config` volume. Connections and settings carry over. The old `libraries` list in `settings.json` is ignored, and old bookmarks such as `/library/movies` redirect to `/trailers`. Arr webhooks are gone: if you added one in Radarr or Sonarr, remove it under **Settings → Connect**, or the Arr will log 404 errors.
