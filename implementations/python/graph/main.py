#!/usr/bin/env python3
"""Direct Apache AGE and Neo4j clients for the package dependency graph."""
import json
import os
import re
import sys
from pathlib import Path

import psycopg
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[3]
GRAPH = json.loads((ROOT / 'workloads/graph/packages.json').read_text())
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


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('age', 'neo4j', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {age|neo4j|both}')
    action, target = sys.argv[1:]
    for store in (['age', 'neo4j'] if target == 'both' else [target]):
        client = Age() if store == 'age' else Neo4j()
        try:
            if action == 'seed':
                client.seed()
            else:
                for label, cypher, expected in CASES:
                    actual = client.query(cypher)
                    if action == 'verify':
                        require(actual == expected, f'{client.name} {label}: expected {expected}, got {actual}')
                        print(f'Python/{client.name} {label}: OK')
                    else:
                        print(f'Python/{client.name} {label}: {actual}')
        finally:
            client.close()


if __name__ == '__main__':
    main()
