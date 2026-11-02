#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/search.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/search.sh {up|seed|run|verify|down} [postgres|opensearch|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  "${compose[@]}" up -d --wait postgres opensearch
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" --profile ui down
  exit
fi
if [[ "$store" != postgres && "$store" != opensearch && "$store" != both ]]; then
  echo 'Store must be postgres, opensearch, or both' >&2
  exit 2
fi
if [[ "$action" == seed ]]; then python3 scripts/generate_search.py; fi
if [[ "$store" == postgres || "$store" == both ]]; then
  script="$action"
  [[ "$action" == run ]] && script=operations
  "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/search/postgresql/$script.sql"
fi
if [[ "$store" == opensearch || "$store" == both ]]; then
  python3 scripts/search_opensearch.py "$action"
fi
