# StoreBench

**Native stores vs. PostgreSQL — reproducible database experiments using native scripts, Python, and Kotlin.**

Status: initial project proposal, November 2, 2026. Infrastructure, implementations, and benchmarks are planned; no measurements are available yet.

## Project idea

StoreBench investigates when a specialized data store offers a measurable advantage over an appropriately designed PostgreSQL solution, and how well both can be used from native scripts, Python, and Kotlin. Distinct, representative use cases form the basis of the comparison. The project is independent of existing portfolio use cases, both in domain and technology.

The name combines the subject, “data stores,” with a reproducible “benchmark workbench.” The proposed repository name is `storebench`.

The outcome is decision support: **Which store fits a given data volume, load, feature requirement, and implementation language — and when is PostgreSQL sufficient?** There is no assumed overall winner.

## Goals and guiding questions

- Compare the native data models and features of specialized stores with a sensibly modeled and indexed PostgreSQL alternative.
- Provide functionally equivalent implementations for each use case as native scripts and in Python and Kotlin.
- Assess usability, typing, error handling, concurrency, transactions, and development effort with supporting evidence.
- Measure latency, throughput, and resource use while distinguishing effects of the store, driver, protocol, and runtime.
- Run all stores locally in Docker containers with explicit resource limits.
- Build an automated performance test environment with reproducible data, load profiles, and reports.

The initial scope covers single instances. High availability, distributed clusters, cloud costs, and a production platform rollout are outside this first scope.

## Relationship to the Developer Platform

StoreBench is an independent experimental project for the Developer Platform's data store catalog. Existing platform documents mention document, graph, and vector labs as possible extensions; they do not establish that a catalog of specialized stores has already been deployed. The selection below is therefore a proposal, not a statement about currently available platform services.

The first runs will use local Docker Compose directly. Results may later inform platform architecture decisions, resource profiles, and examples. Benchmark runs do not depend on a platform deployment. Context: [product overview](../developer-platform/docs/product/overview.md) and [UC-05: compare technical alternatives](../developer-platform/docs/product/use-cases.md).

Executable slices now include [documents](docs/documents.md), [graph package dependencies](docs/graph.md), and [similar documents with vectors](docs/vector.md). They provide local containers, native scripts or direct API requests, and functional checks. The graph slice compares Apache AGE and Neo4j; the relational PostgreSQL graph baseline remains planned.

## Stores and representative use cases

### Core scope

| Area | Specialized store | PostgreSQL comparison | Representative use case and operations |
| --- | --- | --- | --- |
| Documents | CouchDB | JSONB with suitable GIN/expression indexes; a relational model as a separate experiment | Product catalog with variable attributes: create products, filter nested fields, apply partial updates, and aggregate categories. |
| Graphs | Neo4j | Node/edge tables, indexed joins, and recursive CTEs | Software package dependency analysis: direct and transitive dependencies, change impact, and bounded path searches. |
| Vectors | Qdrant | PostgreSQL with pgvector; exact search and a suitable ANN index | Find similar documents: top-k neighbors, metadata filters, vector updates, and result quality assessment. |

PostgreSQL JSONB supports indexing, and recursive CTEs provide a basis for graph queries. pgvector is a separately identified extension, not part of PostgreSQL core. Technical references: [JSONB](https://www.postgresql.org/docs/current/datatype-json.html), [recursive queries](https://www.postgresql.org/docs/current/queries-with.html), and [pgvector](https://github.com/pgvector/pgvector).

### Planned extensions

| Area | Candidate | PostgreSQL comparison | Representative use case |
| --- | --- | --- | --- |
| Key-value / short-lived state | Redis | Primary-key table, atomic updates, and explicit expiration/cleanup logic | Session lookups, TTL, and atomic counters under concurrent access. Evaluate cache and persistent profiles separately. |
| Full-text search | OpenSearch | `tsvector`, `tsquery`, GIN, and ranking | Search, filter, rank, and rediscover knowledge articles after updates. |
| Analytics | ClickHouse | Relational fact table, partitioning, and indexes as needed | Ingest event data and aggregate by time range, category, and high-cardinality dimensions. |

Extensions follow only after a complete benchmark path exists for the core scope. [PostgreSQL full-text search](https://www.postgresql.org/docs/current/textsearch.html) is the functional baseline for search. Additional stores require their own workload and comparison contract.

## Three implementation paths

“Native” has two meanings here: a specialized store versus PostgreSQL, and a store's own query, scripting, or API interface versus language integration. StoreBench identifies both separately.

| Store | Native scripts / direct interface | Python | Kotlin |
| --- | --- | --- | --- |
| PostgreSQL | SQL through `psql`, including pgvector queries | Psycopg | JDBC with pgJDBC |
| CouchDB | Versioned REST requests, Mango queries, and views | Direct HTTP client | Java HTTP client from Kotlin |
| Neo4j | Cypher files through `cypher-shell` | Neo4j Python driver | Neo4j Java driver from Kotlin |
| Qdrant | Versioned JSON requests to REST, executed by a script | Qdrant Python client | Qdrant Java client from Kotlin |

Qdrant does not need an invented scripting language: direct API requests are its native reference path. Kotlin-specific APIs and Java interoperability will be identified separately. References: [CouchDB HTTP API](https://docs.couchdb.org/en/stable/api/), [Neo4j Java](https://neo4j.com/docs/java-manual/current/query-simple/), and [Qdrant clients](https://api.qdrant.tech/).

Each variant includes setup, data loading, operations, and result validation. The first language baseline uses direct drivers without an ORM or substantial application framework. Coroutine, async, pooling, and framework variants are separate experiments so their effects remain visible.

Use cases employ server-side queries and aggregations where appropriate. A shared interface standardizes inputs and results without reducing every store to a generic CRUD API. Query plans, indexes, and data models remain inspectable.

## Functional comparability

Each workload has a versioned contract specifying inputs, expected results, ordering, limits, consistency, error cases, and permitted deviations. A faster implementation with different behavior is not considered equivalent.

- **Documents:** Match field types, null/missing semantics, filters, projections, and update rules. JSONB and relational PostgreSQL models receive separate results.
- **Graphs:** Match direction, maximum path depth, cycle handling, and duplicate rules. Reachability, shortest paths, and enumeration of all paths are distinct workloads.
- **Vectors:** Use the same precomputed embeddings, distance metric, filters, and top-k values. An exact reference run provides ground truth. ANN variants are evaluated at comparable Recall@k, with an initial target of at least 0.95. Embedding generation is outside the database measurement. The [pgvector reference](https://github.com/pgvector/pgvector) documents the relationship between ANN parameters, recall, and speed.
- **Durability:** Document commit acknowledgment, flush/journal behavior, and visibility after writes. Report unequal guarantees separately.
- **Later search and TTL workloads:** Relevance, index freshness, and logical expiration versus physical deletion add quality dimensions.

Optimized indexes and realistic settings are allowed on both sides. Default configuration and tuning are measured separately; build time, storage, and write costs of optimizations are part of the result.

## Local Docker environment

Docker Compose provides stores, runners, and observability. Each measurement runs exactly one target store and one active client. PostgreSQL and its counterpart are measured in sequence under the same profile. Other stores remain stopped.

These are proposed starting profiles, not measured minimum requirements:

| Component | Standard profile | Larger comparison profile |
| --- | --- | --- |
| Target store | 2 CPU cores, 4 GiB RAM | 4 CPU cores, 8 GiB RAM |
| Python/Kotlin runner or native client | 2 CPU cores, 2 GiB RAM | Unchanged |
| Load generator | 2 CPU cores, 2 GiB RAM | Unchanged; verify capacity first |
| Monitoring, total | Up to 1 CPU core, 2 GiB RAM | Unchanged |

These budgets are separate. A host with roughly 12 logical CPUs and 24 GiB RAM is an initial planning figure for the standard profile; actual suitability is checked before measurements. CPU quotas alone do not guarantee exclusive cores. Where possible, the store and load generator use separate CPU sets.

Further requirements:

- Set CPU and RAM limits explicitly in Compose, for example with `cpus` and `mem_limit`, and check effective limits before each run. Docker documents these options in the [Compose reference](https://docs.docker.com/reference/compose-file/services/).
- Pin images by version and digest, along with Python, JDK, Kotlin, and driver versions; no `latest` tags in published experiments.
- Keep persistent data in comparable Docker volumes on the same disk. On Windows, prefer the Linux filesystem of the Docker/WSL environment; do not mix host bind mounts with Linux volumes.
- Record the operating system, CPU architecture, Docker/Compose versions, VM/WSL limits, filesystem, disk, and network path in the run manifest.
- Specify swap behavior, size store caches and the JVM heap within limits, and record OOM events, throttling, and host pressure.
- Use equivalent network paths. Keep authentication and TLS settings consistent within each comparison.
- Check health and functional readiness; an open port alone is insufficient.

## Performance test environment

### Measurement layers

1. **Native reference and diagnosis:** Store-specific scripts, query plans, and, where available, engine timings reveal the operation actually executed. Measurements reuse connections; a new CLI process per operation would be a separate startup-time measurement. Native tools without sufficient timing resolution provide only batch throughput, not fabricated per-operation percentiles.
2. **Direct client benchmark:** Long-lived Python and Kotlin runners measure identical operations directly through the driver. Timing includes pool wait, serialization, network, store processing, and complete reading of the agreed result. Connection setup and process startup are measured separately.
3. **Application benchmark:** An external load generator calls thin Python and Kotlin HTTP adapters implementing the same contract. It measures the full application path and can generate realistic arrival rates independently of response time.

Layer 3 is planned to use k6 arrival-rate scenarios. [k6 documents this open load model](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/). Layer 2 needs its own protocol-level runner; k6 is not assumed to be a universal direct client for every database protocol.

The layers are analyzed separately. Native CLI times are not automatically a lower bound for driver latency. Python/Kotlin differences are initially reported as differences between complete client stacks. Claims about language effects require protocol, pooling, batch size, and concurrency to match as closely as possible. For Qdrant in particular, REST and gRPC must be identified explicitly; the [Java client uses gRPC](https://qdrant.tech/documentation/quickstart/).

### Data and load profiles

- Deterministic generators with a fixed seed, versioned schema, checksums, and an identical operation sequence for all clients.
- Small smoke datasets, medium datasets, and a larger profile exceeding the available store cache. Initial document counts are 10,000, 100,000, and 1,000,000; payload size and actual bytes are also recorded. Graph size, degree distribution, and vector dimension need their own profiles.
- Uniform and skewed access with hotspots, varied selectivity, and small and large result sets. Avoid merely repeating a single cache hit.
- Read-only, write-only, and a defined mix, initially 80% reads / 20% writes; bulk import is separate from online operation.
- Initial concurrency levels of 1, 8, and 32. Also vary offered operation rates through and beyond saturation; a preliminary check determines appropriate rates per use case.
- Warm operation, restart behavior, and separately defined cold-cache experiments. Restarting a container does not automatically clear the host filesystem cache.

### Procedure for a valid run

1. Check host capacity, configuration, resource limits, and generator capacity; create an immutable run manifest.
2. Restore the target store to a defined initial state, build data and indexes, and run conformance checks.
3. As an initial rule, warm up for at least two minutes, then measure for at least five minutes. Extend this if stability or sample size is insufficient; apply identical rules to all variants.
4. Run at least five independent measurements per configuration. Randomize variant order and reset changed data before repeats.
5. Perform at least one 30-minute endurance test for the first complete use case to expose effects such as memory growth or maintenance work.
6. Archive raw data, histograms, resource time series, query plans, and manifest; generate a report automatically.

The load generator records offered, started, and successfully completed operations, timeouts, errors, and requests that were not started. An overloaded generator must not be mistaken for a store limit. The open load model and wait-time recording should prevent a slowing target from appearing better merely because arrival rates fall. With k6, evaluate [dropped_iterations](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/) in particular.

### Metrics and analysis

| Dimension | Recorded measures |
| --- | --- |
| Response time | p50, p95, p99; startup and connection setup separately; observation count |
| Capacity | Offered and achieved operations/s, saturation point, error and timeout rates |
| Resources | Store and client CPU, RAM, I/O, network, CPU throttling, GC, and pool wait |
| Storage | Data/index size, import time, index build time, and maintenance effort |
| Quality | Result correctness, Recall@k, and, where applicable, search relevance and freshness lag |
| Usability | Integration effort, API quality, typing, diagnosis, and required extra code |

Initial common targets are p95 ≤ 100 ms and an error rate ≤ 0.1%. These are confirmed or adjusted with justification for each workload before measurement. Report the maximum sustainable throughput within the specified targets and quality requirements, rather than only the highest short-term throughput.

For each measurement point, report individual runs, median, and variability. Confidence intervals are based on independent repetitions. Interpret p99 only with sufficient sample size; do not simply average percentiles across runs.

Report performance differences as latency and throughput ratios with a clearly named reference, such as Kotlin/Python on the same store or specialized store/PostgreSQL with the same client. Do not claim a language-caused performance penalty without controlled conditions and a discernible difference from measurement variability.

## Evaluating language integration

Alongside measurements, each use case includes a brief experience report covering the same tasks in every implementation:

- Connect, configure credentials, and manage a pool.
- Map data types, including JSON, timestamps, IDs, and vectors.
- Implement parameterized queries, transactions, or atomic updates.
- Stream results, perform batch operations, and limit concurrency.
- Handle timeouts, cancellation, error codes, retries, and resource cleanup.
- Integrate tests, logging, and diagnostics.

A scale from 1 (substantial extra effort) to 5 (direct and well supported) is a qualitative judgment backed by concrete evidence. Kotlin-native support, Java interoperability, and custom bridges are identified separately. Development time and the amount of handwritten integration code provide context; neither alone determines quality. There is no opaque overall score combining speed and usability.

## Planned project structure

```text
storebench/
├── README.md
├── docs/                   # Methodology, architecture, and decisions
├── infrastructure/         # Compose, resource profiles, store configurations
├── workloads/              # Contracts, generator profiles, expected results
├── implementations/
│   ├── native/             # SQL, CouchDB REST, Cypher, and direct API requests
│   ├── python/             # Direct drivers and thin HTTP adapters
│   └── kotlin/             # Direct drivers and thin HTTP adapters
├── benchmarks/             # Orchestration, direct measurement, k6 scenarios
├── observability/          # Resource collection, Prometheus/Grafana as needed
├── tests/                  # Conformance and measurement instrumentation checks
└── results/                # Manifests, raw data, generated reports
```

This is a target structure. The documents, graph, and vector use cases have local Compose environments and functional scripts; the remaining structure is planned. Eventually, local usage should support a complete sequence of startup, data generation, conformance checks, benchmarking, and reporting. Executable commands will be added alongside the implementation.

## Implementation phases and acceptance criteria

| Phase | Deliverable | Acceptance criterion |
| --- | --- | --- |
| 1 — Measurement foundation and documents | Docker profiles, generator, CouchDB/JSONB, three implementation paths, direct and application measurements | A clean checkout reproduces a complete run with validated results, effective limits, and a report. |
| 2 — Graphs | Neo4j versus PostgreSQL, multiple depths and degree distributions | All three implementation paths return the agreed results; query plans and saturation measurements are available. |
| 3 — Vectors | Qdrant versus pgvector, exact reference and ANN profiles | Recall, filter semantics, and protocols are documented; performance is assessed at comparable quality. |
| 4 — Extensions and transfer | Selected Redis, search, or analytics workloads; recommendations for the Developer Platform | Each recommendation identifies use limits, resource needs, integration effort, and the supporting runs. |

The core scope succeeds when document, graph, and vector use cases each exist as native scripts, in Python, and in Kotlin, have been checked against PostgreSQL, and produce fully reproducible reports. “PostgreSQL is sufficient” is also a valuable result.
