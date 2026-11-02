#!/usr/bin/env python3
"""Direct PostgreSQL bytea and RustFS S3 clients for the blob contract."""
import hashlib
import json
import os
import sys
from pathlib import Path

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from blob_data import payload  # Reuse the canonical byte generator.

MANIFEST = json.loads((ROOT / 'workloads/blob/manifest.json').read_text())
BUCKET = MANIFEST['bucket']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Postgres:
    name = 'PostgreSQL'

    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv('STOREBENCH_BLOB_PG_HOST', '127.0.0.1'),
            port=int(os.getenv('STOREBENCH_BLOB_PG_PORT', '5436')),
            dbname='storebench', user='storebench', password='storebench_local',
        )

    def close(self):
        self.connection.close()

    def seed(self):
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute('DROP TABLE IF EXISTS blobs')
                cursor.execute('CREATE TABLE blobs (key text PRIMARY KEY, data bytea NOT NULL, content_type text NOT NULL, owner_name text NOT NULL)')
                cursor.executemany('INSERT INTO blobs (key, data, content_type, owner_name) VALUES (%s, %s, %s, %s)',
                    [(item['key'], payload(item), item['content_type'], item['owner']) for item in MANIFEST['objects']])
        print(f'Python/PostgreSQL: inserted {len(MANIFEST["objects"])} objects')

    def keys(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT key FROM blobs ORDER BY key')
            return [row[0] for row in cursor.fetchall()]

    def head(self, key):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT octet_length(data), content_type, owner_name FROM blobs WHERE key = %s', (key,))
            row = cursor.fetchone()
            return None if row is None else (row[0], row[1], row[2])

    def get(self, key, span=None):
        with self.connection.cursor() as cursor:
            if span is None:
                cursor.execute('SELECT data FROM blobs WHERE key = %s', (key,))
            else:
                cursor.execute('SELECT substring(data FROM %s FOR %s) FROM blobs WHERE key = %s',
                               (span[0] + 1, span[1] - span[0] + 1, key))
            row = cursor.fetchone()
            return None if row is None else bytes(row[0])

    def overwrite(self, item):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE blobs SET data = %s, content_type = %s, owner_name = %s WHERE key = %s',
                           (payload(item), item['content_type'], item['owner'], item['key']))
            require(cursor.rowcount == 1, 'PostgreSQL overwrite did not affect one object')
        self.connection.commit()

    def delete(self, key):
        with self.connection.cursor() as cursor:
            cursor.execute('DELETE FROM blobs WHERE key = %s', (key,))
            require(cursor.rowcount == 1, 'PostgreSQL delete did not affect one object')
        self.connection.commit()


class RustFS:
    name = 'RustFS'

    def __init__(self):
        self.client = boto3.client(
            's3', endpoint_url=os.getenv('STOREBENCH_RUSTFS_ENDPOINT', 'http://127.0.0.1:9002'),
            aws_access_key_id='storebench_local', aws_secret_access_key='storebench_secret_local',
            region_name='us-east-1', config=Config(s3={'addressing_style': 'path'}),
        )

    def close(self):
        self.client.close()

    def seed(self):
        try:
            self.client.head_bucket(Bucket=BUCKET)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
            self.client.create_bucket(Bucket=BUCKET)
        for page in self.client.get_paginator('list_objects_v2').paginate(Bucket=BUCKET):
            for object_ in page.get('Contents', []):
                self.client.delete_object(Bucket=BUCKET, Key=object_['Key'])
        for item in MANIFEST['objects']:
            self.put(item)
        print(f'Python/RustFS: uploaded {len(MANIFEST["objects"])} objects')

    def put(self, item):
        self.client.put_object(Bucket=BUCKET, Key=item['key'], Body=payload(item),
                               ContentType=item['content_type'], Metadata={'owner': item['owner']})

    def keys(self):
        result = []
        for page in self.client.get_paginator('list_objects_v2').paginate(Bucket=BUCKET):
            result.extend(object_['Key'] for object_ in page.get('Contents', []))
        return sorted(result)

    def head(self, key):
        try:
            result = self.client.head_object(Bucket=BUCKET, Key=key)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                return None
            raise
        return (result['ContentLength'], result['ContentType'], result['Metadata'].get('owner'))

    def get(self, key, span=None):
        kwargs = {'Bucket': BUCKET, 'Key': key}
        if span is not None:
            kwargs['Range'] = f'bytes={span[0]}-{span[1]}'
        try:
            response = self.client.get_object(**kwargs)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                return None
            raise
        with response['Body'] as body:
            return body.read()

    def overwrite(self, item):
        self.put(item)

    def delete(self, key):
        self.client.delete_object(Bucket=BUCKET, Key=key)


def check_item(store, item):
    expected = payload(item)
    actual = store.get(item['key'])
    require(actual == expected, f'{store.name} bytes mismatch: {item["key"]}')
    require(store.head(item['key']) == (len(expected), item['content_type'], item['owner']),
            f'{store.name} metadata mismatch: {item["key"]}')
    return len(actual), hashlib.sha256(actual).hexdigest()


def check_range(store):
    span = MANIFEST['range']
    source = next(item for item in MANIFEST['objects'] if item['key'] == span['key'])
    expected = payload(source)[span['start']:span['end'] + 1]
    actual = store.get(span['key'], (span['start'], span['end']))
    require(actual == expected, f'{store.name} range bytes mismatch')
    return len(actual), hashlib.sha256(actual).hexdigest()


def run(store):
    for item in MANIFEST['objects']:
        size, digest = check_item(store, item)
        print(f'Python/{store.name} get {item["key"]}: {size} bytes, sha256={digest}')
    size, digest = check_range(store)
    print(f'Python/{store.name} range: {size} bytes, sha256={digest}')
    store.overwrite(MANIFEST['overwrite'])
    store.delete(MANIFEST['delete'])


def verify(store):
    expected = {item['key']: item for item in MANIFEST['objects'] if item['key'] != MANIFEST['delete']}
    expected[MANIFEST['overwrite']['key']] = MANIFEST['overwrite']
    require(store.keys() == sorted(expected), f'{store.name} object keys mismatch')
    for item in expected.values():
        check_item(store, item)
    check_range(store)
    require(store.head(MANIFEST['delete']) is None, f'{store.name} deleted object still exists')
    print(f'Python/{store.name} blob check passed')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('postgres', 'rustfs', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {postgres|rustfs|both}')
    action, target = sys.argv[1:]
    for name in (['postgres', 'rustfs'] if target == 'both' else [target]):
        store = Postgres() if name == 'postgres' else RustFS()
        try:
            if action == 'seed':
                store.seed()
            elif action == 'run':
                run(store)
            else:
                verify(store)
        finally:
            store.close()


if __name__ == '__main__':
    main()
