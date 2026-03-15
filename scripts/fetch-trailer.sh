#!/usr/bin/env bash
# =============================================================================
# fetch-trailer.sh
# Downloads a trailer for movies (Radarr) and shows (Sonarr) on import
# Output filename: "Title (Year).trailer.mkv" (optionally in TRAILER_SUBFOLDER)
# -----------------------------------------------------------------------------
# CONFIGURATION — edit fetch-trailer.conf, not this file
# -----------------------------------------------------------------------------

# Resolve script directory robustly — works whether sourced directly or via
# process substitution (as fetch-trailer-manual.sh does). Falls back to
# checking common install locations if BASH_SOURCE resolves to /dev/fd.
_raw_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$_raw_dir" == /dev/fd* ]]; then
    # Being sourced via process substitution — use caller's script dir instead
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${0}}")" && pwd)"
else
    SCRIPT_DIR="$_raw_dir"
fi
unset _raw_dir

CONF_FILE="${CONF_FILE:-${SCRIPT_DIR}/fetch-trailer.conf}"

if [[ -f "$CONF_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONF_FILE"
else
    echo "[WARN ] fetch-trailer.conf not found in $SCRIPT_DIR — using built-in defaults" >&2
fi

# Pre-declare arrays so they are always defined before conf is sourced.
# This prevents unbound variable errors under set -euo pipefail and allows
# the conf file to override them cleanly via normal assignment.
PREFERRED_TERMS=()
EXCLUDED_TERMS=()
RADARR_PREFERRED_TERMS=()
RADARR_EXCLUDED_TERMS=()
SONARR_PREFERRED_TERMS=()
SONARR_EXCLUDED_TERMS=()

CONF_FILE="${CONF_FILE:-${SCRIPT_DIR}/fetch-trailer.conf}"

if [[ -f "$CONF_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONF_FILE"
else
    echo "[WARN ] fetch-trailer.conf not found in $SCRIPT_DIR — using built-in defaults" >&2
fi

# --- Defaults (applied for any value not set by the conf file) ---------------
TMDB_API_KEY="${TMDB_API_KEY:-YOUR_TMDB_API_KEY_HERE}"
TRAILER_SUBFOLDER="${TRAILER_SUBFOLDER:-}"
_default_filename='{title} ({year}).trailer.mkv'
TRAILER_FILENAME="${TRAILER_FILENAME:-$_default_filename}"
unset _default_filename
if [[ ${#PREFERRED_TERMS[@]} -eq 0 ]]; then
    PREFERRED_TERMS=("Official Trailer" "Official US Trailer" "Main Trailer" "Trailer")
fi
if [[ ${#EXCLUDED_TERMS[@]} -eq 0 ]]; then
    EXCLUDED_TERMS=(
        "Teaser" "Clip" "Featurette" "Behind the Scenes" "Bloopers"
        "Opening" "Deleted Scene" "Interview" "Promo" "Sneak Peek"
        "Music Video" "Announcement" "Recap" "Extended Look" "First Look"
    )
fi
YTDLP_COOKIES_FILE="${YTDLP_COOKIES_FILE:-}"
DOWNLOAD_SUBTITLES="${DOWNLOAD_SUBTITLES:-true}"
YTDLP_EXTRA_ARGS="${YTDLP_EXTRA_ARGS:-}"
SKIP_IF_EXISTS="${SKIP_IF_EXISTS:-true}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
TMDB_RATE_DELAY="${TMDB_RATE_DELAY:-30}"
RATE_LIMIT_DIR="${RATE_LIMIT_DIR:-/config/scripts/tmp}"
LOG_FILE="${LOG_FILE:-/config/scripts/fetch-trailer.log}"
YT_DLP_BIN="${YT_DLP_BIN:-yt-dlp}"
JQ_BIN="${JQ_BIN:-jq}"

# DRY_RUN is intentionally not defaulted from conf — use --dry-run flag or
# export DRY_RUN=true in your shell. Conf-level dry-run would affect automation.
DRY_RUN="${DRY_RUN:-false}"

# -----------------------------------------------------------------------------
# END CONFIGURATION - DO NOT EDIT BELOW THIS LINE
# -----------------------------------------------------------------------------

# --- Logging -----------------------------------------------------------------
log() {
    local level="$1"; shift
    local msg="$*"
    local ts; ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [$level] $msg" >&2
    if [[ -n "$LOG_FILE" ]]; then
        local log_dir; log_dir="$(dirname "$LOG_FILE")"
        if [[ ! -d "$log_dir" ]]; then
            mkdir -p "$log_dir" 2>/dev/null || { echo "[$ts] [WARN ] Could not create log directory: $log_dir" >&2; LOG_FILE=""; }
        fi
        [[ -n "$LOG_FILE" ]] && echo "[$ts] [$level] $msg" >> "$LOG_FILE"
    fi
}

info()  { log "INFO " "$@"; }
warn()  { log "WARN " "$@"; }
error() { log "ERROR" "$@"; }
debug() { log "DEBUG" "$@"; }

# --- Argument parsing -------------------------------------------------------
# Parse --dry-run flag before anything else so it's available globally
for arg in "$@"; do
    [[ "$arg" == "--dry-run" ]] && DRY_RUN="true"
done

# --- Rate limiting -----------------------------------------------------------

# Enforce minimum delay between TMDB API calls across concurrent invocations.
# Uses a shared timestamp file — each run waits until TMDB_RATE_DELAY seconds
# have elapsed since the last run's TMDB calls before proceeding.
tmdb_rate_wait() {
    mkdir -p "$RATE_LIMIT_DIR"
    local ts_file="${RATE_LIMIT_DIR}/last-tmdb-call"
    local now; now="$(date +%s)"

    if [[ -f "$ts_file" ]]; then
        local last; last="$(cat "$ts_file" 2>/dev/null || echo 0)"
        [[ ! "$last" =~ ^[0-9]+$ ]] && last=0
        local elapsed=$(( now - last ))
        if (( elapsed < TMDB_RATE_DELAY )); then
            local wait=$(( TMDB_RATE_DELAY - elapsed ))
            info "Rate limiting: waiting ${wait}s before TMDB calls (last run ${elapsed}s ago)"
            sleep "$wait"
        fi
    fi

    echo "$(date +%s)" > "$ts_file"
}

# --- Dependency check ---------------------------------------------------------
check_deps() {
    local missing=()
    # In dry-run mode, yt-dlp isn't invoked so don't require it
    local required=("$JQ_BIN" curl)
    [[ "$DRY_RUN" != "true" ]] && required+=("$YT_DLP_BIN")
    for dep in "${required[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing required tools: ${missing[*]}"
        error "Install them in your container or update the *_BIN paths in this script."
        exit 1
    fi
}

# --- Determine media type (Radarr vs Sonarr) ----------------------------------
detect_source() {
    if [[ -n "${radarr_eventtype:-}" ]]; then
        echo "radarr"
    elif [[ -n "${sonarr_eventtype:-}" ]]; then
        echo "sonarr"
    else
        echo "unknown"
    fi
}

# --- Resolve media metadata from env vars ------------------------------------
resolve_metadata() {
    SOURCE="$(detect_source)"

    case "$SOURCE" in
        radarr)
            MEDIA_TYPE="movie"
            MEDIA_TITLE="${radarr_movie_title:-}"
            MEDIA_YEAR="${radarr_movie_year:-}"
            TMDB_ID="${radarr_movie_tmdbid:-}"
            MEDIA_PATH="${radarr_movie_path:-}"
            EVENT_TYPE="${radarr_eventtype:-}"
            ;;
        sonarr)
            MEDIA_TYPE="tv"
            MEDIA_TITLE="${sonarr_series_title:-}"
            MEDIA_YEAR="${sonarr_series_year:-}"
            TMDB_ID="${sonarr_series_tmdbid:-}"
            MEDIA_PATH="${sonarr_series_path:-}"
            EVENT_TYPE="${sonarr_eventtype:-}"
            ;;
        *)
            error "Could not detect Radarr or Sonarr environment variables."
            error "This script must be called by Radarr or Sonarr as a Custom Script. Did you mean to run fetch-trailer-manual.sh?"
            exit 1
            ;;
    esac

    # Sonarr doesn't always export TMDB ID — fall back to TVDB lookup if needed
    if [[ -z "$TMDB_ID" && "$SOURCE" == "sonarr" ]]; then
        TVDB_ID="${sonarr_series_tvdbid:-}"
        if [[ -n "$TVDB_ID" ]]; then
            info "No TMDB ID from Sonarr; looking up via TVDB ID $TVDB_ID"
            TMDB_ID="$(tmdb_id_from_tvdb "$TVDB_ID")"
        fi
    fi

    # Sonarr sometimes appends a year disambiguator to the series title
    # (e.g. "Doctor Who (2005)") which would produce "Doctor Who (2005) (2005)"
    # in the output filename. Strip the trailing (YYYY) if present.
    if [[ "$SOURCE" == "sonarr" ]]; then
        MEDIA_TITLE="$(echo "$MEDIA_TITLE" | sed 's/ ([0-9]\{4\})$//')"
    fi

    # Merge per-source terms into global lists (additive, no replacement).
    # Per-source preferred terms prepend (higher priority); excluded terms append.
    local _src_upper="${SOURCE^^}"
    local _pref_var="${_src_upper}_PREFERRED_TERMS[@]"
    local _excl_var="${_src_upper}_EXCLUDED_TERMS[@]"
    local _pref_extra=("${!_pref_var-}")
    local _excl_extra=("${!_excl_var-}")

    if [[ ${#_pref_extra[@]} -gt 0 && -n "${_pref_extra[0]}" ]]; then
        PREFERRED_TERMS=("${_pref_extra[@]}" "${PREFERRED_TERMS[@]}")
        info "Merged ${#_pref_extra[@]} ${SOURCE}-specific preferred term(s) — ${#PREFERRED_TERMS[@]} total"
    fi
    if [[ ${#_excl_extra[@]} -gt 0 && -n "${_excl_extra[0]}" ]]; then
        EXCLUDED_TERMS=("${EXCLUDED_TERMS[@]}" "${_excl_extra[@]}")
        info "Merged ${#_excl_extra[@]} ${SOURCE}-specific excluded term(s) — ${#EXCLUDED_TERMS[@]} total"
    fi
}

# --- TMDB helpers -------------------------------------------------------------
tmdb_get() {
    local endpoint="$1"
    curl -sf \
        -H "Authorization: Bearer $TMDB_API_KEY" \
        -H "Accept: application/json" \
        "https://api.themoviedb.org/3${endpoint}"
}

# Look up TMDB series ID from a TVDB ID
tmdb_id_from_tvdb() {
    local tvdb_id="$1"
    tmdb_get "/find/${tvdb_id}?external_source=tvdb_id" \
        | "$JQ_BIN" -r '.tv_results[0].id // empty'
}

# Fetch the original language of the media (ISO 639-1 code, e.g. "ko", "ja", "fr")
tmdb_fetch_original_language() {
    local tmdb_id="$1"
    local media_type="$2"
    tmdb_get "/${media_type}/${tmdb_id}?language=en-US" \
        | "$JQ_BIN" -r '.original_language // empty'
}

# Fetch videos list from TMDB, merging en-US and original language results.
# Each result is tagged with an "is_orig_lang" boolean for scoring.
tmdb_fetch_videos() {
    local tmdb_id="$1"
    local media_type="$2"
    local orig_lang="${3:-}"

    local en_videos orig_videos combined

    en_videos="$(tmdb_get "/${media_type}/${tmdb_id}/videos?language=en-US")"

    # If original language is set and non-English, fetch that language's results and tag them
    if [[ -n "$orig_lang" && "$orig_lang" != "en" ]]; then
        orig_videos="$(tmdb_get "/${media_type}/${tmdb_id}/videos?language=${orig_lang}-${orig_lang^^}")"

        # Merge: tag orig-lang videos, deduplicate by YouTube key
        combined="$(
            "$JQ_BIN" -n \
                --argjson en "$en_videos" \
                --argjson orig "$orig_videos" \
                --arg lang "$orig_lang" '
                ($orig.results // [] | map(.key)) as $orig_keys |
                ($en.results // [] | map(. + {is_orig_lang: (.iso_639_1 == $lang)})) as $en_tagged |
                ($orig.results // [] | map(. + {is_orig_lang: true})) as $orig_tagged |
                ($orig_tagged + ($en_tagged | map(select(.key as $k | $orig_keys | index($k) | not))))
                | {results: .}
            '
        )"
        echo "$combined"
    else
        # Just pass through en-US results, tagging is_orig_lang=false
        echo "$en_videos" | "$JQ_BIN" '.results = (.results // [] | map(. + {is_orig_lang: false})) | .'
    fi
}

# --- Trailer selection --------------------------------------------------------

# Returns 1 if a string (lowercased) matches any term in an array
matches_any() {
    local haystack; haystack="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
    shift
    for term in "$@"; do
        local needle; needle="$(echo "$term" | tr '[:upper:]' '[:lower:]')"
        if [[ "$haystack" == *"$needle"* ]]; then
            return 0
        fi
    done
    return 1
}

# Given a JSON array of TMDB video objects (with is_orig_lang tag), pick the best YouTube trailer key
pick_best_trailer() {
    local videos_json="$1"

    # Pull out only YouTube Trailer-type videos, sort: orig-lang first, then by date desc
    local candidates
    candidates="$(echo "$videos_json" | "$JQ_BIN" -c '
        .results
        | map(select(.site == "YouTube" and .type == "Trailer"))
        | sort_by([(.is_orig_lang | not), (.published_at | . // "" | . )])
        | reverse
    ')"

    local count
    count="$(echo "$candidates" | "$JQ_BIN" 'length')"
    info "Found $count YouTube trailers on TMDB"

    if [[ "$count" -eq 0 ]]; then
        return 1
    fi

    # Helper: run one selection pass over a candidate subset
    _try_pick() {
        local pool="$1"
        for term in "${PREFERRED_TERMS[@]}"; do
            while IFS= read -r video; do
                local name key
                name="$(echo "$video" | "$JQ_BIN" -r '.name')"
                key="$(echo "$video" | "$JQ_BIN" -r '.key')"
                local is_orig
                is_orig="$(echo "$video" | "$JQ_BIN" -r '.is_orig_lang')"

                if matches_any "$name" "${EXCLUDED_TERMS[@]}"; then
                    continue
                fi
                if matches_any "$name" "$term"; then
                    local tag=""
                    [[ "$is_orig" == "true" ]] && tag=" [orig-lang]"
                    info "Selected trailer (matched '$term'$tag): $name [$key]"
                    echo "$key"
                    return 0
                fi
            done < <(echo "$pool" | "$JQ_BIN" -c '.[]')
        done

        # Fallback: first non-excluded
        while IFS= read -r video; do
            local name key is_orig
            name="$(echo "$video" | "$JQ_BIN" -r '.name')"
            key="$(echo "$video" | "$JQ_BIN" -r '.key')"
            is_orig="$(echo "$video" | "$JQ_BIN" -r '.is_orig_lang')"
            if matches_any "$name" "${EXCLUDED_TERMS[@]}"; then
                continue
            fi
            local tag=""
            [[ "$is_orig" == "true" ]] && tag=" [orig-lang]"
            info "Selected trailer (fallback$tag): $name [$key]"
            echo "$key"
            return 0
        done < <(echo "$pool" | "$JQ_BIN" -c '.[]')

        return 1
    }

    # First pass: English-pool [Subtitled] candidates only.
    # Scoped to is_orig_lang==false to avoid picking dubbed non-English trailers
    # that happen to have [Subtitled] in their TMDB title.
    # This catches patterns like "Official US Trailer [Subtitled]" for
    # Korean/Japanese films where the English-distributed trailer has burned-in subs.
    local en_pool
    en_pool="$(echo "$candidates" | "$JQ_BIN" -c '[.[] | select(.is_orig_lang == false)]')"
    local subtitled_pool
    subtitled_pool="$(echo "$en_pool" | "$JQ_BIN" -c '[.[] | select(.name | ascii_downcase | contains("subtitled"))]')"
    local subtitled_count
    subtitled_count="$(echo "$subtitled_pool" | "$JQ_BIN" 'length')"

    if [[ "$subtitled_count" -gt 0 ]]; then
        info "Found $subtitled_count English [Subtitled] candidate(s) — checking first"
        local result
        result="$(_try_pick "$subtitled_pool")"
        if [[ -n "$result" ]]; then
            echo "$result"
            return 0
        fi
        info "No preferred-term match in [Subtitled] pool — continuing"
    fi

    # Second pass: original-language candidates (non-English media only)
    if [[ -n "$orig_lang" && "$orig_lang" != "en" ]]; then
        local orig_pool
        orig_pool="$(echo "$candidates" | "$JQ_BIN" -c '[.[] | select(.is_orig_lang == true)]')"
        local orig_count
        orig_count="$(echo "$orig_pool" | "$JQ_BIN" 'length')"

        if [[ "$orig_count" -gt 0 ]]; then
            info "Trying original-language pool ($orig_count candidates)"
            local result
            result="$(_try_pick "$orig_pool")"
            if [[ -n "$result" ]]; then
                echo "$result"
                return 0
            fi
            info "No match in original-language pool — falling back to full pool"
        else
            info "No original-language trailers found on TMDB — using full pool"
        fi
    fi

    # Third pass: full pool
    local result
    result="$(_try_pick "$candidates")"
    if [[ -n "$result" ]]; then
        echo "$result"
        return 0
    fi

    warn "All TMDB trailers matched exclusion terms — using first available as last resort"
    "$JQ_BIN" -r '.[0].key' <<< "$candidates"
    return 0
}

# --- Filename construction ----------------------------------------------------
build_output_path() {
    local media_path="$1"
    local title="$2"
    local year="$3"

    # Sanitize title for filesystem use
    local safe_title
    safe_title="$(echo "$title" | tr -d '/:*?"<>|\\' | sed 's/  */ /g' | sed 's/[[:space:]]*$//')"

    # Substitute {title} and {year} in the filename template
    local filename
    filename="${TRAILER_FILENAME//\{title\}/$safe_title}"
    filename="${filename//\{year\}/$year}"

    local dest="$media_path"
    if [[ -n "$TRAILER_SUBFOLDER" ]]; then
        dest="${media_path}/${TRAILER_SUBFOLDER}"
        mkdir -p "$dest"
    fi

    echo "${dest}/${filename}"
}

# --- Check for existing trailer -----------------------------------------------
trailer_exists() {
    local media_path="$1"
    # Match "Title (Year).trailer.mkv" and legacy "-trailer.mkv" patterns
    if find "$media_path" -maxdepth 2 -type f \
        \( -name "*.trailer.mkv" -o -name "*.trailer.mp4" -o -name "*-trailer.mkv" -o -name "*-trailer.mp4" \) \
        2>/dev/null | grep -q .; then
        return 0
    fi
    return 1
}

# --- Download -----------------------------------------------------------------
download_trailer() {
    local yt_key="$1"
    local output_path="$2"
    local orig_lang="${3:-}"
    local media_title="${4:-}"
    local media_year="${5:-}"
    local url="https://www.youtube.com/watch?v=${yt_key}"
    local workdir
    workdir="$(dirname "$output_path")"
    local tmpbase="${workdir}/.trailer-tmp-${yt_key}"

    # --- Build base yt-dlp args -----------------------------------------------
    # Set MKV title tag explicitly so Jellyfin shows the correct title
    # instead of whatever metadata the YouTube uploader embedded.
    local mkv_title="${media_title} (${media_year}) - Trailer"
    local ytdlp_args=(
        --format "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        --merge-output-format mkv
        --no-playlist
        --no-warnings
        --output "${tmpbase}.%(ext)s"
        --retries 3
        --fragment-retries 3
        --abort-on-error
        --parse-metadata "title:%(meta_title)s"
        --replace-in-metadata "title" ".*" "$mkv_title"
    )

    # Cookies (file only)
    if [[ -n "$YTDLP_COOKIES_FILE" && -f "$YTDLP_COOKIES_FILE" ]]; then
        ytdlp_args+=(--cookies "$YTDLP_COOKIES_FILE")
        info "Using cookies file: $YTDLP_COOKIES_FILE"
    elif [[ -n "$YTDLP_COOKIES_FILE" ]]; then
        warn "YTDLP_COOKIES_FILE is set but file not found: $YTDLP_COOKIES_FILE"
    fi

    # Subtitles — sidecar .srt, only for non-English media
    local sub_tmpbase="${workdir}/.trailer-sub-${yt_key}"
    local sub_file=""
    if [[ "$DOWNLOAD_SUBTITLES" == "true" && -n "$orig_lang" && "$orig_lang" != "en" ]]; then
        local ytdlp_sub_args=(
            --skip-download
            --write-subs
            --write-auto-subs
            --sub-langs "en,en-US"
            --sub-format "srt/best"
            --convert-subs srt
            --output "${sub_tmpbase}.%(ext)s"
            --no-warnings
        )
        if [[ -n "$YTDLP_COOKIES_FILE" && -f "$YTDLP_COOKIES_FILE" ]]; then
            ytdlp_sub_args+=(--cookies "$YTDLP_COOKIES_FILE")
        fi

        info "Fetching English subtitles for non-English media ($orig_lang)..."
        # Subtitle fetch is best-effort — not all videos have subs available.
        # Failure here is non-fatal; the trailer download proceeds regardless.
        "$YT_DLP_BIN" "${ytdlp_sub_args[@]}" "$url" 2>/dev/null || true

        sub_file="$(find "$workdir" -maxdepth 1 -name ".trailer-sub-${yt_key}.*.srt" 2>/dev/null | head -1)"
        if [[ -n "$sub_file" ]]; then
            info "Subtitles found: $(basename "$sub_file")"
        else
            info "No English subtitles available — continuing without them"
        fi
    fi

    if [[ -n "$YTDLP_EXTRA_ARGS" ]]; then
        # Word splitting is intentional here — YTDLP_EXTRA_ARGS is a
        # space-separated list of flags (e.g. "--proxy socks5://...").
        # Do not put secrets in this value as it may be visible
        # in process listings.
        # shellcheck disable=SC2206
        ytdlp_args+=($YTDLP_EXTRA_ARGS)
    fi

    # --- Download video -------------------------------------------------------
    info "Downloading video: $url"
    info "Output target: $output_path"

    if ! "$YT_DLP_BIN" "${ytdlp_args[@]}" "$url"; then
        warn "yt-dlp failed for $url"
        find "$workdir" -maxdepth 1 -name ".trailer-tmp-${yt_key}.*" -delete 2>/dev/null
        find "$workdir" -maxdepth 1 -name ".trailer-sub-${yt_key}.*" -delete 2>/dev/null
        return 1
    fi

    local downloaded
    downloaded="$(find "$workdir" -maxdepth 1 -name ".trailer-tmp-${yt_key}.*" 2>/dev/null | head -1)"
    if [[ -z "$downloaded" ]]; then
        error "yt-dlp succeeded but output file not found"
        return 1
    fi

    mv -- "$downloaded" "$output_path"

    # --- Sidecar subtitle ---------------------------------------------------
    if [[ -n "$sub_file" && -f "$sub_file" ]]; then
        # Derive sidecar path from output path: swap .mkv → .en.srt
        local sidecar_path="${output_path%.mkv}.en.srt"
        mv -- "$sub_file" "$sidecar_path"
        info "Subtitle sidecar saved: $(basename "$sidecar_path")"
    fi

    # Clean up any leftover temp files
    find "$workdir" -maxdepth 1 -name ".trailer-tmp-${yt_key}.*" -delete 2>/dev/null
    find "$workdir" -maxdepth 1 -name ".trailer-sub-${yt_key}.*" -delete 2>/dev/null

    info "Saved trailer to: $output_path"
    return 0
}

# --- Discord notification -----------------------------------------------------
notify_discord() {
    [[ -z "$DISCORD_WEBHOOK_URL" ]] && return 0
    local message="$1"
    # Escape backslashes and double-quotes for JSON safety
    local escaped
    escaped="$(echo "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$escaped\"}" > /dev/null || warn "Discord notification failed"
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    # Parse --dry-run flag from positional args
    for arg in "$@"; do
        [[ "$arg" == "--dry-run" ]] && DRY_RUN="true"
    done

    [[ "$DRY_RUN" == "true" ]] && info "*** DRY-RUN MODE — no files will be written ***"

    check_deps
    resolve_metadata

    info "=== fetch-trailer.sh ==="
    info "Source   : $SOURCE ($EVENT_TYPE)"
    info "Title    : $MEDIA_TITLE ($MEDIA_YEAR)"
    info "TMDB ID  : $TMDB_ID"
    info "Path     : $MEDIA_PATH"

    # Radarr/Sonarr fire test events — bail out cleanly
    if [[ "${EVENT_TYPE,,}" == "test" ]]; then
        info "Test event received — exiting cleanly."
        exit 0
    fi

    # Validate required fields
    if [[ -z "$MEDIA_TITLE" || -z "$MEDIA_PATH" ]]; then
        error "Missing title or media path from $SOURCE env vars."
        exit 1
    fi

    if [[ -z "$TMDB_API_KEY" || "$TMDB_API_KEY" == "YOUR_TMDB_API_KEY_HERE" ]]; then
        error "TMDB_API_KEY is not set. Edit the script or export the variable."
        exit 1
    fi

    # Skip if trailer already exists (suppress in dry-run so you can re-inspect)
    if [[ "$DRY_RUN" != "true" && "$SKIP_IF_EXISTS" == "true" ]] && trailer_exists "$MEDIA_PATH"; then
        info "Trailer already exists in $MEDIA_PATH — skipping."
        exit 0
    fi

    if [[ "$SOURCE" == "sonarr" ]]; then
        info "Sonarr: fetching series-level trailer for $MEDIA_TITLE"
    fi

    # Enforce TMDB rate delay before any API calls
    tmdb_rate_wait

    # TMDB lookup
    if [[ -z "$TMDB_ID" ]]; then
        warn "No TMDB ID available — attempting title search"
        local encoded_title
        encoded_title="$("$JQ_BIN" -rn --arg x "$MEDIA_TITLE" '$x | @uri')"
        if [[ "$MEDIA_TYPE" == "movie" ]]; then
            TMDB_ID="$(tmdb_get "/search/movie?query=${encoded_title}&year=${MEDIA_YEAR}" \
                | "$JQ_BIN" -r '.results[0].id // empty')"
        else
            TMDB_ID="$(tmdb_get "/search/tv?query=${encoded_title}" \
                | "$JQ_BIN" -r '.results[0].id // empty')"
        fi
        info "TMDB search result ID: $TMDB_ID"
    fi

    if [[ -z "$TMDB_ID" ]]; then
        error "Could not resolve TMDB ID for '$MEDIA_TITLE'. Skipping."
        exit 1
    fi

    # Fetch original language from TMDB
    local orig_lang=""
    if [[ "$DOWNLOAD_SUBTITLES" == "true" ]]; then
        orig_lang="$(tmdb_fetch_original_language "$TMDB_ID" "$MEDIA_TYPE")"
        if [[ -n "$orig_lang" ]]; then
            info "Original language: $orig_lang"
        else
            warn "Could not determine original language from TMDB"
        fi
    fi

    # Fetch videos from TMDB (merged en-US + original language if applicable)
    local videos_json
    videos_json="$(tmdb_fetch_videos "$TMDB_ID" "$MEDIA_TYPE" "$orig_lang")"

    if [[ -z "$videos_json" ]]; then
        error "Empty response from TMDB videos endpoint."
        exit 1
    fi

    # Pick best trailer
    local yt_key
    yt_key="$(pick_best_trailer "$videos_json")"

    if [[ -z "$yt_key" ]]; then
        warn "No suitable trailer found on TMDB for '$MEDIA_TITLE'."
        exit 0
    fi

    # Build output path
    local output_path
    output_path="$(build_output_path "$MEDIA_PATH" "$MEDIA_TITLE" "${MEDIA_YEAR:-0000}")"

    # --- Dry-run report -------------------------------------------------------
    if [[ "$DRY_RUN" == "true" ]]; then

        # Subtitle note for header
        local sub_note="disabled"
        if [[ "$DOWNLOAD_SUBTITLES" == "true" ]]; then
            if [[ -n "$orig_lang" && "$orig_lang" != "en" ]]; then
                sub_note="en sidecar (non-English media)"
            else
                sub_note="skipped (English media)"
            fi
        fi

        # Collect all non-excluded YouTube trailer candidates for the report
        local all_candidates
        all_candidates="$(echo "$videos_json" | "$JQ_BIN" -c '
            .results
            | map(select(.site == "YouTube" and .type == "Trailer"))
            | sort_by([(.is_orig_lang | not), (.published_at | . // "")])
            | reverse
        ')"
        local total
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

        local idx=0
        while IFS= read -r candidate; do
            idx=$(( idx + 1 ))
            local c_key c_name c_is_orig c_date
            c_key="$(echo "$candidate"  | "$JQ_BIN" -r '.key')"
            c_name="$(echo "$candidate" | "$JQ_BIN" -r '.name')"
            c_is_orig="$(echo "$candidate" | "$JQ_BIN" -r '.is_orig_lang')"
            c_date="$(echo "$candidate" | "$JQ_BIN" -r '.published_at // "unknown date"' | cut -c1-10)"

            local lang_tag="  en"
            [[ "$c_is_orig" == "true" ]] && lang_tag="orig"

            # Mark excluded candidates
            local excluded_tag=""
            if matches_any "$c_name" "${EXCLUDED_TERMS[@]}"; then
                excluded_tag=" [EXCLUDED]"
            fi

            # Mark the selected candidate
            local selected_tag=""
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
        notify_discord "🎬 Trailer downloaded: **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${yt_key}"
        exit 0
    else
        error "Trailer download failed for '$MEDIA_TITLE'"
        notify_discord "⚠️ Trailer download failed: **$MEDIA_TITLE ($MEDIA_YEAR)** — https://www.youtube.com/watch?v=${yt_key}"
        exit 1
    fi
}

main "$@"