#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f infrastructure/graph.compose.yaml)
action="${1:-}"
store="${2:-}"
if [[ ! "$action" =~ ^(up|seed|run|verify|down)$ ]]; then
  echo 'Usage: scripts/graph.sh {up|seed|run|verify|down} [age|neo4j|hugegraph|both]' >&2
  exit 2
fi
if [[ "$action" == up ]]; then
  case "$store" in
    ''|both) services=(age neo4j hugegraph) ;;
    age|neo4j|hugegraph) services=("$store") ;;
    *) echo 'Store must be age, neo4j, hugegraph, or both' >&2; exit 2 ;;
  esac
  "${compose[@]}" up -d --wait "${services[@]}"
  exit
fi
if [[ "$action" == down ]]; then
  "${compose[@]}" --profile ui down
  exit
fi
if [[ "$store" != age && "$store" != neo4j && "$store" != hugegraph && "$store" != both ]]; then
  echo 'Store must be age, neo4j, hugegraph, or both' >&2
  exit 2
fi
if [[ "$action" == seed && "$store" != hugegraph ]]; then python3 scripts/generate_graph.py; fi
if [[ "$action" == verify ]]; then python3 scripts/verify_graph.py "$store"; exit; fi
script="$action"
[[ "$action" == run ]] && script=operations
if [[ "$store" == age || "$store" == both ]]; then
  "${compose[@]}" exec -T age psql -X -v ON_ERROR_STOP=1 -U storebench -d storebench < "implementations/native/graph/age/$script.sql"
fi
if [[ "$store" == neo4j || "$store" == both ]]; then
  "${compose[@]}" exec -T neo4j cypher-shell --non-interactive -u neo4j -p storebench_local < "implementations/native/graph/neo4j/$script.cypher"
fi
if [[ "$store" == hugegraph || "$store" == both ]]; then
  python3 implementations/native/graph/hugegraph/main.py "$action"
fi
