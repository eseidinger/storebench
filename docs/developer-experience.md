# Developer experience: PostgreSQL and specialized stores

This qualitative comparison examines the direct Python and Kotlin clients for the five StoreBench use cases. It considers data models, queries, client APIs, writes, and integration work visible in the code. The findings apply to these small functional examples, not to every capability of the stores. Latency, throughput, and resource use are outside this document.

Each client provides `seed`, `run`, and `verify` for its stores. The graph comparison has an important limit: its PostgreSQL side uses **Apache AGE**, which is itself a graph extension. A baseline using ordinary node and edge tables with recursive CTEs has not been implemented.

## Documents: PostgreSQL JSONB and CouchDB

Code: [Python](../implementations/python/documents/main.py), [Kotlin](../implementations/kotlin/documents/src/main/kotlin/Documents.kt).

| Language | PostgreSQL JSONB | CouchDB |
| --- | --- | --- |
| Python | **Advantage:** Psycopg binds JSONB directly; nested filters, targeted updates, and grouping stay in SQL. **Drawback:** Developers need to know JSON operators, casts, and suitable index expressions. | **Advantage:** Documents are natural Python dictionaries. **Drawback:** This client handles authentication and HTTP errors itself. Filtering and totals also require a Mango index and a view. |
| Kotlin | **Advantage:** JDBC and the seed transaction are explicit and familiar. **Drawback:** The client writes JSON as a string, reads it back through Jackson, and maps query results manually. | **Advantage:** Jackson's object model fits nested documents. **Drawback:** Java's HTTP client requires substantial request, JSON, and status-handling code; the index and view add setup steps. |

Both CouchDB clients fetch the document before updating it, then write the whole document with its current `_rev`. This example has no conflict handling for concurrent updates. PostgreSQL uses `jsonb_set` for the same change.

## Graphs: PostgreSQL with Apache AGE and Neo4j

Code: [Python](../implementations/python/graph/main.py), [Kotlin](../implementations/kotlin/graph/src/main/kotlin/Graph.kt). The relational PostgreSQL graph baseline described in the [graph use case](graph.md) remains open.

| Language | PostgreSQL/AGE | Neo4j |
| --- | --- | --- |
| Python | **Advantage:** The existing Psycopg connection can be reused. **Drawback:** Every connection needs `LOAD 'age'` and the AGE search path. Cypher is embedded in SQL, and `agtype` results are read as text. | **Advantage:** Cypher runs directly through the driver, with bound parameters when creating edges. **Drawback:** It needs another driver and session lifecycle; the current client still normalizes results to strings. |
| Kotlin | **Advantage:** Access stays within JDBC. **Drawback:** SQL around Cypher, dollar quoting, and `agtype` conversion reduce readability; the seed validates package names before embedding them in Cypher. | **Advantage:** The Java driver offers direct Cypher calls and parameter maps. **Drawback:** Sessions and results use Java interoperability, and this client makes little use of the driver's result types. |

The visible difference primarily concerns the **client interface for the same graph workload**. It says nothing yet about a plain relational PostgreSQL implementation.

## Vectors: PostgreSQL with pgvector and Qdrant

Code: [Python](../implementations/python/vector/main.py), [Kotlin](../implementations/kotlin/vector/src/main/kotlin/Vector.kt).

| Language | PostgreSQL/pgvector | Qdrant |
| --- | --- | --- |
| Python | **Advantage:** Vector search, metadata filtering, and updates fit parameterized SQL. **Drawback:** The client formats vectors as text and casts them to `vector`; distance semantics are encoded in the `<=>` operator. | **Advantage:** Collection, points, filters, and `exact=true` are visible as Python client models. **Drawback:** Collection lifecycle, payloads, and completed writes add API steps. |
| Kotlin | **Advantage:** JDBC keeps vectors and metadata in a familiar table model. **Drawback:** Vectors are again converted to text, and SQL parameters are set by position. | **Advantage:** The Java client provides concrete types for points and queries. **Drawback:** gRPC Protobuf builders, `Double`-to-`Float` conversion, and waiting on futures make the client lengthy. |

Python uses REST for Qdrant; Kotlin uses gRPC. Their developer experience therefore includes different protocols. Both explicitly request exact search in this example; ANN behavior is outside this assessment.

## Full-text search: PostgreSQL and OpenSearch

Code: [Python](../implementations/python/search/main.py), [Kotlin](../implementations/kotlin/search/src/main/kotlin/Search.kt).

| Language | PostgreSQL | OpenSearch |
| --- | --- | --- |
| Python | **Advantage:** Text analysis, weighting, and ranking are visible in the table definition and SQL; the change is a regular `UPDATE`. **Drawback:** Developers must compose `tsvector`, `tsquery`, and ranking expressions. | **Advantage:** `multi_match`, category filtering, and sorting fit Python dictionaries. **Drawback:** Mapping and index lifecycle are separate; after an update the client explicitly requests search visibility with `refresh=wait_for`. |
| Kotlin | **Advantage:** JDBC and SQL remain consistent with the other PostgreSQL clients. **Drawback:** Optional filters, parameter positions, and result mapping are handled manually. | **Advantage:** The Java API supplies typed builders for mappings and searches. **Drawback:** Those builders take substantial code; the current partial update needs a generic `Map` cast. |

PostgreSQL uses its built-in full-text search here, without an extension. The example establishes only the agreed hits and ordering, not general equivalence in text analysis or relevance models.

## Blobs: PostgreSQL `bytea` and RustFS through S3

Code: [Python](../implementations/python/blob/main.py), [Kotlin](../implementations/kotlin/blob/src/main/kotlin/Blob.kt).

| Language | PostgreSQL `bytea` | RustFS/S3 |
| --- | --- | --- |
| Python | **Advantage:** Bytes and metadata live in one table and are seeded in one transaction. **Drawback:** Object operations are expressed as SQL; for bytes `100–199`, the client translates to SQL's one-based position `101`. | **Advantage:** Boto3 offers direct upload, head, download, range, and delete operations. **Drawback:** Bucket creation, listing, 404 cases, credentials, and path-style addressing need integration code. |
| Kotlin | **Advantage:** `setBytes` and `getBytes` make `bytea` accessible, and the seed transaction is explicit. **Drawback:** Head, range, and delete are custom SQL queries with JDBC mapping. | **Advantage:** The AWS SDK expresses the file contract with S3 requests. **Drawback:** Client configuration and request builders are extensive, and one object request does not replace a transaction across objects. |

Both implementations verify full bytes, metadata, and the requested range. They do not treat an S3 `ETag` as a portable content hash.

## Cross-cutting findings

- **One PostgreSQL client family:** Psycopg or JDBC covers all five workloads. Domain details then move into SQL, casts, and, with AGE, embedded Cypher.
- **Domain-specific APIs:** Neo4j, Qdrant, OpenSearch, and S3 name graph, vector, search, and object operations directly. Their setup and error cases become additional client work. CouchDB represents documents directly but needs HTTP helpers, an index, and a view in these clients.
- **Language differences:** Python dictionaries fit JSON and REST APIs well. Kotlin effort depends on the Java API: Neo4j remains compact, while Qdrant and OpenSearch use many builders. JDBC is also more verbose in Kotlin than Psycopg is in Python.
- **Limit of the findings:** The examples use fixed, small datasets and simple standalone clients. They demonstrate the usability of these implemented paths, not a general ranking of stores or complete production integration.
