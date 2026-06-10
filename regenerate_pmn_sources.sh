#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELECTION_PATH="$(realpath "${1:-$SCRIPT_DIR/pmn_selection.yaml}")"
OUTPUT_PATH="$(realpath -m "${2:-$SCRIPT_DIR/pmn_sources.yaml}")"
CATALOG_PATH="$(realpath "${3:-$SCRIPT_DIR/data/previous work/all_bodies.json}")"
GENERATOR_IMAGE="${PMN_GENERATOR_IMAGE:-ghcr.io/moline-k/utah-pmn-summaries:latest}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

run_local() {
  python3 "$SCRIPT_DIR/app/generate_pmn_sources.py" \
    --selection "$SELECTION_PATH" \
    --catalog "$CATALOG_PATH" \
    --out "$OUTPUT_PATH"
}

paths_within_repo() {
  case "$SELECTION_PATH" in "$SCRIPT_DIR"/*) ;; *) return 1;; esac
  case "$OUTPUT_PATH" in "$SCRIPT_DIR"/*) ;; *) return 1;; esac
  case "$CATALOG_PATH" in "$SCRIPT_DIR"/*) ;; *) return 1;; esac
}

run_compose() {
  local selection_rel output_rel catalog_rel
  selection_rel="${SELECTION_PATH#$SCRIPT_DIR/}"
  output_rel="${OUTPUT_PATH#$SCRIPT_DIR/}"
  catalog_rel="${CATALOG_PATH#$SCRIPT_DIR/}"
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" run --rm pmn_generator \
    --selection "/workspace/$selection_rel" \
    --catalog "/workspace/$catalog_rel" \
    --out "/workspace/$output_rel"
}

run_image() {
  local selection_dir output_dir catalog_dir
  selection_dir="$(dirname "$SELECTION_PATH")"
  output_dir="$(dirname "$OUTPUT_PATH")"
  catalog_dir="$(dirname "$CATALOG_PATH")"

  docker run --rm \
    -v "$selection_dir":/mnt/selection:ro \
    -v "$output_dir":/mnt/output \
    -v "$catalog_dir":/mnt/catalog:ro \
    "$GENERATOR_IMAGE" \
    python /app/generate_pmn_sources.py \
      --selection "/mnt/selection/$(basename "$SELECTION_PATH")" \
      --catalog "/mnt/catalog/$(basename "$CATALOG_PATH")" \
      --out "/mnt/output/$(basename "$OUTPUT_PATH")"
}

if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" >/dev/null 2>&1; then
  echo "Using local Python generator"
  run_local
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && paths_within_repo; then
  echo "Using docker compose generator service"
  run_compose
elif command -v docker >/dev/null 2>&1; then
  echo "Using Docker image generator: $GENERATOR_IMAGE"
  run_image
else
  echo "No usable generator runtime found. Install python3+pyyaml, or docker compose, or docker." >&2
  exit 1
fi
