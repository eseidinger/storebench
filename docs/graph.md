# Graph: package dependencies

This executable StoreBench use case compares [Apache AGE](https://age.apache.org/getstarted/quickstart/) and [Neo4j](https://neo4j.com/docs/operations-manual/current/docker/introduction/) using the same directed software package dependency graph. AGE is a PostgreSQL graph extension; it is distinct from the plain node/edge-table PostgreSQL baseline proposed in the main README. This slice verifies behavior through native scripts and direct Python/Kotlin clients. It does not provide latency or throughput measurements or a relational PostgreSQL baseline yet.

## Run locally

Requirements: Docker with Compose, Python 3, Java 17 or newer, and enough free resources for two containers. The Compose file uses Apache AGE 1.7.0 on PostgreSQL 17 and Neo4j 5.26.32. Ports are bound to localhost: AGE/PostgreSQL at 5455, Neo4j Browser at 7475, and Bolt at 7688. Fixed credentials (`storebench`/`storebench_local` for AGE, `neo4j`/`storebench_local` for Neo4j) are for local development only.

From the repository root:

```bash
scripts/graph.sh up
scripts/graph.sh seed both
scripts/graph.sh run both
scripts/graph.sh verify both
scripts/graph.sh down
```

`seed` resets the graph and recreates the six packages and six directed dependency edges from [packages.json](../workloads/graph/packages.json). It also regenerates the native seed scripts. Rerun `seed` before repeating a modified workload. `down` keeps the volumes; `docker compose -f infrastructure/graph.compose.yaml down -v` removes them deliberately. `seed`, `run`, and `verify` accept `age`, `neo4j`, or `both`.

### Python client

From the repository root, start the stores with `scripts/graph.sh up`, then run:

```bash
python3 -m venv implementations/python/graph/.venv
implementations/python/graph/.venv/bin/pip install -r implementations/python/graph/requirements.txt
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py seed both
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py run both
implementations/python/graph/.venv/bin/python implementations/python/graph/main.py verify both
```

The client uses Psycopg for AGE and the Neo4j Python driver for Bolt. It reads the same `packages.json` fixture as the native generator. `seed` replaces the graph in each selected store. To target a single store, replace `both` with `age` or `neo4j`.

### Kotlin client

From the repository root, with the stores running:

```bash
cd implementations/kotlin/graph
./gradlew installDist
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin seed both
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin run both
build/install/storebench-graph-kotlin/bin/storebench-graph-kotlin verify both
```

The Kotlin client uses PostgreSQL JDBC for AGE and the Neo4j Java driver through Kotlin Java interoperability. Run it from `implementations/kotlin/graph` so it can find the canonical fixture. Its `seed` also replaces the selected graphs. Use one seeding command from either client before running both clients' queries; the clients share the stores.

Client connection overrides: `STOREBENCH_AGE_HOST`, `STOREBENCH_AGE_PORT`, and `STOREBENCH_NEO4J_URI`. Defaults are the local Compose ports above. Both clients use the fixed local credentials from Compose.

## Contract

An edge `A -[:DEPENDS_ON]-> B` means package A directly depends on B. Package names are unique. All traversals follow this edge direction; impact analysis traverses from candidate dependents to the changed package. The graph is acyclic and all variable-length traversals are bounded to one through four edges. Reachability returns distinct package names. Path enumeration keeps different paths to the same destination.

| Query | Expected result |
| --- | --- |
| Direct dependencies of `app` | `api`, `web` |
| All transitive dependencies of `app` (including direct) | `api`, `auth`, `core`, `ui`, `web` |
| Packages affected by changing `core` | `api`, `app`, `auth`, `web` |
| Paths from `app` to `core` | `app → web → core` (2 edges); `app → api → auth → core` (3 edges) |

The native operation scripts display results in each database's own format. The native verifier uses each database's CLI. The Python and Kotlin verifiers query directly through their drivers. All verifiers check node and edge counts and exit nonzero on mismatches. The direct clients compare sorted result lists, preserving path length multiplicity; the native verifier compares result sets. AGE's raw path representation includes internal vertex and edge IDs, so path lengths are used for automated cross-store verification on this fixed graph.

## Files and limits

- `infrastructure/graph.compose.yaml`: both services, health checks, resource limits, and persistent volumes.
- `workloads/graph/packages.json`: canonical graph.
- `scripts/generate_graph.py`: generates native seed scripts from the canonical graph.
- `implementations/native/graph/age/`: SQL and AGE Cypher seed and operation scripts.
- `implementations/native/graph/neo4j/`: Neo4j Cypher seed and operation scripts.
- `scripts/graph.sh` and `scripts/verify_graph.py`: native local workflow and result checks.
- `implementations/python/graph/` and `implementations/kotlin/graph/`: direct clients with seed, run, and verify commands.

The local functional check runs both stores together. A future benchmark should measure one store at a time, add the relational PostgreSQL baseline, record query plans and effective limits, and use larger graphs with varied degree distributions and independent repetitions. Apache AGE requires `LOAD 'age'` and an AGE-aware search path in each PostgreSQL session; the scripts set these explicitly. [AGE documents its Cypher SQL function](https://age.apache.org/age-manual/master/intro/cypher.html), while [Neo4j documents `cypher-shell` scripting](https://neo4j.com/docs/operations-manual/current/cypher-shell/).

Interactive access to both stores is listed in [local store access](access.md).
