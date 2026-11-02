\set ON_ERROR_STOP on
-- Two-term AND query. Rank title terms above body terms.
SELECT id, round(ts_rank(search_vector, plainto_tsquery('english', 'vector indexing'))::numeric, 6) AS rank
FROM articles WHERE search_vector @@ plainto_tsquery('english', 'vector indexing')
ORDER BY rank DESC, id LIMIT 10;
-- Same query with a category filter before the update.
SELECT id FROM articles WHERE category = 'guide'
AND search_vector @@ plainto_tsquery('english', 'vector indexing') ORDER BY id;
-- Add both terms to article 5's body.
UPDATE articles SET body = 'Vector indexing helps find similar documents.' WHERE id = 5;
-- Updated article becomes visible; ranking remains explicit.
SELECT id, round(ts_rank(search_vector, plainto_tsquery('english', 'vector indexing'))::numeric, 6) AS rank
FROM articles WHERE search_vector @@ plainto_tsquery('english', 'vector indexing')
ORDER BY rank DESC, id LIMIT 10;
SELECT id FROM articles WHERE category = 'guide'
AND search_vector @@ plainto_tsquery('english', 'vector indexing') ORDER BY id;
