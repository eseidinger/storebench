\set ON_ERROR_STOP on
SELECT key, octet_length(data) AS size, content_type, owner_name FROM blobs ORDER BY key;
SELECT octet_length(data) AS full_size, md5(data) AS full_md5 FROM blobs WHERE key = 'images/pattern.bin';
SELECT octet_length(substring(data FROM 101 FOR 100)) AS range_size, md5(substring(data FROM 101 FOR 100)) AS range_md5 FROM blobs WHERE key = 'images/pattern.bin';
UPDATE blobs SET data = decode('557064617465642053746f726542656e6368210a', 'hex'), content_type = 'text/plain', owner_name = 'storebench' WHERE key = 'notes/hello.txt';
DELETE FROM blobs WHERE key = 'empty.bin';
SELECT key, octet_length(data) AS size FROM blobs ORDER BY key;
