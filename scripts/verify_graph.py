#!/usr/bin/env python3
"""Check the graph contract against the native CLI of each selected store."""
import subprocess
import sys

stores = ['age', 'neo4j'] if len(sys.argv) < 2 or sys.argv[1] == 'both' else [sys.argv[1]]
if any(store not in ('age', 'neo4j') for store in stores):
    sys.exit('Store must be age, neo4j, or both')

cases = [
    ('nodes', 'MATCH (p:Package) RETURN count(p)', {'6'}),
    ('edges', 'MATCH ()-[r:DEPENDS_ON]->() RETURN count(r)', {'6'}),
    ('direct', "MATCH (:Package {name: 'app'})-[:DEPENDS_ON]->(p:Package) RETURN p.name", {'api', 'web'}),
    ('transitive', "MATCH (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(p:Package) RETURN DISTINCT p.name", {'api', 'auth', 'core', 'ui', 'web'}),
    ('impact', "MATCH (p:Package)-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN DISTINCT p.name", {'api', 'app', 'auth', 'web'}),
    ('paths', "MATCH path = (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN length(path)", {'2', '3'}),
]

for store in stores:
    for label, cypher, expected in cases:
        if store == 'age':
            sql = "LOAD 'age'; SET search_path = ag_catalog, \"$user\", public; SELECT value::text FROM cypher('dependencies', $$ " + cypher + " $$) AS (value agtype);"
            cmd = ['docker', 'compose', '-f', 'infrastructure/graph.compose.yaml', 'exec', '-T', 'age', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1', '-U', 'storebench', '-d', 'storebench']
            result = subprocess.run(cmd, input=sql, text=True, capture_output=True, check=True)
            actual = {line.strip().strip('"') for line in result.stdout.splitlines() if line.strip()}
        else:
            cmd = ['docker', 'compose', '-f', 'infrastructure/graph.compose.yaml', 'exec', '-T', 'neo4j', 'cypher-shell', '--non-interactive', '--format', 'plain', '-u', 'neo4j', '-p', 'storebench_local']
            result = subprocess.run(cmd, input=cypher + ';\n', text=True, capture_output=True, check=True)
            actual = {line.strip().strip('"') for line in result.stdout.splitlines()[1:] if line.strip()}
        if actual != expected:
            sys.exit(f'{store} {label}: expected {sorted(expected)}, got {sorted(actual)}')
        print(f'{store} {label}: OK')
