# Document storage workload design

This is a **proposed benchmark contract**, not an implemented or measured workload. The existing [six-product fixture and executable contract](documents.md) remain the functional smoke test. This design extends the same product-catalog domain to compare CouchDB documents with PostgreSQL JSONB at realistic data volumes and request patterns. A relational PostgreSQL model, if added, is a separate variant.

## What makes a run representative

A representative run models an application workflow, including the documents it stores, the queries users actually make, result sizes, writes, contention, and freshness requirements. No single operation mix represents every document application. The three profiles below cover browsing, catalog maintenance, and contested inventory changes. Their percentages are **starting examples**, not claims about typical production traffic. Replace them with measured distributions from a target application when available; publish the source period, sampling method, and anonymization rules with the run. Keep an uncalibrated profile labeled synthetic.

Use a stable, versioned request trace or deterministic generator for each profile. Replay the same logical requests against both stores. Measure the complete client operation, including request encoding, network transfer, response decoding, conflict handling, and any required retries. Report each operation class separately as well as the profile total; a fast point lookup must not hide slow filters or writes.

## Data and query contract

The base document has `id`, `name`, `category`, `price_cents`, `stock`, and an `attributes` object. `id` is a stable unique string, prices and stock are integers, and missing optional attributes are absent rather than JSON null. Use the same logical document and field types in both stores. CouchDB's `_id` equals `id`; `_rev` is storage metadata and is excluded from logical equality. Add a monotonically increasing `version` to generated documents for update and freshness checks. For multi-tenant runs, add `tenant_id` and require every lookup, filter, page, and aggregation to be scoped to one tenant; include tenant scope in the PostgreSQL indexes and CouchDB query definitions.

Generate catalogs from a fixed seed and a versioned schema. Preserve correlations that affect query selectivity: category with available attributes, price and stock with category, and popularity with a subset of IDs. Vary document sizes through realistic optional attributes and bounded text fields, not meaningless random padding alone. Record the actual serialized size distribution (p50/p95/p99), absent/null rates, category frequencies, and query hit counts. Hold these distributions constant across stores. Include missing IDs, filters with zero matches, and documents at the payload-size extremes.

| Parameter | Initial values to test | Why it matters |
| --- | --- | --- |
| Catalog size | 10,000; 100,000; 1,000,000 documents | Exposes memory and index effects; report actual data and index bytes. |
| Payload size | Small, medium, and large classes, e.g. 0.5–2, 2–8, and 8–32 KiB serialized | Changes I/O, transfer, decoding, and rewrite cost. Record the class mix. |
| Optional fields | 0%, 25%, 75% absent for selected attributes | Tests sparse schemas and missing-field semantics. |
| Category distribution | Uniform and skewed (top category 40%) | Changes group sizes and filter frequency. |
| Filter selectivity | Target about 0.01%, 1%, and 20% matches | Separates selective index lookups from broad result scans. Verify actual selectivity after generation. |
| Access skew | Uniform; top 1% of IDs receive 50% of point reads | Represents hot items and changes cache behavior. |
| Result limit | 10, 50, 200; page depth 1, 10, 100 | Changes transfer volume and cost of deep browsing. |
| Update locality | Uniform IDs; top 1% receive 50% of writes | Exposes revision conflicts, locking, and rewrite pressure. |
| Tenant shape | Single tenant; many uneven tenants | Tests scoped indexes and isolation. This changes the schema and is a separately named variant. |

These are controlled axes, not a full Cartesian product. Start with a medium baseline, then vary one axis at a time; add combinations suggested by the target application's traffic. Publish the exact profile file, generator version, seed, schema version, and data checksum. Do not compare runs whose actual selectivity or returned bytes differ materially.

## Operations

All reads return the same logical fields and ordering. An operation succeeds only after the full result has been received and decoded. An update succeeds only after its specified postcondition holds. Use fixed query templates and parameter sets prepared before timing; do not choose easier predicates for one store.

| Code | Logical operation | Contract and required variation |
| --- | --- | --- |
| P1 | Point read | Read one product by `(tenant_id, id)` when tenant mode is active, otherwise by `id`. Separate hits and misses; return the full document. |
| P2 | Attribute filter | Filter by category plus nested attributes such as color and waterproof. Sort by `(category, id)` and return the first `limit` matches with the same projection. Test rare, common, and empty results. |
| P3 | Browse pages | Traverse filtered results using a stable `(category, id)` cursor. Define the cursor from the last returned row, the page limit, and whether a concurrent update may move an item between pages. Record page depth and total returned bytes. |
| P4 | Category summary | Return count and sum of `price_cents` for each category in scope, sorted by category. The sum is over all matching products, not only the current page. |
| P5 | Create | Insert a new unique ID and full document; report duplicate-ID rejection separately. Confirm the document by ID after acknowledgment. |
| P6 | Attribute update | Change one nested attribute while preserving all other logical fields and incrementing `version`. Include single-writer and conflicting-writer cases. |
| P7 | Stock change | Apply a conditional stock delta only if the current version and nonnegative-stock rule allow it. A rejected condition is a distinct outcome, not a successful write. |
| P8 | Delete | Delete one existing ID; subsequent point reads must miss. Measure tombstone or cleanup cost separately where applicable. |

P2 and P3 need an indexed, server-side ordering in both implementations before their timings can be compared as equivalent operations. The current smoke-test CouchDB path sorts the tiny filtered result on the client. If a query/index combination cannot provide equivalent order, either change the common query contract or report that path separately with the full fetch and client sort included. Never truncate before sorting and then claim an equivalent top-N result.

P6 and P7 deliberately expose different write mechanisms. CouchDB reads the document and writes a new revision; PostgreSQL can perform a conditional JSONB update in one statement. Define the same logical precondition and end state, then include all reads, retries, and response checks required by each implementation. Use a bounded retry policy with identical maximum attempts and backoff budget. Report conflict, retry, failed-condition, and exhausted-retry counts. For P7, verify that concurrent accepted deltas are all reflected exactly once and stock never becomes negative. Report the achieved semantics and any difference in guarantees rather than silently accepting lost updates.

The P4 summary and P2/P3 indexes may have maintenance or visibility costs. Build indexes and CouchDB views before the steady-state read run, and report their build time, disk size, and write cost. For a read after write, distinguish (1) write acknowledgment, (2) visibility by ID, and (3) visibility in filtered queries and summaries. A run may require immediate visibility or may allow a stated lag budget; use the same *application requirement* for both stores and record the observed lag distribution. Do not treat a stale summary as a correct current result.

## Scenario profiles

Each row is a reproducible mix of **logical operations**, totaling 100%. The percentages count requested operations, not internal database calls; a CouchDB update with a preliminary read still counts as one P6 or P7. Keep insertion and deletion IDs disjoint from the fixed read set unless the scenario explicitly tests visibility. Execute a workload at controlled offered rates and several concurrency levels; keep the request mix and key distribution fixed as load increases.

| Profile | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | Purpose |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Storefront browsing | 45% | 30% | 15% | 5% | 1% | 3% | 1% | 0% | Mostly reads, selective and broad filters, bounded paging. |
| Catalog maintenance | 20% | 15% | 10% | 5% | 15% | 25% | 5% | 5% | New and changing products, index maintenance, summary freshness. |
| Contended inventory | 30% | 10% | 0% | 5% | 0% | 5% | 50% | 0% | Hot IDs, concurrent conditional writes, retry and conflict behavior. |

The inventory profile is only a valid cross-store performance comparison if both implementations satisfy the same conditional-update postcondition. If that cannot be achieved within the retry budget, report it as a functional limit. Add a bulk-import experiment outside these mixes: load a fixed empty catalog in batches, then separately time index/view construction and the first query. Bulk loading is not interchangeable with steady-state writes.

Keep the measured data state bounded and reproducible. Preallocate IDs for P5/P8, pair creations with later deletions where the profile includes both, alternate P6 values, and balance positive and negative P7 deltas while respecting the stock floor. If a profile intentionally grows the catalog, name it an ingest/growth run and report size and index growth over time. Precompute the request schedule without performing store work, but let reads and writes observe the state changes produced during the run. Reset to the same initial fixture and request seed before every repetition.

## Running and reporting a comparison

1. Generate the fixture and request stream once; validate counts, field types, serialized sizes, query hit counts, and checksums independently of either store.
2. Load each store from the same fixture. Verify a sample of full documents, exact filtered IDs and order, summary totals, update preservation, conditional stock outcomes, and delete results before timing.
3. Run one store and one long-lived client at a time under the same effective CPU, memory, disk, and network limits. Record versions, indexes, client language/driver, durability settings, and query plans. Compare native, Python, and Kotlin paths as separate series.
4. Apply the common [measurement procedure](benchmark-tests.de.md): warm-up, repeated measured runs, varied offered rate and concurrency, reset state after writes, and a separate sustained run. Record offered and completed operations/s, p50/p95/p99 by operation, errors, timeouts, retries, visibility lag, returned bytes, CPU, memory, I/O, and data/index size.
5. Publish the maximum sustainable throughput that meets the predeclared latency, error, correctness, and visibility targets. Include individual repetitions and any unmet contract requirement. Avoid a single aggregate score across the three profiles.

## First implemented preparation step

The versioned [storefront profile](../workloads/documents/profiles/storefront-v1.json) defines 10,000 products, 1,000 logical requests, the operation mix, and parameters for categories, optional fields, document sizes, point reads, filters, and pages. The [generator](../scripts/generate_document_workload.py) produces three files without contacting either database:

```bash
python3 scripts/generate_document_workload.py
```

The default output is `results/documents/storefront-v1/`; `--profile` and `--output` select a different profile or directory. `documents.jsonl` contains the initial documents. `requests.jsonl` contains the ordered requests with inputs and expected results. `manifest.json` records profile, generator, and file checksums plus observed distributions and hit counts. Generated results are not tracked by Git. The existing six-product smoke-test fixture and generator remain separate.

Expected results in `requests.jsonl` assume **serial** execution in sequence order. They are for conformance checks. A later concurrent runner must validate permissible outcomes and invariants for overlapping writes rather than applying these serial expectations unchanged. The current profile has no deletes (P8 = 0), and this generator rejects a nonzero P8 mix.

## Serial conformance run

The [conformance runner](../benchmarks/documents/conformance.py) loads `documents.jsonl` and replays all 1,000 requests in order against PostgreSQL and CouchDB. It checks file hashes before connecting, then compares IDs, full logical documents, or category summaries after every operation. A mismatch stops the run with its sequence number. It uses a separate PostgreSQL table and CouchDB database, both named `benchmark_products`, leaving the six-product functional check intact. `all` resets only these benchmark namespaces.

```bash
python3 scripts/generate_document_workload.py
scripts/documents.sh up
python3 -m venv .venv
.venv/bin/pip install -r implementations/python/documents/requirements.txt
.venv/bin/python benchmarks/documents/conformance.py all --store both
```

Use `--store postgres` or `--store couchdb` to select one store and `--input` for another generated directory. `seed` only loads the fixture, `replay` only executes requests, and `all` does both. Reseed before repeating a replay because P5–P7 change state. CouchDB filters use server-side ordering with an explicitly named category/ID index; rare attribute predicates can still examine many documents. Index selectivity and alternative indexes belong to later performance work. This runner checks **correctness**; the separate diagnostic direct-client measurement is described next.

## First serial direct-client measurement

The [Python measurement runner](../benchmarks/documents/measure.py) runs **one store at a time**. It reloads the fixture, warms up with 100 read requests by default, then replays the full mixed trace serially. Start a separate run for each store while the other store is stopped:

```bash
docker compose -f infrastructure/documents.compose.yaml up -d --wait postgres
.venv/bin/python benchmarks/documents/measure.py --store postgres
docker compose -f infrastructure/documents.compose.yaml down
docker compose -f infrastructure/documents.compose.yaml up -d --wait couchdb
.venv/bin/python benchmarks/documents/measure.py --store couchdb
docker compose -f infrastructure/documents.compose.yaml down
```

The runner writes `operations.jsonl`, `summary.json`, and `manifest.json` under `results/documents/runs/<run_id>/`. Use `--input` for a different generated fixture, `--output` for a new output directory, and `--warmup-requests` to set the number of read warmup operations. A monotonic clock measures each direct client call through full response decoding as `elapsed_ns`. Reference validation happens afterward and appears as `validation_ns`. For writes it includes an extra point read, which can affect the state seen by the next request. Result sizes are **logical serialized bytes**, not measured network bytes. The summary reports count, errors, and p50/p95/p99 per operation and query class; high percentiles are weak evidence for groups with few observations.

This is a **diagnostic serial direct-client measurement**. It does not establish sustainable throughput or a store ranking: offered rate, concurrency, independent repetitions, resource sampling, and effective container limits are not yet controlled or collected by this runner. Rare predicates can still scan many CouchDB documents with the current index. The full [benchmark procedure](benchmark-tests.de.md) remains the next stage.
