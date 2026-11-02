# Graph: package dependencies

This executable StoreBench use case compares [Apache AGE](https://age.apache.org/getstarted/quickstart/) and [Neo4j](https://neo4j.com/docs/operations-manual/current/docker/introduction/) using the same directed software package dependency graph. AGE is a PostgreSQL graph extension; it is distinct from the plain node/edge-table PostgreSQL baseline proposed in the main README. This slice verifies behavior only. It does not provide latency or throughput measurements, Python/Kotlin clients, or a relational PostgreSQL baseline yet.

## Run locally

Requirements: Docker with Compose, Python 3, and enough free resources for two containers. The Compose file uses Apache AGE 1.7.0 on PostgreSQL 17 and Neo4j 5.26.32. Ports are bound to localhost: AGE/PostgreSQL at 5455, Neo4j Browser at 7475, and Bolt at 7688. Fixed credentials (`storebench`/`storebench_local` for AGE, `neo4j`/`storebench_local` for Neo4j) are for local development only.

From the repository root:

```bash
scripts/graph.sh up
scripts/graph.sh seed both
scripts/graph.sh run both
scripts/graph.sh verify both
scripts/graph.sh down
```

`seed` resets the graph and recreates the six packages and six directed dependency edges from [packages.json](../workloads/graph/packages.json). It also regenerates the native seed scripts. Rerun `seed` before repeating a modified workload. `down` keeps the volumes; `docker compose -f infrastructure/graph.compose.yaml down -v` removes them deliberately. `seed`, `run`, and `verify` accept `age`, `neo4j`, or `both`.

## Contract

An edge `A -[:DEPENDS_ON]-> B` means package A directly depends on B. Package names are unique. All traversals follow this edge direction; impact analysis traverses from candidate dependents to the changed package. The graph is acyclic and all variable-length traversals are bounded to one through four edges. Reachability returns distinct package names. Path enumeration keeps different paths to the same destination.

| Query | Expected result |
| --- | --- |
| Direct dependencies of `app` | `api`, `web` |
| All transitive dependencies of `app` (including direct) | `api`, `auth`, `core`, `ui`, `web` |
| Packages affected by changing `core` | `api`, `app`, `auth`, `web` |
| Paths from `app` to `core` | `app → web → core` (2 edges); `app → api → auth → core` (3 edges) |

The native operation scripts display results in each database's own format. The verifier uses each database's CLI, compares exact result sets and path lengths, and checks node and edge counts. It exits nonzero on any mismatch. AGE's raw path representation includes internal vertex and edge IDs, so path lengths are used for automated cross-store verification on this fixed graph.

## Files and limits

- `infrastructure/graph.compose.yaml`: both services, health checks, resource limits, and persistent volumes.
- `workloads/graph/packages.json`: canonical graph.
- `scripts/generate_graph.py`: generates native seed scripts from the canonical graph.
- `implementations/native/graph/age/`: SQL and AGE Cypher seed and operation scripts.
- `implementations/native/graph/neo4j/`: Neo4j Cypher seed and operation scripts.
- `scripts/graph.sh` and `scripts/verify_graph.py`: local workflow and result checks.

The local functional check runs both stores together. A future benchmark should measure one store at a time, add the relational PostgreSQL baseline, record query plans and effective limits, and use larger graphs with varied degree distributions and independent repetitions. Apache AGE requires `LOAD 'age'` and an AGE-aware search path in each PostgreSQL session; the scripts set these explicitly. [AGE documents its Cypher SQL function](https://age.apache.org/age-manual/master/intro/cypher.html), while [Neo4j documents `cypher-shell` scripting](https://neo4j.com/docs/operations-manual/current/cypher-shell/).

Interactive access to both stores is listed in [local store access](access.md).
