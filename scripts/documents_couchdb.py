#!/usr/bin/env python3
"""Native CouchDB REST operations for the product-catalog use case."""
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
fixtures = root / 'implementations/native/documents/couchdb'
server = 'http://127.0.0.1:5985'
base = server + '/products'
credentials = base64.b64encode(b'storebench:storebench_local').decode()

def request(method, path='', body=None, missing_ok=False):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(base + path, data=payload, method=method,
                  headers={'Authorization': 'Basic ' + credentials, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise SystemExit(f'CouchDB HTTP {exc.code}: {exc.read().decode()}') from exc

def filtered():
    result = request('POST', '/_find', {
        'selector': {'attributes.color': 'blue', 'attributes.waterproof': True},
        'fields': ['id'], 'limit': 100, 'use_index': 'attributes_color_waterproof'
    })
    return sorted(doc['id'] for doc in result['docs'])

def totals():
    rows = request('GET', '/_design/catalog/_view/category_totals?group=true')['rows']
    return {row['key']: (row['value']['count'], row['value']['sum']) for row in rows}

action = sys.argv[1] if len(sys.argv) > 1 else ''
if action == 'seed':
    setup_url = server + '/_cluster_setup'
    headers = {'Authorization': 'Basic ' + credentials, 'Content-Type': 'application/json'}
    with urlopen(Request(setup_url, headers=headers), timeout=30) as response:
        state = json.load(response)['state']
    if state != 'cluster_finished':
        body = json.dumps({'action': 'enable_single_node', 'bind_address': '0.0.0.0',
                           'username': 'storebench', 'password': 'storebench_local'}).encode()
        with urlopen(Request(setup_url, data=body, method='POST', headers=headers), timeout=30) as response:
            setup = json.load(response)
        if not setup.get('ok'):
            raise SystemExit(f'CouchDB setup failed: {setup}')
    request('DELETE', missing_ok=True)
    request('PUT')
    docs = json.loads((fixtures / 'seed.json').read_text())
    response = request('POST', '/_bulk_docs', docs)
    if len(response) != len(docs['docs']) or any('error' in row for row in response):
        raise SystemExit(f'CouchDB seed failed: {response}')
    request('POST', '/_index', json.loads((fixtures / 'attributes_index.json').read_text()))
    request('PUT', '/_design/catalog', json.loads((fixtures / 'category_totals.json').read_text()))
    print(f'CouchDB: inserted {len(response)} products')
elif action == 'run':
    print('product:', request('GET', '/p001'))
    print('blue waterproof:', filtered())
    product = request('GET', '/p002')
    product['attributes']['waterproof'] = True
    print('update:', request('PUT', '/p002', product))
    print('category totals:', totals())
elif action == 'verify':
    expected = {'apparel': (2, 22800), 'footwear': (2, 24800), 'gear': (2, 19800)}
    all_docs = request('GET', '/_all_docs')['rows']
    products = [row for row in all_docs if not row['id'].startswith('_design/')]
    if len(products) != 6:
        raise SystemExit(f'Expected six products, got {len(products)}')
    if request('GET', '/p001')['name'] != 'Trail Jacket':
        raise SystemExit('Product lookup mismatch')
    if filtered() != ['p001', 'p003', 'p005']:
        raise SystemExit('Nested filter mismatch')
    changed = request('GET', '/p002')
    if changed['attributes'] != {'color': 'black', 'size': 'L', 'waterproof': True}:
        raise SystemExit('Partial update mismatch')
    if totals() != expected:
        raise SystemExit(f'Category aggregation mismatch: {totals()}')
    print('CouchDB documents check passed')
else:
    raise SystemExit('Usage: documents_couchdb.py {seed|run|verify}')
