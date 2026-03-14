#!/usr/bin/env bash
# =============================================================================
# fetch-trailer-manual.sh
# Manually fetch or replace a trailer for any movie or TV show.
# Reads all configuration (API keys, preferences, paths) from fetch-trailer.sh.
#
# USAGE:
#   # Auto — TMDB lookup using same selection logic as Radarr/Sonarr trigger
#   bash fetch-trailer-manual.sh --path "/data/media/movies/Parasite (2019)"
#
#   # Manual — provide a specific YouTube ID, skip TMDB selection entirely
#   bash fetch-trailer-manual.sh --path "/data/media/movies/Parasite (2019)" --ytid dUKFnBqlVSI
#
#   # Override title/year if folder name doesn't parse correctly
#   bash fetch-trailer-manual.sh --path "/data/media/movies/Alien" --title "Alien" --year 1979
#
#   # TV show (Sonarr-style path)
#   bash fetch-trailer-manual.sh --path "/data/media/tv/The Bear (2022)" --type tv
#
#   # Dry-run — show what would be selected without downloading
#   bash fetch-trailer-manual.sh --path "/data/media/movies/Parasite (2019)" --dry-run
#
# NOTES:
#   - Always replaces existing trailers (unlike the automated script)
#   - Sourced config from fetch-trailer.sh must be in the same directory
#   - SKIP_IF_EXISTS is ignored — manual runs always proceed
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_SCRIPT="${SCRIPT_DIR}/fetch-trailer.sh"

if [[ ! -f "$MAIN_SCRIPT" ]]; then
    echo "[ERROR] Cannot find fetch-trailer.sh in $SCRIPT_DIR" >&2
    exit 1
fi

# =============================================================================
# SOURCE CONFIG + SHARED FUNCTIONS from fetch-trailer.sh
# We extract and eval only the config block and function definitions,
# skipping the main() call at the bottom.
# =============================================================================

# Source everything except the final main "$@" call
source <(grep -v '^\s*main\s*"$@"' "$MAIN_SCRIPT")

# =============================================================================
# ARGUMENT PARSING
# =============================================================================
MEDIA_PATH=""
MEDIA_TITLE=""
MEDIA_YEAR=""
MEDIA_TYPE="movie"
MANUAL_YT_ID=""

usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") --path <media_path> [OPTIONS]

Required:
  --path <path>       Full path to the media folder

Optional:
  --title <title>     Override title (default: parsed from folder name)
  --year <year>       Override year  (default: parsed from folder name)
  --type <movie|tv>   Media type (default: movie)
  --ytid <id>         YouTube video ID — skip TMDB, download this specific video
  --dry-run           Show what would happen without downloading anything

Examples:
  $(basename "$0") --path "/data/media/movies/Parasite (2019)"
  $(basename "$0") --path "/data/media/movies/Parasite (2019)" --ytid dUKFnBqlVSI
  $(basename "$0") --path "/data/media/tv/The Bear (2022)" --type tv
  $(basename "$0") --path "/data/media/movies/Alien" --title "Alien" --year 1979 --dry-run
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --path)    MEDIA_PATH="$2";     shift 2 ;;
        --title)   MEDIA_TITLE="$2";    shift 2 ;;
        --year)    MEDIA_YEAR="$2";     shift 2 ;;
        --type)    MEDIA_TYPE="$2";     shift 2 ;;
        --ytid)    MANUAL_YT_ID="$2";   shift 2 ;;
        --dry-run) DRY_RUN="true";      shift   ;;
        --help|-h) usage ;;
        *) echo "[ERROR] Unknown argument: $1" >&2; usage ;;
    esac
done

[[ -z "$MEDIA_PATH" ]] && { echo "[ERROR] --path is required" >&2; usage; }

# =============================================================================
# PARSE TITLE AND YEAR FROM FOLDER NAME IF NOT PROVIDED
# Expects format: "Title (Year)" or "Title (Year) [extra]"
# =============================================================================
FOLDER_NAME="$(basename "$MEDIA_PATH")"

if [[ -z "$MEDIA_TITLE" ]]; then
    # Extract everything before the first (YYYY) pattern
    MEDIA_TITLE="$(echo "$FOLDER_NAME" | sed 's/ ([0-9]\{4\}).*//')"
fi

if [[ -z "$MEDIA_YEAR" ]]; then
    MEDIA_YEAR="$(echo "$FOLDER_NAME" | grep -oE '\([0-9]{4}\)' | head -1 | tr -d '()' || true)"
fi

if [[ -z "$MEDIA_TITLE" ]]; then
    echo "[ERROR] Could not parse title from folder name: $FOLDER_NAME" >&2
    echo "        Use --title to provide it manually." >&2
    exit 1
fi

if [[ -z "$MEDIA_YEAR" ]]; then
    warn "Could not parse year from folder name: $FOLDER_NAME — using 0000"
    MEDIA_YEAR="0000"
fi

# =============================================================================
# MAIN
# =============================================================================
[[ "$DRY_RUN" == "true" ]] && info "*** DRY-RUN MODE — no files will be written ***"

info "=== fetch-trailer-manual.sh ==="
info "Title    : $MEDIA_TITLE ($MEDIA_YEAR)"
info "Type     : $MEDIA_TYPE"
info "Path     : $MEDIA_PATH"
[[ -n "$MANUAL_YT_ID" ]] && info "YouTube  : https://www.youtube.com/watch?v=${MANUAL_YT_ID} (manual)"

check_deps

if [[ -z "$TMDB_API_KEY" || "$TMDB_API_KEY" == "YOUR_TMDB_API_KEY_HERE" ]]; then
    error "TMDB_API_KEY is not set in fetch-trailer.sh."
    exit 1
fi

# Build output path
output_path="$(build_output_path "$MEDIA_PATH" "$MEDIA_TITLE" "$MEDIA_YEAR")"
info "Output   : $output_path"

# Remove any existing trailer files (manual runs always replace)
if [[ "$DRY_RUN" != "true" ]] && trailer_exists "$MEDIA_PATH"; then
    info "Removing existing trailer(s) in $MEDIA_PATH..."
    find "$MEDIA_PATH" -maxdepth 2 -type f \
        \( -name "*.trailer.mkv" -o -name "*.trailer.mp4" \
        -o -name "*-trailer.mkv" -o -name "*-trailer.mp4" \
        -o -name "*.trailer.en.srt" \) \
        -delete 2>/dev/null && info "Existing trailer(s) removed."
fi

# =============================================================================
# MANUAL MODE — YouTube ID provided directly
# =============================================================================
if [[ -n "$MANUAL_YT_ID" ]]; then
    info "Manual mode — skipping TMDB lookup"

    # Still fetch original language for subtitle logic if TMDB lookup is feasible
    local_orig_lang=""
    TMDB_ID=""
    encoded_title="$("$JQ_BIN" -rn --arg x "$MEDIA_TITLE" '$x | @uri')"
    if [[ "$MEDIA_TYPE" == "movie" ]]; then
        TMDB_ID="$(tmdb_get "/search/movie?query=${encoded_title}&year=${MEDIA_YEAR}" \
            | "$JQ_BIN" -r '.results[0].id // empty' 2>/dev/null || true)"
    else
        TMDB_ID="$(tmdb_get "/search/tv?query=${encoded_title}" \
            | "$JQ_BIN" -r '.results[0].id // empty' 2>/dev/null || true)"
    fi

    if [[ -n "$TMDB_ID" ]]; then
        local_orig_lang="$(tmdb_fetch_original_language "$TMDB_ID" "$MEDIA_TYPE" 2>/dev/null || true)"
        [[ -n "$local_orig_lang" ]] && info "Original language: $local_orig_lang"
    else
        warn "Could not resolve TMDB ID — subtitle language detection skipped"
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would download: https://www.youtube.com/watch?v=${MANUAL_YT_ID}"
        info "Would write to: $output_path"
        exit 0
    fi

    if download_trailer "$MANUAL_YT_ID" "$output_path" "$local_orig_lang" "$MEDIA_TITLE" "$MEDIA_YEAR"; then
        info "Done: trailer saved for '$MEDIA_TITLE'"
        notify_discord "🎬 Trailer downloaded (manual): **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${MANUAL_YT_ID}"
        exit 0
    else
        error "Trailer download failed for '$MEDIA_TITLE'"
        notify_discord "⚠️ Trailer download failed (manual): **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${MANUAL_YT_ID}"
        exit 1
    fi
fi

# =============================================================================
# AUTO MODE — TMDB lookup and selection
# =============================================================================

# Enforce TMDB rate delay before any API calls
tmdb_rate_wait

# Resolve TMDB ID
TMDB_ID=""
encoded_title="$("$JQ_BIN" -rn --arg x "$MEDIA_TITLE" '$x | @uri')"
if [[ "$MEDIA_TYPE" == "movie" ]]; then
    TMDB_ID="$(tmdb_get "/search/movie?query=${encoded_title}&year=${MEDIA_YEAR}" \
        | "$JQ_BIN" -r '.results[0].id // empty')"
else
    TMDB_ID="$(tmdb_get "/search/tv?query=${encoded_title}" \
        | "$JQ_BIN" -r '.results[0].id // empty')"
fi

if [[ -z "$TMDB_ID" ]]; then
    error "Could not resolve TMDB ID for '$MEDIA_TITLE'. Try --ytid to provide a trailer manually."
    exit 1
fi
info "TMDB ID  : $TMDB_ID"

# Fetch original language
orig_lang="$(tmdb_fetch_original_language "$TMDB_ID" "$MEDIA_TYPE")"
[[ -n "$orig_lang" ]] && info "Original language: $orig_lang"

# Fetch videos
videos_json="$(tmdb_fetch_videos "$TMDB_ID" "$MEDIA_TYPE" "$orig_lang")"
if [[ -z "$videos_json" ]]; then
    error "Empty response from TMDB videos endpoint."
    exit 1
fi

# Pick best trailer
yt_key="$(pick_best_trailer "$videos_json")"
if [[ -z "$yt_key" ]]; then
    warn "No suitable trailer found on TMDB for '$MEDIA_TITLE'."
    warn "Try --ytid to provide one manually."
    exit 0
fi

# --- Dry-run report -----------------------------------------------------------
if [[ "$DRY_RUN" == "true" ]]; then
    sub_note="disabled"
    if [[ "$DOWNLOAD_SUBTITLES" == "true" ]]; then
        if [[ -n "$orig_lang" && "$orig_lang" != "en" ]]; then
            sub_note="en sidecar (non-English media)"
        else
            sub_note="skipped (English media)"
        fi
    fi

    all_candidates="$(echo "$videos_json" | "$JQ_BIN" -c '
        .results
        | map(select(.site == "YouTube" and .type == "Trailer"))
        | sort_by([(.is_orig_lang | not), (.published_at | . // "")])
        | reverse
    ')"
    total="$(echo "$all_candidates" | "$JQ_BIN" 'length')"

    info "============================================================"
    info "DRY-RUN CANDIDATE REPORT — $MEDIA_TITLE ($MEDIA_YEAR)"
    info "  Media lang     : ${orig_lang:-unknown}"
    info "  Output path    : $output_path"
    info "  Quality format : bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    info "  Cookies file   : ${YTDLP_COOKIES_FILE:-not set}"
    info "  Subtitles      : $sub_note"
    info "  Selected key   : $yt_key  ← would be downloaded"
    info "------------------------------------------------------------"
    info "  All $total YouTube trailers (orig-lang first, newest first):"
    info "------------------------------------------------------------"

    idx=0
    while IFS= read -r candidate; do
        idx=$(( idx + 1 ))
        c_key="$(echo "$candidate"  | "$JQ_BIN" -r '.key')"
        c_name="$(echo "$candidate" | "$JQ_BIN" -r '.name')"
        c_is_orig="$(echo "$candidate" | "$JQ_BIN" -r '.is_orig_lang')"
        c_date="$(echo "$candidate" | "$JQ_BIN" -r '.published_at // "unknown date"' | cut -c1-10)"

        lang_tag="  en"
        [[ "$c_is_orig" == "true" ]] && lang_tag="orig"

        excluded_tag=""
        matches_any "$c_name" "${EXCLUDED_TERMS[@]}" && excluded_tag=" [EXCLUDED]"

        selected_tag=""
        [[ "$c_key" == "$yt_key" ]] && selected_tag=" ◄ SELECTED"

        info "  [$idx] [$lang_tag] $c_name ($c_date)${excluded_tag}${selected_tag}"
        info "       url: https://www.youtube.com/watch?v=${c_key}"
    done < <(echo "$all_candidates" | "$JQ_BIN" -c '.[]')

    info "============================================================"
    exit 0
fi

# Download
if download_trailer "$yt_key" "$output_path" "$orig_lang" "$MEDIA_TITLE" "$MEDIA_YEAR"; then
    info "Done: trailer saved for '$MEDIA_TITLE'"
    notify_discord "🎬 Trailer downloaded (manual): **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${yt_key}"
    exit 0
else
    error "Trailer download failed for '$MEDIA_TITLE'"
    notify_discord "⚠️ Trailer download failed (manual): **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${yt_key}"
    exit 1
fi