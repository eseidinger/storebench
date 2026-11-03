#!/usr/bin/env python3
"""Direct Apache AGE, Neo4j, and HugeGraph clients for the package graph."""
import gzip
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[3]
GRAPH = json.loads((ROOT / 'workloads/graph/packages.json').read_text())
HUGEGRAPH_FILES = ROOT / 'implementations/native/graph/hugegraph'
HUGEGRAPH_SCHEMA = json.loads((HUGEGRAPH_FILES / 'schema.json').read_text())
HUGEGRAPH_OPERATIONS = json.loads((HUGEGRAPH_FILES / 'operations.json').read_text())
CASES = [
    ('nodes', 'MATCH (p:Package) RETURN count(p)', ['6']),
    ('edges', 'MATCH ()-[r:DEPENDS_ON]->() RETURN count(r)', ['6']),
    ('direct', "MATCH (:Package {name: 'app'})-[:DEPENDS_ON]->(p:Package) RETURN p.name", ['api', 'web']),
    ('transitive', "MATCH (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(p:Package) RETURN DISTINCT p.name", ['api', 'auth', 'core', 'ui', 'web']),
    ('impact', "MATCH (p:Package)-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN DISTINCT p.name", ['api', 'app', 'auth', 'web']),
    ('paths', "MATCH path = (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN length(path)", ['2', '3']),
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Age:
    name = 'AGE'

    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv('STOREBENCH_AGE_HOST', '127.0.0.1'),
            port=int(os.getenv('STOREBENCH_AGE_PORT', '5455')),
            dbname='storebench', user='storebench', password='storebench_local',
            autocommit=True,
        )
        with self.connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS age')
            cursor.execute("LOAD 'age'")
            cursor.execute('SET search_path = ag_catalog, "$user", public')

    def close(self):
        self.connection.close()

    def execute(self, cypher):
        # AGE requires a literal Cypher body. These statements use fixed queries or
        # names validated below against the fixture's restricted identifier syntax.
        require('$$' not in cypher, 'Invalid Cypher delimiter')
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM cypher('dependencies', $$ " + cypher + ' $$) AS (value agtype)')

    def seed(self):
        names = GRAPH['packages']
        require(all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name) for name in names), 'Invalid package name')
        require(len(names) == len(set(names)), 'Duplicate package name')
        require(all(a in names and b in names for a, b in GRAPH['dependencies']), 'Unknown dependency endpoint')
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT drop_graph('dependencies', true) WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'dependencies')")
            cursor.execute("SELECT create_graph('dependencies')")
        for name in names:
            self.execute(f"CREATE (:Package {{name: '{name}'}})")
        for source, target in GRAPH['dependencies']:
            self.execute(f"MATCH (a:Package {{name: '{source}'}}), (b:Package {{name: '{target}'}}) CREATE (a)-[:DEPENDS_ON]->(b)")
        print(f'Python/AGE: inserted {len(names)} packages and {len(GRAPH["dependencies"])} dependencies')

    def query(self, cypher):
        require('$$' not in cypher, 'Invalid Cypher delimiter')
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT value::text FROM cypher('dependencies', $$ " + cypher + ' $$) AS (value agtype)')
            return sorted(row[0].strip('"') for row in cursor.fetchall())


class Neo4j:
    name = 'Neo4j'

    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv('STOREBENCH_NEO4J_URI', 'bolt://127.0.0.1:7688'),
            auth=('neo4j', 'storebench_local'),
        )
        self.driver.verify_connectivity()

    def close(self):
        self.driver.close()

    def seed(self):
        with self.driver.session() as session:
            session.run('MATCH (n) DETACH DELETE n').consume()
            session.run('CREATE CONSTRAINT package_name IF NOT EXISTS FOR (p:Package) REQUIRE p.name IS UNIQUE').consume()
            for name in GRAPH['packages']:
                session.run('CREATE (:Package {name: $name})', name=name).consume()
            for source, target in GRAPH['dependencies']:
                session.run('MATCH (a:Package {name: $source}), (b:Package {name: $target}) CREATE (a)-[:DEPENDS_ON]->(b)', source=source, target=target).consume()
        print(f'Python/Neo4j: inserted {len(GRAPH["packages"])} packages and {len(GRAPH["dependencies"])} dependencies')

    def query(self, cypher):
        with self.driver.session() as session:
            return sorted(str(record[0]) for record in session.run(cypher))


class HugeGraph:
    name = 'HugeGraph'
    graph_path = '/graphspaces/DEFAULT/graphs/hugegraph'

    def __init__(self):
        self.url = os.getenv('STOREBENCH_HUGEGRAPH_URL', 'http://127.0.0.1:8083').rstrip('/')
        self.request('GET', '/versions')

    def close(self):
        pass

    def request(self, method, path, body=None, missing_ok=False):
        payload = None if body is None else json.dumps(body).encode()
        req = Request(self.url + path, data=payload, method=method,
                      headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=30) as response:
                content = response.read()
                if response.headers.get('Content-Encoding') == 'gzip' or content.startswith(b'\x1f\x8b'):
                    content = gzip.decompress(content)
                return json.loads(content)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(f'HugeGraph {method} {path}: HTTP {exc.code}: {exc.read().decode()}') from exc
        except URLError as exc:
            raise RuntimeError(f'HugeGraph {method} {path}: {exc.reason}') from exc

    def gremlin(self, statement):
        response = self.request('POST', '/gremlin', {
            'gremlin': statement, 'aliases': {'g': '__g_DEFAULT-hugegraph'},
        })
        require(response.get('status', {}).get('code') == 200,
                f'HugeGraph Gremlin failed: {response.get("status")}')
        return response['result']['data']

    def seed(self):
        names = GRAPH['packages']
        edges = GRAPH['dependencies']
        require(len(names) == len(set(names)), 'Duplicate package name')
        require(len(edges) == len({tuple(edge) for edge in edges}), 'Duplicate dependency')
        require(all(a in names and b in names and a != b for a, b in edges), 'Invalid dependency endpoint')
        for group in ('propertykeys', 'vertexlabels', 'edgelabels'):
            for definition in HUGEGRAPH_SCHEMA[group]:
                path = f'{self.graph_path}/schema/{group}/{definition["name"]}'
                if self.request('GET', path, missing_ok=True) is None:
                    self.request('POST', f'{self.graph_path}/schema/{group}', definition)
        self.gremlin("g.V().hasLabel('Package').drop().iterate()")
        ids = {}
        for name in names:
            vertex = self.request('POST', f'{self.graph_path}/graph/vertices', {
                'label': 'Package', 'properties': {'name': name},
            })
            ids[name] = vertex['id']
        for source, target in edges:
            self.request('POST', f'{self.graph_path}/graph/edges', {
                'label': 'DEPENDS_ON', 'outV': ids[source], 'inV': ids[target],
                'outVLabel': 'Package', 'inVLabel': 'Package', 'properties': {},
            })
        print(f'Python/HugeGraph: inserted {len(names)} packages and {len(edges)} dependencies')

    def query(self, label, _cypher):
        values = self.gremlin(HUGEGRAPH_OPERATIONS[label])
        if label == 'paths':
            values = [len(path['objects'] if isinstance(path, dict) else path) - 1 for path in values]
        return sorted(str(value) for value in values)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('age', 'neo4j', 'hugegraph', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {age|neo4j|hugegraph|both}')
    action, target = sys.argv[1:]
    for store in (['age', 'neo4j', 'hugegraph'] if target == 'both' else [target]):
        client = Age() if store == 'age' else Neo4j() if store == 'neo4j' else HugeGraph()
        try:
            if action == 'seed':
                client.seed()
            else:
                for label, cypher, expected in CASES:
                    actual = client.query(label, cypher) if store == 'hugegraph' else client.query(cypher)
                    if action == 'verify':
                        require(actual == expected, f'{client.name} {label}: expected {expected}, got {actual}')
                        print(f'Python/{client.name} {label}: OK')
                    else:
                        print(f'Python/{client.name} {label}: {actual}')
        finally:
            client.close()


if __name__ == '__main__':
    main()
