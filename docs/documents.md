# Documents: product catalog

This executable StoreBench use case compares [Apache CouchDB](https://docs.couchdb.org/en/stable/) documents with PostgreSQL JSONB on a small, fixed product catalog. It checks functional behavior; it is **not** a performance benchmark. The Python and Kotlin clients, larger generated datasets, and measurement runner described in the project plan are future phases. The local CouchDB workflow uses Python's standard library to send direct, inspectable HTTP requests; it is a native API path rather than a separate language-client comparison.

## Requirements

Docker with Compose, Python 3, and enough free resources for two containers. The example uses PostgreSQL 17.6 and CouchDB 3.5.1. Both expose ports on localhost only: PostgreSQL on 5433 and CouchDB HTTP on 5985. Credentials are fixed for local development (`storebench` / `storebench_local`); do not expose these services externally. CouchDB is configured as a single node during `seed` using its [setup API](https://docs.couchdb.org/en/stable/setup/single-node.html).

From the repository root:

```bash
scripts/documents.sh up
scripts/documents.sh seed both
scripts/documents.sh run both
scripts/documents.sh verify both
scripts/documents.sh down
```

`seed` recreates the product table/database and its indexes, so rerun it before repeating `run`. `down` preserves Docker volumes. To remove local data deliberately, use `docker compose -f infrastructure/documents.compose.yaml down -v`.

You can select just `postgres` or `couchdb` for `seed`, `run`, and `verify`. The source dataset is [products.json](../workloads/documents/products.json); `seed` regenerates SQL and CouchDB bulk-insert JSON from it with Python's standard library. Generated files are kept in the repository so the native data requests are directly inspectable.

## Workload contract

All products have a stable string `id`, name, category, integer `price_cents`, integer stock count, and an `attributes` object with variable fields. Prices use integer cents to avoid floating-point differences. Missing fields are absent rather than JSON null. The `id` values are unique. CouchDB uses the same value for `_id`; its `_rev` is an additional storage field. This initial catalog has six products and no concurrent writes.

The operations run in this order:

| Step | Operation | Expected result |
| --- | --- | --- |
| 1 | Read `p001` by ID | Trail Jacket, price 12900 cents |
| 2 | Find blue waterproof products, sorted by ID | `p001`, `p003`, `p005` |
| 3 | Set `p002.attributes.waterproof` to true | Exactly one product changes; other fields remain |
| 4 | Group by category and sum prices | apparel: 2 / 22800; footwear: 2 / 24800; gear: 2 / 19800 |

The total price is 67400 cents. `verify` checks the count, lookup, nested-filter IDs, updated attributes, and category totals, and exits with an error on a mismatch.

PostgreSQL uses `jsonb_set` for the nested update, a GIN index on `attributes`, and an expression index on category. CouchDB uses a [Mango `_find` query](https://docs.couchdb.org/en/stable/api/database/find.html) with an attributes index. The small result is sorted by ID in the request script; this client-side sort should be replaced with an indexed server-side sort before performance comparisons. Category aggregation uses a [map/reduce view](https://docs.couchdb.org/en/stable/ddocs/views/intro.html) with `_stats` and `group=true`; the view may incur index build work on first access.

CouchDB does not provide a single-field server-side patch for this document. The script reads `p002`, changes the nested value, and writes the full document with its current `_rev`. A concurrent update would require conflict handling and retries. PostgreSQL seeds inside one transaction; CouchDB's bulk insert returns per-document results, all of which are checked. These different update and transaction semantics must be accounted for in any later benchmark. The current script does not claim matched durability guarantees.

## Files

- `infrastructure/documents.compose.yaml`: local stores, resource limits, health checks, and volumes.
- `workloads/documents/products.json`: canonical fixture.
- `scripts/generate_documents.py`: generates SQL and CouchDB bulk-insert JSON.
- `implementations/native/documents/postgresql/`: SQL seed, operations, and verification.
- `implementations/native/documents/couchdb/`: bulk-insert JSON, Mango index, and category view definitions.
- `scripts/documents_couchdb.py`: direct CouchDB REST operations and verification.
- `scripts/documents.sh`: command wrapper.

The Compose profile starts both stores for functional comparison. Later performance runs should start and measure one target at a time, record effective resource limits and versions, and use larger datasets and independent repetitions as specified in the main README.

Interactive access to both stores is listed in [local store access](access.md).
