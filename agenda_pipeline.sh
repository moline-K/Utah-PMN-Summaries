#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/media/kendon/apps/agenda_downloader"
LOG_DIR="$REPO_DIR/app/logs"
mkdir -p "$LOG_DIR"

# rotate aggressively: delete logs older than 30 days or beyond the newest 60 files
MAX_AGE_DAYS=30
MAX_FILES=60

find "$LOG_DIR" -name 'pipeline_*.log' -type f -mtime +"$MAX_AGE_DAYS" -delete 2>/dev/null || true
mapfile -t logs < <(ls -1t "$LOG_DIR"/pipeline_*.log 2>/dev/null || true)
if ((${#logs[@]} > MAX_FILES)); then
  for old in "${logs[@]:MAX_FILES}"; do rm -f "$old"; done
fi

ts="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/pipeline_${ts}.log"

{
  echo "[$(date)] Starting agenda_downloader"
  docker compose -f "$REPO_DIR/docker-compose.yml" run --rm agenda_downloader

  echo "[$(date)] Starting agenda_summarizer"
  docker compose -f "$REPO_DIR/docker-compose.yml" run --rm agenda_summarizer

  echo "[$(date)] Pipeline finished"
} >> "$LOG_FILE" 2>&1
