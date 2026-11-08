# How a trailer is chosen

[README](../README.md) · [Using the app](using.md) · [Settings](settings.md) · How a trailer is chosen · [Command line and API](cli-and-api.md) · [Security](security.md) · [Upgrading](upgrading.md)

1. Trailer Park asks TMDB for the title's videos (English, the title's original language, and untagged ones) and keeps YouTube trailers and teasers.
2. A video whose name contains a **negative keyword** is rejected outright. Defaults: `fan made, fan-made, reaction, parody, review, recut, behind the scenes, featurette`.
3. The rest are scored with the **positive keywords**. Defaults: `official, trailer, teaser, theatrical, season 1, season 01, announcement`.

   | Keyword | Matches | Points |
   |---|---|---|
   | `official` | TMDB's official flag, or the word in the video name | +10 |
   | `trailer` | TMDB's type is Trailer (the video name is not used) | +10 |
   | `teaser` | TMDB's type is Teaser | +5 |
   | any other keyword | the video name contains it, ignoring case (a keyword ending in a digit does not match a longer number, so `season 1` does not match `season 10`) | +10 |

   An official trailer therefore scores 20 and an official teaser 15. A video must score above 0 to be considered.
4. Candidates are ordered spoiler-free first (for shows, a title naming a later season or a "final season" sorts behind the rest, but stays usable if nothing else exists), then by score, then full trailers over teasers, then official, then English.
5. The best candidate is downloaded. If YouTube says it is unavailable (removed, private, region-blocked, age-restricted, members-only), the next candidate is tried, up to five.

**Shows with no show-level trailer** fall back to season trailers. `first` (the default) tries season 1, then season 2. `latest` tries the latest season, the one before it, then season 1. `off` tries none. It is used only when TMDB lists no show-level trailer, makes at most three lookups and skips specials. Change it under Settings → Behavior → **TV season fallback**, or set `SEASON_FALLBACK` (`first`, `latest` or `off`) for the first start. A trailer taken from a season is noted in Activity ("trailer from season 2 of the show").

**YouTube search fallback** (Settings → Behavior, off by default). When TMDB has no usable trailer, or every TMDB trailer is unavailable, Trailer Park searches YouTube for `<title> <year> trailer` (top 15 results, metadata only) and scores the results with the same keywords. A title containing the right year ranks first, which separates an original from a remake with the same name.

Downloads go to a temporary file and replace an existing trailer only after they succeed.

## yt-dlp

**Settings → Downloads** shows the active yt-dlp version and whether a newer one is available. Trailer Park checks the official yt-dlp releases about once a day, but never installs automatically. **Update** downloads the official release file, verifies it against the release `SHA2-256SUMS`, and stores it at `/config/bin/yt-dlp`. That copy is used immediately and after the container is recreated. The version bundled in the image stays as the fallback.

**Age-restricted or region-gated videos.** Some trailers cannot be downloaded without a signed-in YouTube session. To give yt-dlp one, export your YouTube cookies in Netscape format (a browser extension such as "Get cookies.txt LOCALLY" does this) and save them as `cookies.txt` in your `/config` volume. When the file exists, Trailer Park passes it to yt-dlp for downloads and searches; without it nothing changes. There is no setting: **Settings → Downloads** shows the path and whether the file is in use, and the contents are never shown or logged. Each download works on a private temporary copy, so the file can be mounted read-only and yt-dlp never rewrites it. If the file exists but cannot be read, downloads fail with a message saying so. Cookies from your own account can get it flagged by YouTube, so a throwaway account is safer.
