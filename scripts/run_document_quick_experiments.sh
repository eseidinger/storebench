#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fixture="results/documents/storefront-quick-v1"
.venv/bin/python scripts/generate_document_workload.py \
  --profile workloads/documents/profiles/storefront-quick-v1.json \
  --output "$fixture"

for profile in read-only-quick-v1 catalog-maintenance-write-quick-v1 contested-stock-write-quick-v1; do
  .venv/bin/python benchmarks/documents/experiment.py \
    --plan "workloads/documents/profiles/$profile.json" \
    --input "$fixture"
done
