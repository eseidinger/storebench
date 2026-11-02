#!/usr/bin/env python3
"""Direct pgvector and Qdrant clients for the exact vector-search contract."""
import json
import os
import sys
from pathlib import Path

import psycopg
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / 'workloads/vector/documents.json').read_text())
COLLECTION = 'storebench_documents'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def vector_text(values):
    return '[' + ','.join(str(value) for value in values) + ']'


class Postgres:
    name = 'PostgreSQL'

    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv('STOREBENCH_VECTOR_PG_HOST', '127.0.0.1'),
            port=int(os.getenv('STOREBENCH_VECTOR_PG_PORT', '5434')),
            dbname='storebench', user='storebench', password='storebench_local',
        )

    def close(self):
        self.connection.close()

    def seed(self):
        with self.connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')
        self.connection.commit()
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute('DROP TABLE IF EXISTS documents')
                cursor.execute(f'''CREATE TABLE documents (
                    id integer PRIMARY KEY, title text NOT NULL, category text NOT NULL,
                    embedding vector({DATA['dimension']}) NOT NULL
                )''')
                cursor.executemany('INSERT INTO documents (id, title, category, embedding) VALUES (%s, %s, %s, %s::vector)',
                    [(d['id'], d['title'], d['category'], vector_text(d['vector'])) for d in DATA['documents']])
                cursor.execute('CREATE INDEX documents_category_idx ON documents (category)')
        print(f'Python/PostgreSQL: inserted {len(DATA["documents"])} documents')

    def search(self, limit, category=None):
        query_vector = vector_text(DATA['query'])
        sql = 'SELECT id, embedding <=> %s::vector AS distance FROM documents'
        params = [query_vector]
        if category is not None:
            sql += ' WHERE category = %s'
            params.append(category)
        sql += ' ORDER BY embedding <=> %s::vector, id LIMIT %s'
        params.extend((query_vector, limit))
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def update(self):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE documents SET embedding = %s::vector WHERE id = %s',
                (vector_text(DATA['update']['vector']), DATA['update']['id']))
            require(cursor.rowcount == 1, 'PostgreSQL update did not affect one document')
        self.connection.commit()

    def document(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT title, category FROM documents WHERE id = %s', (DATA['update']['id'],))
            row = cursor.fetchone()
            require(row is not None, 'PostgreSQL document 3 missing')
            return {'title': row[0], 'category': row[1]}

    def count(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM documents')
            return cursor.fetchone()[0]


class Qdrant:
    name = 'Qdrant'

    def __init__(self):
        self.client = QdrantClient(url=os.getenv('STOREBENCH_QDRANT_URL', 'http://127.0.0.1:6334'), prefer_grpc=False)

    def close(self):
        self.client.close()

    def seed(self):
        if self.client.collection_exists(COLLECTION):
            self.client.delete_collection(COLLECTION)
        self.client.create_collection(COLLECTION, vectors_config=models.VectorParams(
            size=DATA['dimension'], distance=models.Distance(DATA['distance'])))
        points = [models.PointStruct(id=d['id'], vector=d['vector'],
                  payload={'title': d['title'], 'category': d['category']}) for d in DATA['documents']]
        result = self.client.upsert(COLLECTION, points=points, wait=True)
        require(result.status == models.UpdateStatus.COMPLETED, f'Qdrant upsert failed: {result}')
        print(f'Python/Qdrant: inserted {len(points)} documents')

    def search(self, limit, category=None):
        query_filter = None if category is None else models.Filter(must=[
            models.FieldCondition(key='category', match=models.MatchValue(value=category))])
        points = self.client.query_points(COLLECTION, query=DATA['query'], limit=limit,
            query_filter=query_filter, search_params=models.SearchParams(exact=True),
            with_payload=False).points
        return [(point.id, point.score) for point in points]

    def update(self):
        result = self.client.update_vectors(COLLECTION, points=[models.PointVectors(
            id=DATA['update']['id'], vector=DATA['update']['vector'])], wait=True)
        require(result.status == models.UpdateStatus.COMPLETED, f'Qdrant vector update failed: {result}')

    def document(self):
        points = self.client.retrieve(COLLECTION, ids=[DATA['update']['id']], with_payload=True)
        require(len(points) == 1, 'Qdrant document 3 missing')
        return points[0].payload

    def count(self):
        return self.client.count(COLLECTION, exact=True).count


def ids(results):
    return [id for id, _ in results]


def run(store):
    print(f'Python/{store.name} top-3: {store.search(3)}')
    print(f'Python/{store.name} guide top-2: {store.search(2, "guide")}')
    store.update()
    print(f'Python/{store.name} after update: {store.search(3)}')


def verify(store):
    require(store.count() == len(DATA['documents']), f'{store.name} document count mismatch')
    require(ids(store.search(3)) == [1, 3, 2], f'{store.name} updated top-k mismatch')
    require(ids(store.search(2, 'guide')) == [1, 6], f'{store.name} filtered top-k mismatch')
    original = next(d for d in DATA['documents'] if d['id'] == DATA['update']['id'])
    metadata = store.document()
    require(metadata['title'] == original['title'] and metadata['category'] == original['category'],
            f'{store.name} metadata changed')
    print(f'Python/{store.name} vector check passed')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('postgres', 'qdrant', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {postgres|qdrant|both}')
    action, target = sys.argv[1:]
    for name in (['postgres', 'qdrant'] if target == 'both' else [target]):
        store = Postgres() if name == 'postgres' else Qdrant()
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
