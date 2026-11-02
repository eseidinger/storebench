# Vectors: similar documents

This executable StoreBench use case compares [PostgreSQL with pgvector](https://github.com/pgvector/pgvector) and [Qdrant](https://qdrant.tech/documentation/quickstart/) on a fixed set of six precomputed three-dimensional vectors. It checks functional equivalence of exact cosine nearest-neighbor queries, metadata filtering, and a vector update. It is not a performance benchmark: six vectors cannot establish a meaningful ANN speed/recall tradeoff. Larger datasets, ANN indexes, and a measurement runner remain future work. Direct Python and Kotlin clients implement this functional contract.

## Run locally

Requirements: Docker with Compose, Python 3.10 or newer, and Java 17 or newer for Kotlin. The native Python scripts use only the standard library. Compose uses `pgvector/pgvector:0.8.7-pg17-trixie` and `qdrant/qdrant:v1.19.2`, each limited to two CPUs and 4 GiB RAM. PostgreSQL is bound to localhost port 5434 and Qdrant REST to localhost port 6334, and Qdrant gRPC to localhost port 6335. PostgreSQL credentials (`storebench` / `storebench_local`) are for local development. Qdrant has no authentication in this local profile; do not expose it externally.

From the repository root:

```bash
scripts/vector.sh up
scripts/vector.sh seed both
scripts/vector.sh run both
scripts/vector.sh verify both
scripts/vector.sh down
```

`seed` resets the table and Qdrant collection, then loads the same canonical data into each. It also regenerates the native SQL fixture and Qdrant point payload. Rerun `seed` before `run`, because `run` changes document 3's vector. The `seed`, `run`, and `verify` actions accept `postgres`, `qdrant`, or `both`. `down` preserves local volumes; `docker compose -f infrastructure/vector.compose.yaml down -v` removes them deliberately.

### Python client

Start both stores with `scripts/vector.sh up`, then run from the repository root:

```bash
python3 -m venv implementations/python/vector/.venv
implementations/python/vector/.venv/bin/pip install -r implementations/python/vector/requirements.txt
implementations/python/vector/.venv/bin/python implementations/python/vector/main.py seed both
implementations/python/vector/.venv/bin/python implementations/python/vector/main.py run both
implementations/python/vector/.venv/bin/python implementations/python/vector/main.py verify both
```

The Python client uses Psycopg and the Qdrant Python client over REST. It reads the canonical fixture directly. `seed` recreates the selected table or collection. `STOREBENCH_VECTOR_PG_HOST`, `STOREBENCH_VECTOR_PG_PORT`, and `STOREBENCH_QDRANT_URL` override its local connection defaults.

### Kotlin client

With both stores running, execute from the repository root:

```bash
cd implementations/kotlin/vector
./gradlew installDist
build/install/storebench-vector-kotlin/bin/storebench-vector-kotlin seed both
build/install/storebench-vector-kotlin/bin/storebench-vector-kotlin run both
build/install/storebench-vector-kotlin/bin/storebench-vector-kotlin verify both
```

The Kotlin client uses PostgreSQL JDBC and the Qdrant Java client over gRPC. Run it from `implementations/kotlin/vector` so it can find the canonical fixture. `STOREBENCH_VECTOR_PG_HOST`, `STOREBENCH_VECTOR_PG_PORT`, `STOREBENCH_QDRANT_HOST`, and `STOREBENCH_QDRANT_GRPC_PORT` override its local connection defaults. The gRPC port is bound only to localhost and uses plaintext in this development profile.

Both clients accept `postgres`, `qdrant`, or `both`. Run `seed`, then `run`, then `verify`; either client's seed resets the shared stores. The two Qdrant clients use different network protocols, so their timings should be reported as separate client stacks in a future benchmark.

## Workload contract

The canonical [documents.json](../workloads/vector/documents.json) defines numeric IDs, titles, categories, three-dimensional nonzero vectors, a query vector, and an update vector. Both stores use cosine distance/similarity. pgvector's `<=>` returns **distance** (lower is closer); Qdrant returns a **similarity score** (higher is closer). The comparison uses ordered IDs, not raw scores. No embedding generation is part of the measured database path.

| Step | Operation | Expected ordered IDs |
| --- | --- | --- |
| 1 | Exact top-3 for `[1, 0, 0]` | `1, 2, 6` |
| 2 | Exact top-2 with `category = guide` | `1, 6` |
| 3 | Replace document 3's vector with `[0.95, 0.05, 0]` | Metadata stays unchanged |
| 4 | Exact top-3 after the update | `1, 3, 2` |

PostgreSQL has no ANN index in this slice, so its nearest-neighbor query is exact. Qdrant queries explicitly set `params.exact` to `true`. Qdrant upserts and vector updates use `wait=true`; PostgreSQL statements complete synchronously. The native and direct-client verifiers check the final top-k ordering, filtered result, metadata preservation, and document count in both stores. Repeating `run` without reseeding is valid but no longer demonstrates the before/after transition.

## Files and limits

- `infrastructure/vector.compose.yaml`: local services, resource limits, health checks, ports, and volumes.
- `workloads/vector/documents.json`: canonical vectors, metadata, query, and update.
- `scripts/generate_vector.py`: generates PostgreSQL seed SQL and Qdrant point JSON.
- `implementations/native/vector/postgresql/`: native SQL seed, operations, and verification.
- `implementations/native/vector/qdrant/points.json`: versioned direct REST upsert payload.
- `scripts/vector_qdrant.py`: direct Qdrant REST operations and verification.
- `scripts/vector.sh`: native workflow wrapper.
- `implementations/python/vector/` and `implementations/kotlin/vector/`: direct clients with seed, run, and verify commands.

The Compose profile starts both stores for functional checking. A future benchmark should measure one target at a time, use larger and varied vector datasets, run an exact ground-truth search, compare ANN results at matched Recall@k, and report index build time, storage, resource limits, and independent measurements. The [Qdrant query API](https://api.qdrant.tech/api-reference/search/query-points/) documents the exact-search and filter parameters; the [pgvector reference](https://github.com/pgvector/pgvector) documents cosine operators and HNSW indexing.

Interactive access to both stores is listed in [local store access](access.md).
