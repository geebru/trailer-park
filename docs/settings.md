# Settings

[README](../README.md) · [Using the app](using.md) · Settings · [How a trailer is chosen](trailer-selection.md) · [Command line and API](cli-and-api.md) · [Security](security.md) · [Upgrading](upgrading.md)

Settings are saved with **Save changes** (or **Discard**). Connections are saved as you add them. The sections are grouped under **Setup** (how the app is configured) and **Library** (what you have decided about your titles, currently **Ignored**). Un-ignoring applies at once.

| Section | What it controls |
|---|---|
| **Connections** | Radarr and Sonarr instances: name, type, base URL (no username or password in it), API key. Editing a connection keeps its saved key unless you point it at a different server, which needs the key entered again. Radarr connections feed Movies, Sonarr connections feed Shows. |
| **Naming** | **Media folder** (default `/data/media`). **Trailer folder** (default `trailers`; leave blank to save beside the media file). **File name template** (default `{title} ({year}).trailer`; variables `{title}` and `{year}`). A live **Output preview**. |
| **Behavior** | **Positive keywords** and **Negative keywords** and the **TV season fallback** (see [How a trailer is chosen](trailer-selection.md)), and the **YouTube search fallback** (off by default). |
| **TMDB** | Your TMDB Read Access Token, with **Test key**. |
| **Downloads** | yt-dlp version and updates, and whether the [cookies file](trailer-selection.md#yt-dlp) is in use. **Resolution** (maximum: 480p, 720p, **1080p**, 4K), **Output container** (**mkv** or mp4; mp4 prefers H.264 so files play on more devices) and **Concurrent downloads** (**1** to 4). Changes only affect new downloads. |
| **Automation** | **Sync interval** (Off, **5**, 10, 15, 30 minutes, 1, 6 or 24 hours) with the **Next sync** time and **Sync now**, **Only grab monitored titles** (off by default), and **Activity retention** (60, **90** or 180 days, 1 year, or forever). |
| **Notifications** | An optional Discord webhook URL (only `https://discord.com/api/webhooks/...` addresses are accepted) with **Send test** (a successful test saves it), and toggles for **Trailer downloaded** and **Grab failed** (both on by default). Batches and Sync now send one summary instead of one message per title. |
| **Ignored** | The titles you chose to ignore, each with **Un-ignore**. |

## Automatic grabs

They come from a watcher that polls each connection's API at the sync interval (Off turns automatic grabs off). Radarr grabs on import and upgrade. Sonarr grabs when a series is added, and if its folder does not exist yet it waits (up to 30 days). The first check of a connection only records a baseline, so use **Grab N missing** for titles that were already there. **Sync now** runs a check immediately. Existing trailers are kept on upgrades and on later episode imports. With **Only grab monitored titles** on, the watcher and **Grab N missing** skip titles that Radarr or Sonarr has unmonitored; they stay in Trailers and can still be grabbed one at a time or by selecting them.

The download limit applies across the web interface, batches, the watcher and the command line.

## Files and environment

The `/config` volume holds the app's state. Do not commit it to a public repository.

| File | What it holds |
|---|---|
| `settings.json` | Settings, connections, and secrets (readable only by its owner) |
| `activity.jsonl` | The Activity log |
| `trailers.json` | Metadata for trailers Trailer Park downloaded |
| `watch-state.json` | What the watcher has already seen |
| `ignored.json` | Titles you ignored, so they are not counted as missing |
| `ytdlp-status.json` | The last yt-dlp update check |
| `bin/yt-dlp` | The updated yt-dlp copy, only after an in-app update |
| `cookies.txt` | Optional YouTube cookies for yt-dlp (you add it; see [yt-dlp](trailer-selection.md#yt-dlp)) |
| `download-slots/` | Lock files for the concurrent download limit |

Every setting also has an environment variable that gives it its initial value: the setting's name in capitals, such as `TMDB_API_KEY`, `MEDIA_ROOT`, `VIDEO_QUALITY`, `WATCH_INTERVAL_MINUTES`, `SEASON_FALLBACK`, `YOUTUBE_SEARCH` or `ONLY_MONITORED`. Once settings have been saved they live in `settings.json` and that file wins, so use the interface after the first save.
