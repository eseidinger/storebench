#!/usr/bin/env python3
"""Native HugeGraph REST and Gremlin requests for the package graph fixture."""
import gzip
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[4]
directory = Path(__file__).resolve().parent
fixture = json.loads((root / 'workloads/graph/packages.json').read_text())
schema = json.loads((directory / 'schema.json').read_text())
operations = json.loads((directory / 'operations.json').read_text())
host = os.environ.get('STOREBENCH_HUGEGRAPH_URL', 'http://127.0.0.1:8083').rstrip('/')
graph_path = '/graphspaces/DEFAULT/graphs/hugegraph'


def request(method, path, body=None, missing_ok=False):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(host + path, data=payload, method=method,
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
        raise SystemExit(f'HugeGraph {method} {path}: HTTP {exc.code}: {exc.read().decode()}') from exc
    except URLError as exc:
        raise SystemExit(f'HugeGraph {method} {path}: {exc.reason}') from exc


def gremlin(statement):
    result = request('POST', '/gremlin', {
        'gremlin': statement,
        'aliases': {'g': '__g_DEFAULT-hugegraph'},
    })
    status = result.get('status', {})
    if status.get('code') != 200:
        raise SystemExit(f'HugeGraph Gremlin failed: {status}')
    return result['result']['data']


def query(name):
    return gremlin(operations[name])


def ensure_schema():
    endpoints = {
        'propertykeys': 'propertykeys',
        'vertexlabels': 'vertexlabels',
        'edgelabels': 'edgelabels',
    }
    for group, endpoint in endpoints.items():
        for definition in schema[group]:
            path = f'{graph_path}/schema/{endpoint}/{definition["name"]}'
            if request('GET', path, missing_ok=True) is None:
                request('POST', f'{graph_path}/schema/{endpoint}', definition)


def seed():
    packages = fixture['packages']
    dependencies = fixture['dependencies']
    if len(packages) != len(set(packages)) or any(
        source not in packages or target not in packages or source == target
        for source, target in dependencies
    ) or len(dependencies) != len({tuple(edge) for edge in dependencies}):
        raise SystemExit('Invalid graph fixture')
    ensure_schema()
    gremlin("g.V().hasLabel('Package').drop().iterate()")
    ids = {}
    for name in packages:
        vertex = request('POST', f'{graph_path}/graph/vertices', {
            'label': 'Package', 'properties': {'name': name},
        })
        ids[name] = vertex['id']
    for source, target in dependencies:
        request('POST', f'{graph_path}/graph/edges', {
            'label': 'DEPENDS_ON',
            'outV': ids[source], 'inV': ids[target],
            'outVLabel': 'Package', 'inVLabel': 'Package',
            'properties': {},
        })
    print(f'HugeGraph: inserted {len(packages)} packages and {len(dependencies)} dependencies')


def paths():
    result = []
    for path in query('paths'):
        if isinstance(path, dict):
            path = path['objects']
        result.append(tuple(path))
    return result


def run():
    for name in ('direct', 'transitive', 'impact'):
        print(f'{name}: {sorted(query(name))}')
    print(f'paths: {sorted(paths())}')


def verify():
    expected = {
        'nodes': [len(fixture['packages'])],
        'edges': [len(fixture['dependencies'])],
        'direct': ['api', 'web'],
        'transitive': ['api', 'auth', 'core', 'ui', 'web'],
        'impact': ['api', 'app', 'auth', 'web'],
    }
    for name, values in expected.items():
        actual = query(name)
        if sorted(actual) != sorted(values):
            raise SystemExit(f'HugeGraph {name}: expected {values}, got {actual}')
        print(f'hugegraph {name}: OK')
    expected_paths = {
        ('app', 'web', 'core'),
        ('app', 'api', 'auth', 'core'),
    }
    actual_paths = paths()
    if len(actual_paths) != len(expected_paths) or set(actual_paths) != expected_paths:
        raise SystemExit(f'HugeGraph paths: expected {sorted(expected_paths)}, got {sorted(actual_paths)}')
    print('hugegraph paths: OK')


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action == 'seed':
        seed()
    elif action == 'run':
        run()
    elif action == 'verify':
        verify()
    else:
        raise SystemExit('Usage: main.py {seed|run|verify}')
