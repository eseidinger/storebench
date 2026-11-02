#!/usr/bin/env python3
"""Generate equivalent AGE and Neo4j fixtures from one graph definition."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'workloads/graph/packages.json').read_text())
nodes = data['packages']
edges = data['dependencies']
assert len(nodes) == len(set(nodes))
assert len(edges) == len({tuple(edge) for edge in edges})
assert all(a in nodes and b in nodes and a != b for a, b in edges)
assert all(name.isidentifier() for name in nodes)
base = root / 'implementations/native/graph'
age = [
    r'\set ON_ERROR_STOP on',
    'CREATE EXTENSION IF NOT EXISTS age;',
    'LOAD \'age\';',
    'SET search_path = ag_catalog, "$user", public;',
    "SELECT drop_graph('dependencies', true) WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'dependencies');",
    "SELECT create_graph('dependencies');",
]
for name in nodes:
    age.append(f"SELECT * FROM cypher('dependencies', $$ CREATE (:Package {{name: '{name}'}}) $$) AS (result agtype);")
for source, target in edges:
    age.append(f"SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {{name: '{source}'}}), (b:Package {{name: '{target}'}}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);")
(base / 'age/seed.sql').write_text('\n'.join(age) + '\n')
neo = ['MATCH (n:Package) DETACH DELETE n;', 'CREATE CONSTRAINT package_name IF NOT EXISTS FOR (n:Package) REQUIRE n.name IS UNIQUE;']
neo += [f"CREATE (:Package {{name: '{name}'}});" for name in nodes]
neo += [f"MATCH (a:Package {{name: '{source}'}}), (b:Package {{name: '{target}'}}) CREATE (a)-[:DEPENDS_ON]->(b);" for source, target in edges]
(base / 'neo4j/seed.cypher').write_text('\n'.join(neo) + '\n')
