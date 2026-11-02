# Local store access

The workflow scripts in each use-case guide remain the primary way to load data and check behavior. The services below provide interactive access for inspection. All published ports bind to `127.0.0.1`; the fixed credentials are for local development only.

| Use case | Store | Access |
| --- | --- | --- |
| Documents | PostgreSQL | pgAdmin at `http://localhost:5053` (optional `ui` profile), or `psql` in the container |
| Documents | CouchDB | Built-in Fauxton at `http://localhost:5985/_utils/` |
| Graph | Apache AGE | pgAdmin at `http://localhost:5057` (optional `ui` profile), or `psql` in the container |
| Graph | Neo4j | Built-in Browser at `http://localhost:7475` |
| Vectors | PostgreSQL with pgvector | pgAdmin at `http://localhost:5054` (optional `ui` profile), or `psql` in the container |
| Vectors | Qdrant | Built-in dashboard at `http://localhost:6334/dashboard` |
| Full-text search | PostgreSQL | pgAdmin at `http://localhost:5055` (optional `ui` profile), or `psql` in the container |
| Full-text search | OpenSearch | Dashboards at `http://localhost:5602` (optional `ui` profile); REST at `http://localhost:9201` |
| Blob storage | PostgreSQL | pgAdmin at `http://localhost:5056` (optional `ui` profile), or `psql` in the container |
| Blob storage | RustFS | Built-in Console at `http://localhost:9003/rustfs/console/`; S3 API at `http://localhost:9002` |

Start the target use case first, for example `scripts/search.sh up`. Then start its optional UI:

```bash
docker compose -f infrastructure/search.compose.yaml --profile ui up -d pgadmin dashboards
```

For the other use cases, replace `search.compose.yaml` with the matching Compose file and start `pgadmin` only. Normal `scripts/<use-case>.sh up` does not start pgAdmin or Dashboards. `scripts/<use-case>.sh down` stops the UI services in the same Compose project as well.

pgAdmin login is `storebench@example.com` / `storebench_local`. Add a server with host `postgres` (or `age` for the graph use case), port `5432`, maintenance database `storebench`, username `storebench`, and password `storebench_local`. This is the **Compose service hostname**, not the published host port. In AGE's Query Tool, run `LOAD 'age'; SET search_path = ag_catalog, "$user", public;` in each new session before calling `cypher(...)`.

CouchDB Fauxton uses `storebench` / `storebench_local`. Neo4j Browser uses `neo4j` / `storebench_local`; connect over Bolt at `bolt://localhost:7688` if the Browser does not pick up the mapped port automatically. RustFS Console uses `storebench_local` / `storebench_secret_local`. Qdrant and OpenSearch have no authentication in these localhost-only profiles. Neither pgAdmin nor Dashboards is part of measured database workloads; stop them before benchmarking.
