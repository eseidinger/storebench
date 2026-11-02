#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/graph.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/graph.sh {up|seed|run|verify|down} [age|neo4j|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  "${compose[@]}" up -d --wait age neo4j
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" down
  exit
fi
if [[ "$store" != age && "$store" != neo4j && "$store" != both ]]; then
  echo 'Store must be age, neo4j, or both' >&2
  exit 2
fi
if [[ "$action" == seed ]]; then python3 scripts/generate_graph.py; fi
if [[ "$action" == verify ]]; then python3 scripts/verify_graph.py "$store"; exit; fi
script="$action"
[[ "$action" == run ]] && script=operations
if [[ "$store" == age || "$store" == both ]]; then
  "${compose[@]}" exec -T age psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/graph/age/$script.sql"
fi
if [[ "$store" == neo4j || "$store" == both ]]; then
  "${compose[@]}" exec -T neo4j cypher-shell --non-interactive -u neo4j -p storebench_local < "implementations/native/graph/neo4j/$script.cypher"
fi
