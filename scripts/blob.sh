#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/blob.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/blob.sh {up|seed|run|verify|down} [postgres|rustfs|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  "${compose[@]}" up -d --wait postgres rustfs
  python3 scripts/blob_rustfs.py wait
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" --profile ui down
  exit
fi
if [[ "$store" != postgres && "$store" != rustfs && "$store" != both ]]; then
  echo 'Store must be postgres, rustfs, or both' >&2
  exit 2
fi
if [[ "$action" == seed ]]; then python3 scripts/blob_data.py; fi
if [[ "$store" == postgres || "$store" == both ]]; then
  script="$action"
  [[ "$action" == run ]] && script=operations
  "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/blob/postgresql/$script.sql"
fi
if [[ "$store" == rustfs || "$store" == both ]]; then
  python3 scripts/blob_rustfs.py "$action"
fi
