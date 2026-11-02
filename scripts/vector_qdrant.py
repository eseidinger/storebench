#!/usr/bin/env python3
"""Direct Qdrant REST requests for the vector use case (Python standard library)."""
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'workloads/vector/documents.json').read_text())
base = 'http://127.0.0.1:6334/collections/storebench_documents'

def request(method, path='', body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(base + path, data=payload, headers={'Content-Type': 'application/json'}, method=method)
    try:
        with urlopen(req, timeout=20) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise SystemExit(f'Qdrant HTTP {exc.code}: {exc.read().decode()}') from exc
    if result.get('status') not in ('ok', 'acknowledged', 'completed'):
        raise SystemExit(f'Qdrant request failed: {result}')
    return result

def search(limit, category=None):
    body = {'query': data['query'], 'limit': limit, 'params': {'exact': True}, 'with_payload': True}
    if category:
        body['filter'] = {'must': [{'key': 'category', 'match': {'value': category}}]}
    result = request('POST', '/points/query', body)['result']['points']
    return [(point['id'], point['score']) for point in result]

action = sys.argv[1] if len(sys.argv) > 1 else ''
if action == 'seed':
    try:
        request('DELETE')
    except SystemExit as exc:
        if 'HTTP 404' not in str(exc):
            raise
    request('PUT', body={'vectors': {'size': data['dimension'], 'distance': data['distance']}})
    points = json.loads((root / 'implementations/native/vector/qdrant/points.json').read_text())
    request('PUT', '/points?wait=true', points)
    print('Qdrant: inserted', len(points['points']), 'documents')
elif action == 'run':
    print('top-3:', search(3))
    print('guide top-2:', search(2, 'guide'))
    update = data['update']
    request('PUT', '/points/vectors?wait=true', {'points': [{'id': update['id'], 'vector': update['vector']}]})
    print('after update:', search(3))
elif action == 'verify':
    actual = [item[0] for item in search(3)]
    if actual != [1, 3, 2]:
        raise SystemExit(f'Updated top-k mismatch: {actual}')
    actual = [item[0] for item in search(2, 'guide')]
    if actual != [1, 6]:
        raise SystemExit(f'Filtered top-k mismatch: {actual}')
    point = request('POST', '/points', {'ids': [3], 'with_payload': True})['result'][0]
    if point['payload']['category'] != 'article':
        raise SystemExit('Metadata changed')
    print('Qdrant vector check passed')
else:
    raise SystemExit('Usage: vector_qdrant.py {seed|run|verify}')
