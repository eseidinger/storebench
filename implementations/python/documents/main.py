#!/usr/bin/env python3
"""Direct Psycopg and CouchDB HTTP implementation of the documents contract."""
import base64
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[3]
PRODUCTS = json.loads((ROOT / 'workloads/documents/products.json').read_text())
NATIVE_COUCH = ROOT / 'implementations/native/documents/couchdb'
EXPECTED_IDS = ['p001', 'p003', 'p005']
EXPECTED_TOTALS = {'apparel': (2, 22800), 'footwear': (2, 24800), 'gear': (2, 19800)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Postgres:
    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv('STOREBENCH_PG_HOST', '127.0.0.1'),
            port=int(os.getenv('STOREBENCH_PG_PORT', '5433')),
            dbname='storebench', user='storebench', password='storebench_local',
        )

    def close(self):
        self.connection.close()

    def seed(self):
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute('DROP TABLE IF EXISTS products')
                cursor.execute('CREATE TABLE products (id text PRIMARY KEY, doc jsonb NOT NULL)')
                cursor.executemany('INSERT INTO products (id, doc) VALUES (%s, %s)',
                                   [(product['id'], Jsonb(product)) for product in PRODUCTS])
                cursor.execute("CREATE INDEX products_category_idx ON products ((doc->>'category'))")
                cursor.execute("CREATE INDEX products_attributes_gin_idx ON products USING gin ((doc->'attributes'))")
        print('Python/PostgreSQL: inserted', len(PRODUCTS), 'products')

    def filtered(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM products WHERE doc->'attributes' @> %s::jsonb ORDER BY id",
                           (json.dumps({'color': 'blue', 'waterproof': True}),))
            return [row[0] for row in cursor.fetchall()]

    def totals(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT doc->>'category', count(*), sum((doc->>'price_cents')::integer) FROM products GROUP BY 1")
            return {category: (count, total) for category, count, total in cursor.fetchall()}

    def product(self, product_id):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT doc FROM products WHERE id = %s', (product_id,))
            row = cursor.fetchone()
            require(row is not None, f'Missing product {product_id}')
            return row[0]

    def run(self):
        print('product:', self.product('p001'))
        print('blue waterproof:', self.filtered())
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE products SET doc = jsonb_set(doc, '{attributes,waterproof}', 'true'::jsonb) WHERE id = %s", ('p002',))
            require(cursor.rowcount == 1, 'Expected one updated product')
        self.connection.commit()
        print('category totals:', self.totals())

    def verify(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM products')
            require(cursor.fetchone()[0] == 6, 'Expected six products')
        require(self.product('p001')['name'] == 'Trail Jacket', 'Lookup mismatch')
        require(self.filtered() == EXPECTED_IDS, 'Nested filter mismatch')
        require(self.product('p002')['attributes'] == {'color': 'black', 'size': 'L', 'waterproof': True}, 'Update mismatch')
        require(self.totals() == EXPECTED_TOTALS, 'Category totals mismatch')
        print('Python/PostgreSQL documents check passed')


class CouchDB:
    def __init__(self):
        self.server = os.getenv('STOREBENCH_COUCH_URL', 'http://127.0.0.1:5985')
        self.auth = 'Basic ' + base64.b64encode(b'storebench:storebench_local').decode()

    def request(self, method, path, body=None, missing_ok=False):
        payload = None if body is None else json.dumps(body).encode()
        request = Request(self.server + path, data=payload, method=method,
                          headers={'Authorization': self.auth, 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(f'CouchDB HTTP {exc.code}: {exc.read().decode()}') from exc

    def seed(self):
        state = self.request('GET', '/_cluster_setup')['state']
        if state != 'cluster_finished':
            setup = self.request('POST', '/_cluster_setup', {'action': 'enable_single_node',
                'bind_address': '0.0.0.0', 'username': 'storebench', 'password': 'storebench_local'})
            require(setup.get('ok'), f'CouchDB setup failed: {setup}')
        self.request('DELETE', '/products', missing_ok=True)
        self.request('PUT', '/products')
        docs = [{'_id': product['id'], **product} for product in PRODUCTS]
        results = self.request('POST', '/products/_bulk_docs', {'docs': docs})
        require(len(results) == len(docs) and all('error' not in row for row in results), f'Bulk insert failed: {results}')
        self.request('POST', '/products/_index', json.loads((NATIVE_COUCH / 'attributes_index.json').read_text()))
        self.request('PUT', '/products/_design/catalog', json.loads((NATIVE_COUCH / 'category_totals.json').read_text()))
        print('Python/CouchDB: inserted', len(docs), 'products')

    def product(self, product_id):
        return self.request('GET', '/products/' + product_id)

    def filtered(self):
        result = self.request('POST', '/products/_find', {'selector': {'attributes.color': 'blue',
            'attributes.waterproof': True}, 'fields': ['id'], 'limit': 100,
            'use_index': 'attributes_color_waterproof'})
        return sorted(row['id'] for row in result['docs'])

    def totals(self):
        rows = self.request('GET', '/products/_design/catalog/_view/category_totals?group=true')['rows']
        return {row['key']: (row['value']['count'], row['value']['sum']) for row in rows}

    def run(self):
        print('product:', self.product('p001'))
        print('blue waterproof:', self.filtered())
        product = self.product('p002')
        product['attributes']['waterproof'] = True
        updated = self.request('PUT', '/products/p002', product)
        require(updated.get('ok'), 'Update failed')
        print('category totals:', self.totals())

    def verify(self):
        rows = self.request('GET', '/products/_all_docs')['rows']
        require(len([row for row in rows if not row['id'].startswith('_design/')]) == 6, 'Expected six products')
        require(self.product('p001')['name'] == 'Trail Jacket', 'Lookup mismatch')
        require(self.filtered() == EXPECTED_IDS, 'Nested filter mismatch')
        require(self.product('p002')['attributes'] == {'color': 'black', 'size': 'L', 'waterproof': True}, 'Update mismatch')
        require(self.totals() == EXPECTED_TOTALS, 'Category totals mismatch')
        print('Python/CouchDB documents check passed')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('postgres', 'couchdb', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {postgres|couchdb|both}')
    action, store = sys.argv[1:]
    targets = [store] if store != 'both' else ['postgres', 'couchdb']
    for target in targets:
        client = Postgres() if target == 'postgres' else CouchDB()
        try:
            getattr(client, action)()
        finally:
            if isinstance(client, Postgres):
                client.close()

if __name__ == '__main__':
    main()
