# Graph: package dependencies

This executable StoreBench use case compares [Apache AGE](https://age.apache.org/getstarted/quickstart/), [Neo4j](https://neo4j.com/docs/operations-manual/current/docker/introduction/), and [Apache HugeGraph](https://hugegraph.apache.org/docs/quickstart/hugegraph/hugegraph-server/) using the same directed software package dependency graph. AGE is a PostgreSQL graph extension; it is distinct from the plain node/edge-table PostgreSQL baseline proposed in the main README. All three stores have native, direct Python, and direct Kotlin seed, run, and verify paths. This slice does not provide latency or throughput measurements or a relational PostgreSQL baseline yet.

## Run locally

Requirements: Docker with Compose, Python 3, Java 17 or newer, and enough free resources for three containers when running all stores. The Compose file uses Apache AGE 1.7.0 on PostgreSQL 17, Neo4j 5.26.32, and HugeGraph 1.7.0 with RocksDB. Ports are bound to localhost: AGE/PostgreSQL at 5455, Neo4j Browser at 7475, Bolt at 7688, and HugeGraph REST at 8083. Fixed credentials (`storebench`/`storebench_local` for AGE, `neo4j`/`storebench_local` for Neo4j) are for local development only; this HugeGraph profile has no authentication and is reachable only from the local host.

From the repository root:

```bash
scripts/graph.sh up
scripts/graph.sh seed both
scripts/graph.sh run both
scripts/graph.sh verify both
scripts/graph.sh down
```

`seed` resets the selected graph fixture and recreates the six packages and six directed dependency edges from [packages.json](../workloads/graph/packages.json). For AGE and Neo4j it also regenerates native seed scripts. HugeGraph reads the fixture directly, creates its schema when needed, and replaces `Package` vertices through the [REST and Gremlin APIs](https://hugegraph.apache.org/versions/1.7/docs/clients/restful-api/). Rerun `seed` before repeating a modified workload. `down` keeps the volumes; `docker compose -f infrastructure/graph.compose.yaml down -v` removes them deliberately. Native `seed`, `run`, and `verify` accept `age`, `neo4j`, `hugegraph`, or `both`; `both` means all three stores. `up hugegraph` starts only HugeGraph; plain `up` starts all three.

To run only the HugeGraph native path:

```bash
scripts/graph.sh up hugegraph
scripts/graph.sh seed hugegraph
scripts/graph.sh run hugegraph
scripts/graph.sh verify hugegraph
scripts/graph.sh down
```

### Python client

From the repository root, start all three stores with `scripts/graph.sh up`, then run:

```bash
python3 -m venv implementations/python/graph/.venv
implementations/python/graph/.venv/bin/pip install -r implementations/python/graph/requirements.txt
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py seed both
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py run both
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py verify both
```

The client uses Psycopg for AGE, the Neo4j Python driver for Bolt, and Python HTTP requests for HugeGraph REST/Gremlin. It reads the same `packages.json` fixture as the native generator. `seed` replaces the graph in each selected store. To target a single store, replace `both` with `age`, `neo4j`, or `hugegraph`.

### Kotlin client

From the repository root, with the stores running:

```bash
cd implementations/kotlin/graph
./gradlew installDist
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin seed both
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin run both
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin verify both
```

The Kotlin client uses PostgreSQL JDBC for AGE, the Neo4j Java driver, and the JDK HTTP client for HugeGraph REST/Gremlin. Run it from `implementations/kotlin/graph` so it can find the canonical fixture. Its `seed` also replaces the selected graphs. Use one seeding command from either client before running both clients' queries; the clients share the stores.

Client connection overrides: `STOREBENCH_AGE_HOST`, `STOREBENCH_AGE_PORT`, `STOREBENCH_NEO4J_URI`, and `STOREBENCH_HUGEGRAPH_URL`. Defaults are the local Compose ports above. AGE and Neo4j use the fixed local credentials from Compose; HugeGraph uses the localhost-only unauthenticated REST port.

## Contract

An edge `A -[:DEPENDS_ON]-> B` means package A directly depends on B. Package names are unique. All traversals follow this edge direction; impact analysis traverses from candidate dependents to the changed package. The graph is acyclic and all variable-length traversals are bounded to one through four edges. Reachability returns distinct package names. Path enumeration keeps different paths to the same destination.

| Query | Expected result |
| --- | --- |
| Direct dependencies of `app` | `api`, `web` |
| All transitive dependencies of `app` (including direct) | `api`, `auth`, `core`, `ui`, `web` |
| Packages affected by changing `core` | `api`, `app`, `auth`, `web` |
| Paths from `app` to `core` | `app → web → core` (2 edges); `app → api → auth → core` (3 edges) |

The native operation scripts display results in each database's own format. AGE and Neo4j are verified through their CLIs; HugeGraph uses direct REST/Gremlin requests and checks the two complete package paths. The Python and Kotlin verifiers query all three stores directly through their drivers or HTTP clients. All verifiers check node and edge counts and exit nonzero on mismatches. The direct clients compare sorted result lists, preserving path length multiplicity; the AGE/Neo4j native verifier compares result sets. AGE's raw path representation includes internal vertex and edge IDs, so path lengths are used for automated cross-store verification on this fixed graph.

## Files and limits

- `infrastructure/graph.compose.yaml`: three services, health checks, resource limits, and persistent volumes.
- `workloads/graph/packages.json`: canonical graph.
- `scripts/generate_graph.py`: generates native seed scripts from the canonical graph.
- `implementations/native/graph/age/`: SQL and AGE Cypher seed and operation scripts.
- `implementations/native/graph/neo4j/`: Neo4j Cypher seed and operation scripts.
- `implementations/native/graph/hugegraph/`: HugeGraph schema, Gremlin operations, and direct REST runner.
- `scripts/graph.sh` and `scripts/verify_graph.py`: native local workflow and result checks.
- `implementations/python/graph/` and `implementations/kotlin/graph/`: direct clients with seed, run, and verify commands.

The local native functional check runs all three stores together. A future benchmark should measure one store at a time, add the relational PostgreSQL baseline, record query plans and effective limits, and use larger graphs with varied degree distributions and independent repetitions. Apache AGE requires `LOAD 'age'` and an AGE-aware search path in each PostgreSQL session; the scripts set these explicitly. [AGE documents its Cypher SQL function](https://age.apache.org/age-manual/master/intro/cypher.html), while [Neo4j documents `cypher-shell` scripting](https://neo4j.com/docs/operations-manual/current/cypher-shell/).

Interactive access to the stores is listed in [local store access](access.md).
