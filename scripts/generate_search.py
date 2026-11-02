#!/usr/bin/env python3
"""Generate PostgreSQL SQL and OpenSearch bulk NDJSON from one article fixture."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'workloads/search/articles.json').read_text())
articles = data['articles']
assert data['language'] == 'english'
assert len({a['id'] for a in articles}) == len(articles)

def quote(value):
    return "'" + value.replace("'", "''") + "'"

sql = [r'\set ON_ERROR_STOP on', 'BEGIN;', 'DROP TABLE IF EXISTS articles;', '''CREATE TABLE articles (
  id integer PRIMARY KEY,
  title text NOT NULL,
  body text NOT NULL,
  category text NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', title), 'A') ||
    setweight(to_tsvector('english', body), 'B')
  ) STORED
);''']
for a in articles:
    sql.append(f"INSERT INTO articles (id, title, body, category) VALUES ({a['id']}, {quote(a['title'])}, {quote(a['body'])}, {quote(a['category'])});")
sql += ['CREATE INDEX articles_search_idx ON articles USING gin (search_vector);',
        'CREATE INDEX articles_category_idx ON articles (category);', 'COMMIT;']
(root / 'implementations/native/search/postgresql/seed.sql').write_text('\n'.join(sql) + '\n')
lines = []
for article in articles:
    lines.append(json.dumps({'index': {'_id': str(article['id'])}}, separators=(',', ':')))
    lines.append(json.dumps({key: article[key] for key in ('title', 'body', 'category')}, separators=(',', ':')))
(root / 'implementations/native/search/opensearch/bulk.ndjson').write_text('\n'.join(lines) + '\n')
