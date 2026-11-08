# Using the app

[README](../README.md) · Using the app · [Settings](settings.md) · [How a trailer is chosen](trailer-selection.md) · [Command line and API](cli-and-api.md) · [Security](security.md) · [Upgrading](upgrading.md)

## Overview

Total titles, how many have no trailer (with a **Review** link to the Missing view), coverage as a percentage (ignored titles are left out of both), and your most recent activity. The sidebar on every page shows each service's connection state, the next sync, and any running downloads or batch.

## Trailers

**Movies** and **Shows** tabs list every title. Search by name, and filter by connection, media folder, and **All titles / Available / Missing / Name mismatch / Multiple found**. The filters and page live in the address, so you can bookmark a view such as `/trailers?status=missing`.

**What counts as a trailer.** A title has a trailer when its media folder contains **any** trailer file, whatever it is called:

- any video file (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`) inside a `trailers` or `trailer` subfolder (any capitalization) or your configured trailer folder
- a video file in the media folder itself whose name ends in `trailer`, such as `-trailer.mkv`, `.trailer.mkv`, `Title trailer.mp4` or `trailer.mkv` (files over 2 GB are ignored there, so a main movie is never mistaken for a trailer)

Changing the folder or file name settings never moves a title between Missing and Available.

**Missing** lists titles with no trailer file at all. Radarr movies appear once the movie file exists, Sonarr series once their series folder exists.

- **Grab** lets TMDB choose the best trailer. **Manual** uses a YouTube link or ID you give it.
- **Ignore** is for titles you do not want a trailer for (shorts, kids' shows). An ignored title leaves Missing, its count, **Grab N missing** and the automatic grabs, and shows as **Ignored** under All titles, where **Grab** and **Manual** still work. Un-ignore it under **Settings → Ignored**. Once a title has a trailer the ignore is dropped.
- **Grab N missing** (top right) grabs every missing title in the current tab and connection filter, one after another, after a confirmation. Progress and **Cancel batch** are in the sidebar.
- **Select** titles with the checkboxes (or **Select all on this page**; filter to Missing first to pick only those), then **Grab N selected** grabs them as one batch, with no job dialog. If the selection includes titles that already have a trailer, a confirmation asks whether to **Grab missing only** or **Grab all**, which replaces those trailers (the old files are deleted once the new download succeeds). Select all skips ignored titles; one you tick by hand is still grabbed, as are unmonitored ones. The selection survives paging and is cleared when you change a filter.

**Available** lists titles that have a trailer, marked **Name mismatch** (the file does not match your naming template) and/or **Multiple found** (several trailer files; allowed, not an error).

- **Replace** downloads a new trailer. The old files are removed only if the new download succeeds. **Manual** replaces with a specific YouTube link or ID.
- **Files** opens per-file **Rename** (to the current naming, keeps the extension, never overwrites), **Keep only this** (deletes the others) and **Delete**.
- **Rename N** (top right) renames every flagged single-file title in the current tab and connection. A dry run shows what is ready or blocked first, and titles with several files are skipped.

Trailer Park stores metadata for trailers it downloads (TMDB video name, YouTube ID, language, score, time, source). Renames keep that metadata. Trailers it did not download show as **Found on disk**.

A download opens a live log with progress. **Run in background** closes it without stopping anything; **Cancel** stops the download and removes partial files.

**Batches.** Only one batch runs at a time. Each title in it is a normal download, so you can open any running one from the sidebar. **Cancel batch** stops further titles from starting; downloads already running finish safely. When a batch ends, one summary goes to Discord (if enabled) and the batch is recorded in Activity.

## Activity

A paged log of what happened: trailers downloaded (including manual ones), no suitable match found, failed downloads, renames, removed files, ignored and un-ignored titles, batches finished or cancelled, yt-dlp updates, maintenance, and one entry per connection each time you press **Sync now** (so a check that found nothing, or failed, is still visible; the scheduled checks are not logged). Entries older than the retention period are removed automatically.
