"""Deterministic bytes and SQL generation for the blob use case."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'workloads/blob/manifest.json').read_text())

def payload(item):
    if item['kind'] == 'text':
        return item['value'].encode()
    if item['kind'] == 'empty':
        return b''
    if item['kind'] == 'sha256_pattern':
        seed = b'StoreBench blob pattern v1'
        return (hashlib.sha256(seed).digest() * ((item['size'] + 31) // 32))[:item['size']]
    raise ValueError(item['kind'])

def quote(value):
    return "'" + value.replace("'", "''") + "'"

def generate_sql():
    directory = ROOT / 'implementations/native/blob/postgresql'
    seed = [r'\set ON_ERROR_STOP on', 'BEGIN;', 'DROP TABLE IF EXISTS blobs;',
            'CREATE TABLE blobs (key text PRIMARY KEY, data bytea NOT NULL, content_type text NOT NULL, owner_name text NOT NULL);']
    for item in MANIFEST['objects']:
        seed.append(f"INSERT INTO blobs VALUES ({quote(item['key'])}, decode('{payload(item).hex()}', 'hex'), {quote(item['content_type'])}, {quote(item['owner'])});")
    seed.append('COMMIT;')
    (directory / 'seed.sql').write_text('\n'.join(seed) + '\n')
    update = MANIFEST['overwrite']
    span = MANIFEST['range']
    operations = [r'\set ON_ERROR_STOP on',
                  "SELECT key, octet_length(data) AS size, content_type, owner_name FROM blobs ORDER BY key;",
                  f"SELECT octet_length(data) AS full_size, md5(data) AS full_md5 FROM blobs WHERE key = {quote(span['key'])};",
                  f"SELECT octet_length(substring(data FROM {span['start'] + 1} FOR {span['end'] - span['start'] + 1})) AS range_size, md5(substring(data FROM {span['start'] + 1} FOR {span['end'] - span['start'] + 1})) AS range_md5 FROM blobs WHERE key = {quote(span['key'])};",
                  f"UPDATE blobs SET data = decode('{payload(update).hex()}', 'hex'), content_type = {quote(update['content_type'])}, owner_name = {quote(update['owner'])} WHERE key = {quote(update['key'])};",
                  f"DELETE FROM blobs WHERE key = {quote(MANIFEST['delete'])};",
                  'SELECT key, octet_length(data) AS size FROM blobs ORDER BY key;']
    (directory / 'operations.sql').write_text('\n'.join(operations) + '\n')
    remaining = [item for item in MANIFEST['objects'] if item['key'] != MANIFEST['delete']]
    verify = [r'\set ON_ERROR_STOP on', 'DO $$ BEGIN',
              f"IF (SELECT count(*) FROM blobs) <> {len(remaining)} THEN RAISE EXCEPTION 'Blob count mismatch'; END IF;"]
    for item in remaining:
        expected = update if item['key'] == update['key'] else item
        verify.append(f"IF NOT EXISTS (SELECT 1 FROM blobs WHERE key = {quote(item['key'])} AND data = decode('{payload(expected).hex()}', 'hex') AND content_type = {quote(expected['content_type'])} AND owner_name = {quote(expected['owner'])}) THEN RAISE EXCEPTION 'Blob mismatch: {item['key']}'; END IF;")
    verify.append(f"IF (SELECT substring(data FROM {span['start'] + 1} FOR {span['end'] - span['start'] + 1}) FROM blobs WHERE key = {quote(span['key'])}) <> decode('{payload(next(item for item in MANIFEST['objects'] if item['key'] == span['key']))[span['start']:span['end'] + 1].hex()}', 'hex') THEN RAISE EXCEPTION 'Range mismatch'; END IF;")
    verify += ['END $$;', "SELECT 'PostgreSQL blob check passed' AS result;"]
    (directory / 'verify.sql').write_text('\n'.join(verify) + '\n')

if __name__ == '__main__':
    generate_sql()
