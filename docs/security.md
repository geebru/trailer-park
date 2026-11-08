# Security

[README](../README.md) · [Using the app](using.md) · [Settings](settings.md) · [How a trailer is chosen](trailer-selection.md) · [Command line and API](cli-and-api.md) · Security · [Upgrading](upgrading.md)

**No login.** Trailer Park has no authentication of its own (a login is tracked in [#15](https://github.com/geebru/trailer-park/issues/15)). Anyone who can reach its port can change settings, start grabs and delete the trailers it manages. Keep it on a trusted network and off the public internet. If you need it from outside your LAN, use a VPN, or a reverse proxy that authenticates before it forwards a request.

**Host names.** A request is refused unless it reaches the app by an expected name (`ALLOWED_HOSTS`, see [Install](../README.md#install)). That stops a web page on another site from pointing its own domain at your server and driving the API through your browser (DNS rebinding). It does not replace a login.

**The config directory is sensitive.** `/config/settings.json` holds your TMDB token, the Discord webhook URL and the Radarr and Sonarr API keys in plain text, readable only by its owner, as the Arrs do with theirs. The app never returns or logs them, but a copy of the directory exposes every key. Keep backups private and never post it in an issue.

**Run it unprivileged.** The container runs as root unless you set `user:`. yt-dlp and ffmpeg handle data from the internet, so a flaw in either would get the whole container. Set `user:` to an ID that can write `/config` and your media folders (see [Install](../README.md#install)). The image works the same either way.

**Reporting a vulnerability.** See [SECURITY.md](../SECURITY.md).

Every response carries `Content-Security-Policy` (the interface loads only from its own origin and cannot be put in a frame), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`. If you run it behind a reverse proxy, let these headers through.
