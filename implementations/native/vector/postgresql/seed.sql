\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS vector;
BEGIN;
DROP TABLE IF EXISTS documents;
CREATE TABLE documents (id integer PRIMARY KEY, title text NOT NULL, category text NOT NULL, embedding vector(3) NOT NULL);
INSERT INTO documents VALUES (1, 'Vector search', 'guide', '[1.0,0.0,0.0]');
INSERT INTO documents VALUES (2, 'Similarity search', 'article', '[0.9,0.1,0.0]');
INSERT INTO documents VALUES (3, 'Database indexes', 'article', '[0.0,1.0,0.0]');
INSERT INTO documents VALUES (4, 'Relational queries', 'guide', '[0.0,0.9,0.1]');
INSERT INTO documents VALUES (5, 'Object storage', 'article', '[0.0,0.0,1.0]');
INSERT INTO documents VALUES (6, 'Hybrid search', 'guide', '[0.7,0.0,0.7]');
CREATE INDEX documents_category_idx ON documents (category);
COMMIT;
