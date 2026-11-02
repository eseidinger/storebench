\set ON_ERROR_STOP on
BEGIN;
DROP TABLE IF EXISTS articles;
CREATE TABLE articles (
  id integer PRIMARY KEY,
  title text NOT NULL,
  body text NOT NULL,
  category text NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', title), 'A') ||
    setweight(to_tsvector('english', body), 'B')
  ) STORED
);
INSERT INTO articles (id, title, body, category) VALUES (1, 'Vector search guide', 'Find similar documents with embeddings.', 'guide');
INSERT INTO articles (id, title, body, category) VALUES (2, 'Search operations', 'Full text search queries use tokens.', 'guide');
INSERT INTO articles (id, title, body, category) VALUES (3, 'Database indexing', 'Indexes speed up database filters.', 'article');
INSERT INTO articles (id, title, body, category) VALUES (4, 'Graph traversal', 'Explore package dependency paths.', 'article');
INSERT INTO articles (id, title, body, category) VALUES (5, 'Storage overview', 'Store and retrieve documents.', 'guide');
INSERT INTO articles (id, title, body, category) VALUES (6, 'Vector indexing', 'Approximate nearest neighbor indexes for embeddings.', 'article');
CREATE INDEX articles_search_idx ON articles USING gin (search_vector);
CREATE INDEX articles_category_idx ON articles (category);
COMMIT;
