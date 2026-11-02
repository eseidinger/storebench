# Vectors: similar documents

This executable StoreBench use case compares [PostgreSQL with pgvector](https://github.com/pgvector/pgvector) and [Qdrant](https://qdrant.tech/documentation/quickstart/) on a fixed set of six precomputed three-dimensional vectors. It checks functional equivalence of exact cosine nearest-neighbor queries, metadata filtering, and a vector update. It is not a performance benchmark: six vectors cannot establish a meaningful ANN speed/recall tradeoff. Larger datasets, ANN indexes, and Python/Kotlin direct clients remain future work.

## Run locally

Requirements: Docker with Compose and Python 3. The Python scripts use only the standard library. Compose uses `pgvector/pgvector:0.8.7-pg17-trixie` and `qdrant/qdrant:v1.19.2`, each limited to two CPUs and 4 GiB RAM. PostgreSQL is bound to localhost port 5434 and Qdrant REST to localhost port 6334. PostgreSQL credentials (`storebench` / `storebench_local`) are for local development. Qdrant has no authentication in this local profile; do not expose it externally.

From the repository root:

```bash
scripts/vector.sh up
scripts/vector.sh seed both
scripts/vector.sh run both
scripts/vector.sh verify both
scripts/vector.sh down
```

`seed` resets the table and Qdrant collection, then loads the same canonical data into each. It also regenerates the native SQL fixture and Qdrant point payload. Rerun `seed` before `run`, because `run` changes document 3's vector. The `seed`, `run`, and `verify` actions accept `postgres`, `qdrant`, or `both`. `down` preserves local volumes; `docker compose -f infrastructure/vector.compose.yaml down -v` removes them deliberately.

## Workload contract

The canonical [documents.json](../workloads/vector/documents.json) defines numeric IDs, titles, categories, three-dimensional nonzero vectors, a query vector, and an update vector. Both stores use cosine distance/similarity. pgvector's `<=>` returns **distance** (lower is closer); Qdrant returns a **similarity score** (higher is closer). The comparison uses ordered IDs, not raw scores. No embedding generation is part of the measured database path.

| Step | Operation | Expected ordered IDs |
| --- | --- | --- |
| 1 | Exact top-3 for `[1, 0, 0]` | `1, 2, 6` |
| 2 | Exact top-2 with `category = guide` | `1, 6` |
| 3 | Replace document 3's vector with `[0.95, 0.05, 0]` | Metadata stays unchanged |
| 4 | Exact top-3 after the update | `1, 3, 2` |

PostgreSQL has no ANN index in this slice, so its nearest-neighbor query is exact. Qdrant queries explicitly set `params.exact` to `true`. Qdrant upserts and vector updates use `wait=true`; PostgreSQL statements complete synchronously. The verifier checks the final top-k ordering, filtered result, metadata preservation, and document count in PostgreSQL. Qdrant uses direct REST calls and checks the same search outcomes and metadata. Repeating `run` without reseeding is valid but no longer demonstrates the before/after transition.

## Files and limits

- `infrastructure/vector.compose.yaml`: local services, resource limits, health checks, ports, and volumes.
- `workloads/vector/documents.json`: canonical vectors, metadata, query, and update.
- `scripts/generate_vector.py`: generates PostgreSQL seed SQL and Qdrant point JSON.
- `implementations/native/vector/postgresql/`: native SQL seed, operations, and verification.
- `implementations/native/vector/qdrant/points.json`: versioned direct REST upsert payload.
- `scripts/vector_qdrant.py`: direct Qdrant REST operations and verification.
- `scripts/vector.sh`: workflow wrapper.

The Compose profile starts both stores for functional checking. A future benchmark should measure one target at a time, use larger and varied vector datasets, run an exact ground-truth search, compare ANN results at matched Recall@k, and report index build time, storage, resource limits, and independent measurements. The [Qdrant query API](https://api.qdrant.tech/api-reference/search/query-points/) documents the exact-search and filter parameters; the [pgvector reference](https://github.com/pgvector/pgvector) documents cosine operators and HNSW indexing.

Interactive access to both stores is listed in [local store access](access.md).
