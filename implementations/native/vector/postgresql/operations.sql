\set ON_ERROR_STOP on
-- Exact top-3 cosine nearest neighbors.
SELECT id, round((embedding <=> '[1,0,0]')::numeric, 6) AS cosine_distance
FROM documents ORDER BY embedding <=> '[1,0,0]', id LIMIT 3;
-- Exact top-2 among guides.
SELECT id, round((embedding <=> '[1,0,0]')::numeric, 6) AS cosine_distance
FROM documents WHERE category = 'guide' ORDER BY embedding <=> '[1,0,0]', id LIMIT 2;
-- Replace one vector; metadata is unchanged.
UPDATE documents SET embedding = '[0.95,0.05,0]' WHERE id = 3;
-- Top-3 after update.
SELECT id, round((embedding <=> '[1,0,0]')::numeric, 6) AS cosine_distance
FROM documents ORDER BY embedding <=> '[1,0,0]', id LIMIT 3;
