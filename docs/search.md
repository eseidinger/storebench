# Full-text search: knowledge articles

This executable StoreBench use case compares [PostgreSQL full-text search](https://www.postgresql.org/docs/current/textsearch.html) with [OpenSearch](https://docs.opensearch.org/latest/). PostgreSQL uses its built-in `tsvector` and `tsquery` features; **no extension is needed**. Both stores index the same six English-language knowledge articles and run a two-term search, category filter, and update visibility check. This small fixture establishes functional behavior, not performance or broad relevance equivalence. Python/Kotlin direct clients and the measurement runner remain future work.

## Run locally

Requirements: Docker with Compose, Python 3, and sufficient memory for both services. OpenSearch may also require a host `vm.max_map_count` of at least 262144; see its [Docker installation guide](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/). The Compose file uses PostgreSQL 17.6 and OpenSearch 3.9.0, with two CPUs and 4 GiB RAM per service. OpenSearch's JVM heap is 1 GiB. PostgreSQL is bound to localhost port 5435 and OpenSearch HTTP to localhost port 9201. OpenSearch's security plugin is disabled for this localhost-only development profile; do not expose the port externally.

From the repository root:

```bash
scripts/search.sh up
scripts/search.sh seed both
scripts/search.sh run both
scripts/search.sh verify both
scripts/search.sh down
```

`seed` recreates the PostgreSQL table and OpenSearch index from [articles.json](../workloads/search/articles.json), then waits for OpenSearch's bulk write to become searchable. Rerun `seed` before repeating the before/after workload. The `seed`, `run`, and `verify` actions accept `postgres`, `opensearch`, or `both`. `down` keeps the local volumes; `docker compose -f infrastructure/search.compose.yaml down -v` removes them deliberately.

## Workload contract

Each article has a numeric ID, title, body, and category. Both stores analyze the `title` and `body` as English text and keep `category` as an exact filter field. The query is **`vector indexing` with both terms required**. Title matches receive more weight than body matches. Result IDs are sorted by score descending, then ID ascending as a tie breaker; score values themselves are store-specific and must not be compared directly.

| Step | Operation | Expected ordered IDs |
| --- | --- | --- |
| 1 | Search `vector indexing` | `6` |
| 2 | Search the same query with `category = guide` | No results |
| 3 | Change article 5's body to `Vector indexing helps find similar documents.` | Title and category stay unchanged |
| 4 | Repeat the search | `6, 5` |
| 5 | Repeat with `category = guide` | `5` |

PostgreSQL builds a generated weighted `tsvector`, indexes it with GIN, and uses `plainto_tsquery('english', ...)` plus `ts_rank`. OpenSearch defines English analyzers for title/body, a keyword category field, and a two-term `multi_match` query with a category `term` filter. An OpenSearch partial update uses `refresh=wait_for`, so the subsequent query observes it; this wait is part of the operation path and must be measured separately in a future benchmark. PostgreSQL's update completes synchronously. The verifier checks document count, final ranked IDs, filtered IDs, and unchanged title in each store.

The fixture has deliberately unambiguous ranked results. It does not establish identical stemming, tokenization, phrase behavior, language handling, or relevance scores beyond this contract. Before benchmarking, add varied queries, relevance judgments, update visibility targets, and realistic document volumes. Index build time, storage, refresh costs, and query plans belong in the result. See the [OpenSearch bulk API](https://docs.opensearch.org/latest/api-reference/document-apis/bulk/) for refresh behavior and the [PostgreSQL text search documentation](https://www.postgresql.org/docs/current/textsearch.html) for its built-in facilities.

## Files

- `infrastructure/search.compose.yaml`: local services, limits, health checks, ports, and volumes.
- `workloads/search/articles.json`: canonical fixture, query, and update.
- `scripts/generate_search.py`: generates PostgreSQL seed SQL and OpenSearch bulk NDJSON.
- `implementations/native/search/postgresql/`: SQL seed, operations, and verification.
- `implementations/native/search/opensearch/`: index mapping and bulk payload.
- `scripts/search_opensearch.py`: direct OpenSearch REST operations and verification.
- `scripts/search.sh`: workflow wrapper.

Interactive access to both stores is listed in [local store access](access.md).
