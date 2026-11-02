#!/usr/bin/env python3
"""Generate native PostgreSQL and Qdrant seed files from the canonical fixture."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'workloads/vector/documents.json').read_text())
docs = data['documents']
assert data['dimension'] == 3 and data['distance'] == 'Cosine'
assert len({item['id'] for item in docs}) == len(docs)
assert all(len(item['vector']) == data['dimension'] and any(item['vector']) for item in docs)

sql = [r'\set ON_ERROR_STOP on', 'CREATE EXTENSION IF NOT EXISTS vector;', 'BEGIN;',
       'DROP TABLE IF EXISTS documents;',
       'CREATE TABLE documents (id integer PRIMARY KEY, title text NOT NULL, category text NOT NULL, embedding vector(3) NOT NULL);']
for item in docs:
    title = item['title'].replace("'", "''")
    category = item['category'].replace("'", "''")
    vector = json.dumps(item['vector'], separators=(',', ':'))
    sql.append(f"INSERT INTO documents VALUES ({item['id']}, '{title}', '{category}', '{vector}');")
sql += ['CREATE INDEX documents_category_idx ON documents (category);', 'COMMIT;']
(root / 'implementations/native/vector/postgresql/seed.sql').write_text('\n'.join(sql) + '\n')
points = [{'id': item['id'], 'vector': item['vector'], 'payload': {'title': item['title'], 'category': item['category']}} for item in docs]
(root / 'implementations/native/vector/qdrant/points.json').write_text(json.dumps({'points': points}, indent=2) + '\n')
