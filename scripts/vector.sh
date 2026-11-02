#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/vector.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/vector.sh {up|seed|run|verify|down} [postgres|qdrant|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  "${compose[@]}" up -d --wait postgres qdrant
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" down
  exit
fi
if [[ "$store" != postgres && "$store" != qdrant && "$store" != both ]]; then
  echo 'Store must be postgres, qdrant, or both' >&2
  exit 2
fi
if [[ "$action" == seed ]]; then python3 scripts/generate_vector.py; fi
if [[ "$store" == postgres || "$store" == both ]]; then
  script="$action"
  [[ "$action" == run ]] && script=operations
  "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/vector/postgresql/$script.sql"
fi
if [[ "$store" == qdrant || "$store" == both ]]; then
  python3 scripts/vector_qdrant.py "$action"
fi
