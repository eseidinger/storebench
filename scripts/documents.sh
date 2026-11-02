#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/documents.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/documents.sh {up|seed|run|verify|down} [postgres|couchdb|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  "${compose[@]}" up -d --wait postgres couchdb
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" --profile ui down
  exit
fi
if [[ "$store" != postgres && "$store" != couchdb && "$store" != both ]]; then
  echo 'Store must be postgres, couchdb, or both' >&2
  exit 2
fi
if [[ "$action" == seed ]]; then
  python3 scripts/generate_documents.py
fi
if [[ "$store" == postgres || "$store" == both ]]; then
  script="$action"
  [[ "$action" == run ]] && script=operations
  "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/documents/postgresql/$script.sql"
fi
if [[ "$store" == couchdb || "$store" == both ]]; then
  python3 scripts/documents_couchdb.py "$action"
fi
