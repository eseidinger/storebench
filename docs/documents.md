# Documents: product catalog

This is the first executable StoreBench use case. It compares MongoDB documents with PostgreSQL JSONB on a small, fixed product catalog. It checks functional behavior; it is **not** a performance benchmark. The Python and Kotlin clients, larger generated datasets, and measurement runner described in the project plan are future phases.

## Requirements

Docker with Compose, Python 3, and enough free resources for two containers. The example uses PostgreSQL 17.6 and MongoDB 8.0.15. Both expose ports on localhost only: PostgreSQL on 5433 and MongoDB on 27018. Credentials are fixed for local development (`storebench` / `storebench_local`); do not expose these services externally.

From the repository root:

```bash
scripts/documents.sh up
scripts/documents.sh seed both
scripts/documents.sh run both
scripts/documents.sh verify both
scripts/documents.sh down
```

`seed` recreates the product table/collection and its indexes, so rerun it before repeating `run`. `down` preserves the Docker volumes. To remove local data deliberately, use `docker compose -f infrastructure/documents.compose.yaml down -v`.

You can select just `postgres` or `mongodb` for `seed`, `run`, and `verify`. The source dataset is [products.json](../workloads/documents/products.json); `seed` regenerates SQL and JavaScript fixtures from it with Python's standard library. Generated files are kept in the repository so the native scripts are also directly inspectable.

## Workload contract

All products have a stable string `id`, name, category, integer `price_cents`, integer stock count, and an `attributes` object with variable fields. Prices use integer cents to avoid floating-point differences. Missing fields are absent rather than JSON null. The `id` values are unique. This initial catalog has six products and no concurrent writes.

The operations run in this order:

| Step | Operation | Expected result |
| --- | --- | --- |
| 1 | Read `p001` by ID | Trail Jacket, price 12900 cents |
| 2 | Find blue waterproof products, sorted by ID | `p001`, `p003`, `p005` |
| 3 | Set `p002.attributes.waterproof` to true | Exactly one product changes; other fields remain |
| 4 | Group by category and sum prices | apparel: 2 / 22800; footwear: 2 / 24800; gear: 2 / 19800 |

The total price is 67400 cents. `verify` checks counts, the nested filter, the changed field, and that total, and exits with an error if a check fails. The SQL uses `jsonb_set`; MongoDB uses `$set` on the nested path. Both use an index on category and an index for attributes; MongoDB also has a unique index on `id`, matching the PostgreSQL primary key. They are representative initial indexes, not tuned benchmark results.

The scripts do not claim matched durability or transaction semantics. PostgreSQL seeds in a transaction; MongoDB seeds the collection without a multi-document transaction. The update operation itself is atomic for one product in each store. The output formats differ by database CLI; the shared contract above defines the result semantics.

## Files

- `infrastructure/documents.compose.yaml`: local stores, resource limits, health checks, and volumes.
- `workloads/documents/products.json`: canonical fixture.
- `scripts/generate_documents.py`: generates both native seed scripts.
- `implementations/native/documents/{postgresql,mongodb}/`: seed, operations, and verification scripts.
- `scripts/documents.sh`: command wrapper.

The Compose profile starts both stores for functional comparison. Later performance runs should start and measure one target at a time, record effective resource limits and versions, and use larger datasets and independent repetitions as specified in the main README.
