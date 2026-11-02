#!/usr/bin/env python3
"""RustFS S3 operations through the AWS CLI, with byte-level verification."""
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from blob_data import MANIFEST, payload

ENDPOINT = 'http://127.0.0.1:9002'
BUCKET = MANIFEST['bucket']
ENV = dict(os.environ, AWS_ACCESS_KEY_ID='storebench_local',
           AWS_SECRET_ACCESS_KEY='storebench_secret_local', AWS_DEFAULT_REGION='us-east-1')

def aws(*args, check=True):
    result = subprocess.run(['aws', '--endpoint-url', ENDPOINT, 's3api', *args],
                            env=ENV, capture_output=True, text=True)
    if check and result.returncode:
        raise SystemExit(f'aws s3api {args[0]} failed: {result.stderr.strip()}')
    return result

def upload(item, directory):
    file = Path(directory) / 'object.bin'
    file.write_bytes(payload(item))
    aws('put-object', '--bucket', BUCKET, '--key', item['key'], '--body', str(file),
        '--content-type', item['content_type'], '--metadata', f"owner={item['owner']}")

def fetch(key, directory, byte_range=None):
    file = Path(directory) / 'download.bin'
    args = ['get-object', '--bucket', BUCKET, '--key', key]
    if byte_range is not None:
        args += ['--range', f'bytes={byte_range[0]}-{byte_range[1]}']
    aws(*args, str(file))
    return file.read_bytes()

action = sys.argv[1] if len(sys.argv) > 1 else ''
if action == 'wait':
    for _ in range(60):
        try:
            with urlopen(ENDPOINT + '/health', timeout=2) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit('RustFS did not become ready within 60 seconds')
elif action == 'seed':
    if aws('head-bucket', '--bucket', BUCKET, check=False).returncode != 0:
        aws('create-bucket', '--bucket', BUCKET)
    listed = aws('list-objects-v2', '--bucket', BUCKET, '--query', 'Contents[].Key', '--output', 'text').stdout.split()
    for key in listed:
        aws('delete-object', '--bucket', BUCKET, '--key', key)
    with tempfile.TemporaryDirectory() as directory:
        for item in MANIFEST['objects']:
            upload(item, directory)
    print('RustFS: uploaded', len(MANIFEST['objects']), 'objects')
elif action == 'run':
    with tempfile.TemporaryDirectory() as directory:
        for item in MANIFEST['objects']:
            head = aws('head-object', '--bucket', BUCKET, '--key', item['key'])
            print('head:', item['key'], __import__('json').loads(head.stdout)['ContentLength'])
            actual = fetch(item['key'], directory)
            print('get:', item['key'], len(actual), hashlib.sha256(actual).hexdigest())
        span = MANIFEST['range']
        actual = fetch(span['key'], directory, (span['start'], span['end']))
        print('range:', len(actual), hashlib.sha256(actual).hexdigest())
        upload(MANIFEST['overwrite'], directory)
        aws('delete-object', '--bucket', BUCKET, '--key', MANIFEST['delete'])
elif action == 'verify':
    with tempfile.TemporaryDirectory() as directory:
        expected = {item['key']: item for item in MANIFEST['objects'] if item['key'] != MANIFEST['delete']}
        expected[MANIFEST['overwrite']['key']] = MANIFEST['overwrite']
        for key, item in expected.items():
            if fetch(key, directory) != payload(item):
                raise SystemExit(f'Object bytes mismatch: {key}')
            head = aws('head-object', '--bucket', BUCKET, '--key', key).stdout
            import json
            metadata = json.loads(head)
            if metadata['ContentLength'] != len(payload(item)) or metadata['ContentType'] != item['content_type'] or metadata['Metadata'].get('owner') != item['owner']:
                raise SystemExit(f'Object metadata mismatch: {key}')
        span = MANIFEST['range']
        ranged = fetch(span['key'], directory, (span['start'], span['end']))
        source = next(item for item in MANIFEST['objects'] if item['key'] == span['key'])
        if ranged != payload(source)[span['start']:span['end'] + 1]:
            raise SystemExit('Range read mismatch')
        if aws('head-object', '--bucket', BUCKET, '--key', MANIFEST['delete'], check=False).returncode == 0:
            raise SystemExit('Deleted object still exists')
        print('RustFS blob check passed')
else:
    raise SystemExit('Usage: blob_rustfs.py {wait|seed|run|verify}')
