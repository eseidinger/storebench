#!/usr/bin/env python3
"""Direct PostgreSQL and OpenSearch clients for the full-text search contract."""
import json
import os
import sys
from pathlib import Path

import psycopg
from opensearchpy import OpenSearch

ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / 'workloads/search/articles.json').read_text())
MAPPING = json.loads((ROOT / 'implementations/native/search/opensearch/mapping.json').read_text())
INDEX = 'storebench_articles'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Postgres:
    name = 'PostgreSQL'

    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv('STOREBENCH_SEARCH_PG_HOST', '127.0.0.1'),
            port=int(os.getenv('STOREBENCH_SEARCH_PG_PORT', '5435')),
            dbname='storebench', user='storebench', password='storebench_local',
        )

    def close(self):
        self.connection.close()

    def seed(self):
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute('DROP TABLE IF EXISTS articles')
                cursor.execute('''CREATE TABLE articles (
                    id integer PRIMARY KEY, title text NOT NULL, body text NOT NULL, category text NOT NULL,
                    search_vector tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', title), 'A') ||
                        setweight(to_tsvector('english', body), 'B')
                    ) STORED
                )''')
                cursor.executemany('INSERT INTO articles (id, title, body, category) VALUES (%s, %s, %s, %s)',
                    [(a['id'], a['title'], a['body'], a['category']) for a in DATA['articles']])
                cursor.execute('CREATE INDEX articles_search_idx ON articles USING gin (search_vector)')
                cursor.execute('CREATE INDEX articles_category_idx ON articles (category)')
        print(f'Python/PostgreSQL: inserted {len(DATA["articles"])} articles')

    def search(self, category=None):
        sql = '''SELECT id, ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
            FROM articles WHERE search_vector @@ plainto_tsquery('english', %s)'''
        params = [DATA['query'], DATA['query']]
        if category is not None:
            sql += ' AND category = %s'
            params.append(category)
        sql += ' ORDER BY rank DESC, id ASC LIMIT 10'
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def update(self):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE articles SET body = %s WHERE id = %s',
                           (DATA['update']['body'], DATA['update']['id']))
            require(cursor.rowcount == 1, 'PostgreSQL update did not affect one article')
        self.connection.commit()

    def article(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT title, body, category FROM articles WHERE id = %s', (DATA['update']['id'],))
            row = cursor.fetchone()
            require(row is not None, 'PostgreSQL article 5 missing')
            return dict(zip(('title', 'body', 'category'), row))

    def count(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM articles')
            return cursor.fetchone()[0]


class OpenSearchStore:
    name = 'OpenSearch'

    def __init__(self):
        self.client = OpenSearch(
            hosts=[{'host': os.getenv('STOREBENCH_OPENSEARCH_HOST', '127.0.0.1'),
                    'port': int(os.getenv('STOREBENCH_OPENSEARCH_PORT', '9201'))}],
            use_ssl=False,
        )

    def close(self):
        self.client.close()

    def seed(self):
        if self.client.indices.exists(index=INDEX):
            self.client.indices.delete(index=INDEX)
        self.client.indices.create(index=INDEX, body=MAPPING)
        actions = []
        for article in DATA['articles']:
            actions.append({'index': {'_index': INDEX, '_id': article['id']}})
            actions.append({key: article[key] for key in ('title', 'body', 'category')})
        result = self.client.bulk(body=actions, refresh='wait_for')
        require(not result['errors'] and len(result['items']) == len(DATA['articles']),
                f'OpenSearch bulk load failed: {result}')
        print(f'Python/OpenSearch: inserted {len(DATA["articles"])} articles')

    def search(self, category=None):
        query = {'multi_match': {'query': DATA['query'], 'fields': ['title^3', 'body'], 'operator': 'and'}}
        if category is not None:
            query = {'bool': {'must': [query], 'filter': [{'term': {'category': category}}]}}
        body = {'query': query, 'size': 10, 'sort': [{'_score': 'desc'}, {'_id': 'asc'}]}
        result = self.client.search(index=INDEX, body=body)
        return [(int(hit['_id']), hit['_score']) for hit in result['hits']['hits']]

    def update(self):
        result = self.client.update(index=INDEX, id=DATA['update']['id'],
                                    body={'doc': {'body': DATA['update']['body']}}, refresh='wait_for')
        require(result['result'] == 'updated', f'OpenSearch update failed: {result}')

    def article(self):
        return self.client.get(index=INDEX, id=DATA['update']['id'])['_source']

    def count(self):
        return self.client.count(index=INDEX)['count']


def ids(result):
    return [id for id, _ in result]


def run(store):
    before = store.search()
    guide_before = store.search('guide')
    require(ids(before) == [6] and ids(guide_before) == [],
            f'{store.name} before-update results mismatch; seed before run')
    print(f'Python/{store.name} before update: {before}')
    print(f'Python/{store.name} guide before update: {guide_before}')
    store.update()
    after = store.search()
    guide_after = store.search('guide')
    require(ids(after) == [6, 5] and ids(guide_after) == [5],
            f'{store.name} after-update results mismatch')
    print(f'Python/{store.name} after update: {after}')
    print(f'Python/{store.name} guide after update: {guide_after}')


def verify(store):
    require(store.count() == len(DATA['articles']), f'{store.name} article count mismatch')
    require(ids(store.search()) == [6, 5], f'{store.name} ranked results mismatch')
    require(ids(store.search('guide')) == [5], f'{store.name} filtered results mismatch')
    article = store.article()
    original = next(a for a in DATA['articles'] if a['id'] == DATA['update']['id'])
    require(article['title'] == original['title'] and article['category'] == original['category'],
            f'{store.name} title or category changed')
    require(article['body'] == DATA['update']['body'], f'{store.name} body update missing')
    print(f'Python/{store.name} search check passed')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('seed', 'run', 'verify') or sys.argv[2] not in ('postgres', 'opensearch', 'both'):
        raise SystemExit('Usage: main.py {seed|run|verify} {postgres|opensearch|both}')
    action, target = sys.argv[1:]
    for name in (['postgres', 'opensearch'] if target == 'both' else [target]):
        store = Postgres() if name == 'postgres' else OpenSearchStore()
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
