#!/usr/bin/env python3
"""Direct OpenSearch REST operations using only the Python standard library."""
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'workloads/search/articles.json').read_text())
fixtures = root / 'implementations/native/search/opensearch'
base = 'http://127.0.0.1:9201/storebench_articles'

def request(method, path='', body=None, content_type='application/json', missing_ok=False):
    payload = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = Request(base + path, data=payload, method=method, headers={'Content-Type': content_type})
    try:
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise SystemExit(f'OpenSearch HTTP {exc.code}: {exc.read().decode()}') from exc

def search(category=None):
    query = {'multi_match': {'query': data['query'], 'fields': ['title^3', 'body'], 'operator': 'and'}}
    if category:
        query = {'bool': {'must': [query], 'filter': [{'term': {'category': category}}]}}
    response = request('POST', '/_search', {'query': query, 'size': 10, 'sort': [{'_score': 'desc'}, {'_id': 'asc'}]})
    return [(int(hit['_id']), hit['_score']) for hit in response['hits']['hits']]

action = sys.argv[1] if len(sys.argv) > 1 else ''
if action == 'seed':
    request('DELETE', missing_ok=True)
    request('PUT', body=json.loads((fixtures / 'mapping.json').read_text()))
    result = request('POST', '/_bulk?refresh=wait_for', (fixtures / 'bulk.ndjson').read_bytes(),
                     content_type='application/x-ndjson')
    if result.get('errors'):
        raise SystemExit(f'OpenSearch bulk load failed: {result}')
    print('OpenSearch: indexed', len(result['items']), 'articles')
elif action == 'run':
    print('before update:', search())
    print('guide before update:', search('guide'))
    update = data['update']
    result = request('POST', f"/_update/{update['id']}?refresh=wait_for", {'doc': {'body': update['body']}})
    if result.get('result') != 'updated':
        raise SystemExit(f'OpenSearch update failed: {result}')
    print('after update:', search())
    print('guide after update:', search('guide'))
elif action == 'verify':
    actual = [item[0] for item in search()]
    if actual != [6, 5]:
        raise SystemExit(f'Ranked results mismatch: {actual}')
    actual = [item[0] for item in search('guide')]
    if actual != [5]:
        raise SystemExit(f'Filtered results mismatch: {actual}')
    article = request('GET', '/_doc/5')['_source']
    if article['title'] != 'Storage overview':
        raise SystemExit('Title changed')
    count = request('GET', '/_count')['count']
    if count != 6:
        raise SystemExit(f'Expected six articles, got {count}')
    print('OpenSearch search check passed')
else:
    raise SystemExit('Usage: search_opensearch.py {seed|run|verify}')
