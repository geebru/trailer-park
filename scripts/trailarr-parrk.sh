#!/usr/bin/env bash
# =====================================================================
# Trailarr Parrk
# Triggered by Radarr (on import/upgrade) or Sonarr (on series add).
# Fetches the best available trailer from TMDB/YouTube via yt-dlp.
#
# Manual usage (run from inside the container):
#   --movie   "Title"   Search by movie title (fuzzy)
#   --series  "Title"   Search by series title (fuzzy, targets Sonarr)
#   --id      <tmdb_id> TMDB ID (precise, skips title search)
#   --path    "/path"   Media path (precise, skips title search)
#   --yt-id   <yt_id>   Skip TMDB, download this YouTube ID directly
#   --dry-run           Log actions without downloading
# =====================================================================

set -euo pipefail

# =====================================================================
# Config
# =====================================================================

CONFIG_FILE="/config/scripts/trailarr-parrk.conf"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "[Trailarr Parrk] ERROR: Config file not found at $CONFIG_FILE"
  exit 1
fi
source "$CONFIG_FILE"

# =====================================================================
# Helpers
# =====================================================================

log() {
  echo "[Trailarr Parrk] $1"
}

# Wraps any command — prints it in dry-run mode, executes it otherwise
run_cmd() {
  if [ "${DRY_RUN:-false}" = "true" ]; then
    echo "[Trailarr Parrk] [DRY RUN] $*"
  else
    "$@" || {
      notify_discord "**$TITLE (${YEAR:-unknown})**\n⚠️ Trailer download failed"
      log "ERROR: Download failed"
      exit 1
    }
  fi
}

# URL-encodes a string using Python (handles all special characters)
url_encode() {
  python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$1"
}

# Sends a message to Discord via webhook — silent no-op if not configured
notify_discord() {
  [ -z "${DISCORD_WEBHOOK:-}" ] && return
  local message="🎬 **Trailarr Parrk**\n$1"
  [ "${DRY_RUN:-false}" = "true" ] && log "[DRY RUN] Discord notification: $message" && return
  curl -sf -X POST "$DISCORD_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "{\"content\": \"$message\"}" >/dev/null \
    && log "Discord notification sent" \
    || log "Discord notification failed (webhook error)"
}

# =====================================================================
# Flag Parsing
# Flags override env vars — env vars are the fallback for triggered runs.
# =====================================================================

ARG_TITLE=""
ARG_ID=""
ARG_PATH=""
ARG_YT_ID=""
ARG_MEDIA_TYPE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --movie)   ARG_TITLE="$2";  ARG_MEDIA_TYPE="movie"; shift 2 ;;
    --series)  ARG_TITLE="$2";  ARG_MEDIA_TYPE="tv";    shift 2 ;;
    --id)      ARG_ID="$2";                              shift 2 ;;
    --path)    ARG_PATH="$2";                            shift 2 ;;
    --yt-id)   ARG_YT_ID="$2";                           shift 2 ;;
    --dry-run) DRY_RUN=true;                             shift   ;;
    *)
      log "ERROR: Unknown flag: $1"
      log "Usage: trailarr-parrk.sh [--movie|--series \"Title\"] [--id <tmdb_id>] [--path \"/path\"] [--yt-id <yt_id>] [--dry-run]"
      exit 1
      ;;
  esac
done

# =====================================================================
# Lock File (prevents parallel runs from hammering the API)
# Uses noclobber for atomic creation — avoids TOCTOU race condition
# =====================================================================

LOCK_FILE="/tmp/trailarr-parrk.lock"

acquire_lock() {
  while ! (set -o noclobber; echo $$ > "$LOCK_FILE") 2>/dev/null; do
    sleep 1
  done
}

release_lock() {
  rm -f "$LOCK_FILE"
}

trap release_lock EXIT

# =====================================================================
# TMDB Rate Limiter
# Tracks call count within a rolling window.
# Shared state is stored in a temp file between invocations.
# =====================================================================

RATE_FILE="/tmp/trailarr-parrk.rate"

rate_limit() {
  local now
  now=$(date +%s)

  if [ ! -f "$RATE_FILE" ]; then
    echo "$now 1" > "$RATE_FILE"
    return
  fi

  local start count
  read -r start count < "$RATE_FILE"

  if (( now - start < WINDOW_SECONDS )); then
    if (( count >= MAX_CALLS )); then
      local sleep_for=$(( WINDOW_SECONDS - (now - start) ))
      log "Rate limit reached — waiting ${sleep_for}s"
      sleep "$sleep_for"
      echo "$(date +%s) 1" > "$RATE_FILE"
    else
      echo "$start $(( count + 1 ))" > "$RATE_FILE"
    fi
  else
    echo "$now 1" > "$RATE_FILE"
  fi
}

# Wraps all TMDB calls: acquire lock → rate limit → curl → release lock
tmdb_call() {
  local url="$1"
  acquire_lock
  rate_limit
  local response
  response=$(curl -sf "$url") || { log "TMDB request failed (redacted)"; release_lock; exit 1; }
  release_lock
  echo "$response"
}

# =====================================================================
# Detect Context (flags → env vars → error)
# =====================================================================

if [ -n "$ARG_MEDIA_TYPE" ]; then
  # Invoked manually with --movie or --series
  MEDIA_TYPE="$ARG_MEDIA_TYPE"
  TITLE="$ARG_TITLE"
  TMDB_ID="${ARG_ID:-}"
  MEDIA_PATH="${ARG_PATH:-}"

  # Resolve missing TMDB ID from title via TMDB search
  if [ -z "$TMDB_ID" ] && [ -n "$TITLE" ]; then
    local_endpoint="movie"
    [ "$MEDIA_TYPE" = "tv" ] && local_endpoint="tv"
    ENCODED_TITLE=$(url_encode "$TITLE")
    SEARCH=$(tmdb_call "https://api.themoviedb.org/3/search/${local_endpoint}?api_key=${TMDB_API_KEY}&query=${ENCODED_TITLE}")

    MATCH_COUNT=$(echo "$SEARCH" | jq '.results | length')
    if [ "$MATCH_COUNT" -eq 0 ]; then
      log "ERROR: No TMDB match found for: $TITLE"
      exit 1
    elif [ "$MATCH_COUNT" -gt 1 ] && [ -z "$ARG_ID" ] && [ -z "$ARG_PATH" ]; then
      log "Multiple matches found for \"$TITLE\" — re-run with --id to specify:"
      for (( i=0; i<MATCH_COUNT && i<5; i++ )); do
        MATCH=$(echo "$SEARCH" | jq ".results[$i]")
        MATCH_ID=$(echo "$MATCH" | jq -r '.id')
        MATCH_TITLE=$(echo "$MATCH" | jq -r '.title // .name')
        MATCH_YEAR=$(echo "$MATCH" | jq -r '.release_date[:4] // .first_air_date[:4] // "unknown"')
        echo "           --id $MATCH_ID  $MATCH_TITLE ($MATCH_YEAR)"
      done
      exit 1
    fi

    TMDB_ID=$(echo "$SEARCH" | jq -r '.results[0].id')
  fi

  if [ -z "$TMDB_ID" ]; then
    log "ERROR: Could not resolve TMDB ID — provide --id or a searchable --movie/--series title"
    exit 1
  fi

elif [ -n "${radarr_movie_tmdbid:-}" ]; then
  # Triggered by Radarr
  MEDIA_TYPE="movie"
  TMDB_ID="$radarr_movie_tmdbid"
  TITLE="$radarr_movie_title"
  MEDIA_PATH="$radarr_movie_path"

elif [ -n "${sonarr_series_title:-}" ]; then
  # Triggered by Sonarr
  MEDIA_TYPE="tv"
  TITLE="$sonarr_series_title"
  MEDIA_PATH="$sonarr_series_path"

  log "Searching TMDB for series: $TITLE"
  ENCODED_TITLE=$(url_encode "$TITLE")
  SEARCH=$(tmdb_call "https://api.themoviedb.org/3/search/tv?api_key=${TMDB_API_KEY}&query=${ENCODED_TITLE}")

  TMDB_ID=$(echo "$SEARCH" | jq -r '.results[0].id // empty')
  if [ -z "$TMDB_ID" ]; then
    log "ERROR: No TMDB match found for series: $TITLE"
    exit 1
  fi

else
  log "No flags or Radarr/Sonarr environment variables detected — nothing to do"
  exit 0
fi

log "Title:     $TITLE"
log "TMDB ID:   $TMDB_ID"
log "Type:      $MEDIA_TYPE"

# =====================================================================
# Fetch Media Details (year + original language)
# =====================================================================

MEDIA_DETAILS=$(tmdb_call "https://api.themoviedb.org/3/${MEDIA_TYPE}/${TMDB_ID}?api_key=${TMDB_API_KEY}")

ORIG_LANG=$(echo "$MEDIA_DETAILS" | jq -r '.original_language // "en"')

# Resolve title from TMDB if only --id was passed
if [ -z "${TITLE:-}" ]; then
  TITLE=$(echo "$MEDIA_DETAILS" | jq -r '.title // .name')
fi

if [ "$MEDIA_TYPE" = "movie" ]; then
  YEAR=$(echo "$MEDIA_DETAILS" | jq -r '.release_date[:4] // empty')
else
  YEAR=$(echo "$MEDIA_DETAILS" | jq -r '.first_air_date[:4] // empty')
fi

log "Year:      ${YEAR:-(unknown)}"
log "Language:  $ORIG_LANG"

# MEDIA_PATH is required for output — error clearly if still missing
if [ -z "${MEDIA_PATH:-}" ]; then
  log "ERROR: No media path available — provide --path \"/media/Title (Year)\""
  exit 1
fi

# =====================================================================
# Output Path
# =====================================================================

SAFE_TITLE=$(echo "$TITLE" | sed 's|[/\\:*?"<>|]|-|g')

if [ -n "${TRAILER_SUBDIR:-}" ]; then
  OUT_DIR="$MEDIA_PATH/$TRAILER_SUBDIR"
else
  OUT_DIR="$MEDIA_PATH"
fi
mkdir -p "$OUT_DIR"

if [ -n "${FILENAME_OVERRIDE:-}" ]; then
  BASE_NAME="$FILENAME_OVERRIDE"
elif [ -n "$YEAR" ]; then
  BASE_NAME="${SAFE_TITLE} (${YEAR}).trailer"
else
  BASE_NAME="${SAFE_TITLE}.trailer"
fi

OUTPUT_FILE="$OUT_DIR/${BASE_NAME}.mkv"

log "Output:    $OUTPUT_FILE"

# =====================================================================
# Manual Mode — skip TMDB lookup and download a specific YouTube video
# Triggered by --yt-id flag. Skips scoring, filtering, and
# the existing-file check entirely.
# =====================================================================

if [ -n "${ARG_YT_ID:-}" ]; then
  YOUTUBE_URL="https://www.youtube.com/watch?v=${ARG_YT_ID}"
  log "Manual mode — using provided YouTube ID: $ARG_YT_ID"
  log "URL:       $YOUTUBE_URL"

  YTDLP_OPTS=(
    -f "bv*[height<=1080]+ba/b[height<=1080]"
    --merge-output-format mkv
    -o "$OUTPUT_FILE"
  )
  [ -n "${YT_COOKIES:-}" ] && YTDLP_OPTS+=(--cookies "$YT_COOKIES")

  log "Downloading..."
  run_cmd yt-dlp "${YTDLP_OPTS[@]}" "$YOUTUBE_URL"

  notify_discord "**$TITLE (${YEAR:-unknown})**\n✅ Trailer manually replaced!\n$YOUTUBE_URL"
  log "Done — trailer saved to: $OUTPUT_FILE"
  exit 0
fi

# =====================================================================
# Normal Mode — skip if trailer already exists
# =====================================================================

if [ -f "$OUTPUT_FILE" ]; then
  log "Trailer already exists — skipping (use --yt-id <id> to replace)"
  exit 0
fi

# =====================================================================
# Fetch Available Videos from TMDB
# =====================================================================

VIDEOS=$(tmdb_call "https://api.themoviedb.org/3/${MEDIA_TYPE}/${TMDB_ID}/videos?api_key=${TMDB_API_KEY}")

VIDEO_COUNT=$(echo "$VIDEOS" | jq '.results | length // 0')
if [ "$VIDEO_COUNT" -eq 0 ]; then
  notify_discord "**$TITLE (${YEAR:-unknown})**\n⚠️ No trailers found on TMDB"
  log "No videos found on TMDB for this title"
  exit 0
fi

log "Found $VIDEO_COUNT video(s) on TMDB"

# =====================================================================
# Trailer Selection
# Scoring priority:
#   +60  — matches original language
#   +40  — English fallback
#   +20  — each matched preferred term in the name
#   skip — any excluded term in name, or no preferred term match
# =====================================================================

BEST_SCORE=-1
BEST_KEY=""
BEST_NAME=""

for (( i=0; i<VIDEO_COUNT; i++ )); do
  ITEM=$(echo "$VIDEOS" | jq ".results[$i]")

  VIDEO_TYPE=$(echo "$ITEM" | jq -r '.type')
  VIDEO_NAME=$(echo "$ITEM" | jq -r '.name' | tr '[:upper:]' '[:lower:]')
  VIDEO_LANG=$(echo "$ITEM" | jq -r '.iso_639_1')
  VIDEO_KEY=$(echo "$ITEM"  | jq -r '.key')

  [ "$VIDEO_TYPE" != "Trailer" ] && continue

  local_skip=false
  for term in "${EXCLUDED_TERMS[@]}"; do
    if [[ "$VIDEO_NAME" == *"$term"* ]]; then
      local_skip=true
      break
    fi
  done
  [ "$local_skip" = true ] && continue

  if [ "${#PREFERRED_TERMS[@]}" -gt 0 ]; then
    local_match=false
    for term in "${PREFERRED_TERMS[@]}"; do
      [[ "$VIDEO_NAME" == *"$term"* ]] && local_match=true && break
    done
    [ "$local_match" = false ] && continue
  fi

  SCORE=0

  if [ "$VIDEO_LANG" = "$ORIG_LANG" ]; then
    SCORE=$(( SCORE + 60 ))
  elif [ "$VIDEO_LANG" = "en" ]; then
    SCORE=$(( SCORE + 40 ))
  fi

  for term in "${PREFERRED_TERMS[@]}"; do
    [[ "$VIDEO_NAME" == *"$term"* ]] && SCORE=$(( SCORE + 20 ))
  done

  if (( SCORE > BEST_SCORE )); then
    BEST_SCORE=$SCORE
    BEST_KEY=$VIDEO_KEY
    BEST_NAME=$(echo "$ITEM" | jq -r '.name')
  fi
done

if [ -z "$BEST_KEY" ]; then
  notify_discord "**$TITLE (${YEAR:-unknown})**\n⚠️ No trailer passed filtering (${VIDEO_COUNT} videos checked)"
  log "No suitable trailer found after filtering"
  exit 0
fi

YOUTUBE_URL="https://www.youtube.com/watch?v=${BEST_KEY}"
log "Selected:  $BEST_NAME"
log "URL:       $YOUTUBE_URL (score: $BEST_SCORE)"

# =====================================================================
# Download Trailer
# =====================================================================

YTDLP_OPTS=(
  -f "bv*[height<=1080]+ba/b[height<=1080]"
  --merge-output-format mkv
  -o "$OUTPUT_FILE"
)

[ -n "${YT_COOKIES:-}" ] && YTDLP_OPTS+=(--cookies "$YT_COOKIES")

log "Downloading..."
run_cmd yt-dlp "${YTDLP_OPTS[@]}" "$YOUTUBE_URL"

notify_discord "**$TITLE (${YEAR:-unknown})**\n✅ Trailer downloaded (score: $BEST_SCORE)\n$YOUTUBE_URL"
log "Done — trailer saved to: $OUTPUT_FILE"