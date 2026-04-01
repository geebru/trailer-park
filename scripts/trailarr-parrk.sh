#!/bin/sh
# =============================================================================
# trailarr-parrk.sh
# Trailer downloader for Radarr and Sonarr.
#
# SETUP
#   Place in /config/scripts/ inside your Radarr or Sonarr container.
#   In arr: Settings → Connect → Custom Script → this file
#   Radarr events: On Import, On Upgrade
#   Sonarr events: On Series Add
#
# MANUAL
#   Dry-run — fetches and scores from TMDB, prints results, skips download:
#   radarr_eventtype="Download" radarr_movie_title="Dune" \
#     radarr_movie_year="2021" radarr_movie_path="/movies/Dune (2021)" \
#     radarr_movie_tmdbid="438631" sh trailarr-parrk.sh --dry-run
#
#   Force-download a specific YouTube ID (no scoring applied):
#   ./trailarr-parrk.sh --yt-id <ID> --title "Title" --year 2024
#   ./trailarr-parrk.sh --yt-id <ID> --title "Title" --year 2024 --output /path --dry-run
# =============================================================================

# =============================================================================
# CONFIG — edit these
# =============================================================================

# v4 TMDB key (the long one)
TMDB_API_KEY=""

# Comma-separated. Each match in a trailer title adds +10 to its score.
# Trailers scoring 0 are skipped. Case-insensitive.
PREFERRED_TERMS="official,trailer,teaser,theatrical"

# Comma-separated. Any match disqualifies a trailer entirely. Case-insensitive.
EXCLUDED_TERMS="fan made,fan-made,reaction,parody,review,recut,behind the scenes,featurette"

# Subfolder inside the media folder. Leave empty "" to save directly into it.
TRAILER_FOLDER="trailers"

# Filename without extension. Tokens: {title} {year}
FILENAME_TEMPLATE="{title} ({year}).trailer"

# Max download height passed to yt-dlp.
VIDEO_QUALITY="1080"

# Discord notification webhook
DISCORD_WEBHOOK_URL=""

# =============================================================================
# HELPERS
# =============================================================================
 
TAB="$(printf '\t')"
 
log() { printf '[trailarr-parrk] %s\n' "$*"; }
 
notify() {
    [ -z "$DISCORD_WEBHOOK_URL" ] && return 0
    _b=$(printf '%s' "$3" | sed 's/"/\\"/g')
    _t=$(printf '%s' "$2" | sed 's/"/\\"/g')
    curl -sf -o /dev/null -X POST -H "Content-Type: application/json" \
        -d "{\"embeds\":[{\"title\":\"$_t\",\"description\":\"$_b\",\"color\":$1}]}" \
        "$DISCORD_WEBHOOK_URL" || log "WARN: Discord notification failed"
}
 
score_trailer() {
    _t=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
    _score=0
    IFS=","; for _term in $EXCLUDED_TERMS; do
        _c=$(printf '%s' "$_term" | tr '[:upper:]' '[:lower:]' | sed 's/^ *//;s/ *$//')
        case "$_t" in *"$_c"*) IFS=" "; printf 'EXCLUDED'; return;; esac
    done
    for _term in $PREFERRED_TERMS; do
        _c=$(printf '%s' "$_term" | tr '[:upper:]' '[:lower:]' | sed 's/^ *//;s/ *$//')
        case "$_t" in *"$_c"*) _score=$(( _score + 10 ));; esac
    done
    IFS=" "; printf '%d' "$_score"
}
 
# =============================================================================
# CORE
# =============================================================================
 
fetch_and_score() {
    : > /tmp/tp_scored
    : > /tmp/tp_excluded
 
    if [ -z "$TMDB_API_KEY" ]; then
        log "ERROR: TMDB_API_KEY is not set in the script config."
        return 1
    fi
 
    _resp=$(curl -sf \
        -H "Authorization: Bearer $TMDB_API_KEY" \
        -H "Accept: application/json" \
        "https://api.themoviedb.org/3/$2/$1/videos")
 
    if [ -z "$_resp" ]; then
        log "ERROR: TMDB API request failed — check TMDB_API_KEY and network connectivity."
        return 1
    fi
 
    _count=$(printf '%s' "$_resp" \
        | jq '[.results[] | select(.site=="YouTube" and .type=="Trailer")] | length')
    log "TMDB returned $_count YouTube trailer(s)." >&2
    [ "$_count" -eq 0 ] && return 1
 
    printf '%s' "$_resp" \
        | jq -r '.results[] | select(.site=="YouTube" and .type=="Trailer") | [.key,.name] | @tsv' \
        | while IFS="$TAB" read -r _id _name; do
            _s=$(score_trailer "$_name")
            if [ "$_s" = "EXCLUDED" ]; then
                printf '%s|%s\n' "$_name" "$_id" >> /tmp/tp_excluded
            elif [ "$_s" -gt 0 ]; then
                printf '%s|%s|%s\n' "$_s" "$_id" "$_name" >> /tmp/tp_scored
            fi
        done
 
    sort -t'|' -k1 -rn /tmp/tp_scored
}
 
download() {
    if [ "${DRY_RUN:-0}" = "1" ]; then
        log "DRY RUN — would download: https://www.youtube.com/watch?v=$1"
        log "DRY RUN — would save to:  $2.mkv"
        return 0
    fi
    _dir=$(dirname "$2")
    mkdir -p "$_dir"
    find "$_dir" -maxdepth 1 -name "*.mkv" -delete 2>/dev/null || true
    yt-dlp \
        -f "bestvideo[height<=${VIDEO_QUALITY}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=${VIDEO_QUALITY}]+bestaudio/best" \
        --merge-output-format mkv \
        --no-playlist \
        -o "$2.%(ext)s" \
        "https://www.youtube.com/watch?v=$1"
}
 
out_path() {
    _safe=$(printf '%s' "$2" | tr '/:*?"<>|\\' '_')
    _name=$(printf '%s' "$FILENAME_TEMPLATE" | sed "s/{title}/$_safe/g;s/{year}/$3/g")
    [ -n "$TRAILER_FOLDER" ] \
        && printf '%s/%s/%s' "$1" "$TRAILER_FOLDER" "$_name" \
        || printf '%s/%s' "$1" "$_name"
}
 
print_excluded() {
    _excl=$(cat /tmp/tp_excluded 2>/dev/null)
    [ -z "$_excl" ] && return 0
    log "Excluded trailers (use --yt-id to manually grab one):"
    printf '%s\n' "$_excl" | head -n 5 | while IFS='|' read -r _n _id; do
        log "  [--yt-id $_id] $_n — https://youtu.be/$_id"
    done
}
 
# =============================================================================
# MAIN
# =============================================================================
 
main() {
    DRY_RUN=0
 
    # ── Manual mode ───────────────────────────────────────────────────────────
    if [ $# -gt 0 ]; then
        _ytid=""; _title=""; _year=""; _output=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --yt-id)   _ytid="$2";   shift 2;;
                --title)   _title="$2";  shift 2;;
                --year)    _year="$2";   shift 2;;
                --output)  _output="$2"; shift 2;;
                --dry-run) DRY_RUN=1;    shift;;
                *) log "Unknown flag: $1. Flags: --yt-id --title --year --output --dry-run"; exit 1;;
            esac
        done
 
        if [ -n "$_ytid" ]; then
            [ -z "$_title" ] || [ -z "$_year" ] && {
                log "Usage: $0 --yt-id <id> --title <title> --year <year> [--output <path>] [--dry-run]"
                exit 1
            }
            _path=$(out_path "${_output:-.}" "$_title" "$_year")
            log "Manual: $_ytid → $_path.mkv"
            download "$_ytid" "$_path" && log "Done." || { log "Download failed."; exit 1; }
            exit 0
        fi
        # --dry-run alone with no --yt-id falls through to auto mode
    fi
 
    # ── Auto mode — detect Radarr or Sonarr ──────────────────────────────────
    if [ -n "${radarr_eventtype:-}" ]; then
        ARR_TYPE="movie"
        _event="$radarr_eventtype"
        _title="${radarr_movie_title:-}"; _year="${radarr_movie_year:-}"
        _path="${radarr_movie_path:-}";   _tmdbid="${radarr_movie_tmdbid:-}"
    elif [ -n "${sonarr_eventtype:-}" ]; then
        ARR_TYPE="tv"
        _event="$sonarr_eventtype"
        _title="${sonarr_series_title:-}"; _year="${sonarr_series_year:-}"
        _path="${sonarr_series_path:-}";   _tmdbid="${sonarr_series_tmdbid:-}"
    else
        log "No arr event detected and no flags given. Run with --yt-id for manual use."
        exit 1
    fi
 
    [ "$_event" = "Test" ] && {
        log "Test event received."
        notify 3066993 "🎬 Trailarr Parrk connected" "Script connection confirmed."
        exit 0
    }
 
    [ "$DRY_RUN" = "1" ] && log "DRY RUN — no files will be downloaded or deleted."
    log "$_title ($_year) — TMDB $_tmdbid"
 
    _scored=$(fetch_and_score "$_tmdbid" "$ARR_TYPE")
 
    if [ -z "$_scored" ]; then
        print_excluded
        _excl=$(cat /tmp/tp_excluded 2>/dev/null)
        if [ -n "$_excl" ]; then
            _links=$(printf '%s\n' "$_excl" | head -n 3 \
                | while IFS='|' read -r _n _id; do
                    printf '• %s — https://youtu.be/%s\n' "$_n" "$_id"
                  done)
            [ "$DRY_RUN" = "0" ] && notify 16776960 \
                "⚠️ No valid trailers — $_title ($_year)" \
                "All found trailers matched an excluded term.\n\n$_links"
        else
            [ "$DRY_RUN" = "0" ] && notify 16776960 \
                "⚠️ No matching trailers — $_title ($_year)" \
                "No trailers matched preferred terms. Try broadening PREFERRED_TERMS."
        fi
        exit 1
    fi
 
    if [ "$DRY_RUN" = "1" ]; then
        log "Scored candidates:"
        printf '%s\n' "$_scored" | while IFS='|' read -r _s _id _n; do
            log "  [+$_s] $_n — https://youtu.be/$_id  [--yt-id $_id]"
        done
        print_excluded
    fi
 
    _best=$(printf '%s\n' "$_scored" | head -n 1)
    _ytid=$(printf '%s' "$_best" | cut -d'|' -f2)
    _name=$(printf '%s' "$_best" | cut -d'|' -f3)
    _score=$(printf '%s' "$_best" | cut -d'|' -f1)
    _out=$(out_path "$_path" "$_title" "$_year")
 
    log "Best match: '$_name' (score: +$_score)"
 
    if download "$_ytid" "$_out"; then
        [ "$DRY_RUN" = "0" ] && notify 3066993 \
            "✅ Trailer downloaded — $_title ($_year)" \
            "**$_name**\nhttps://youtu.be/$_ytid"
        log "Done."
    else
        [ "$DRY_RUN" = "0" ] && notify 15158332 \
            "❌ Trailer failed — $_title ($_year)" \
            "yt-dlp failed. Check container logs for details."
        exit 1
    fi
}
 
main "$@"
