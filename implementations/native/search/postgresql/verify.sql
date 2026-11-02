\set ON_ERROR_STOP on
DO $$
DECLARE ids integer[];
BEGIN
  IF (SELECT count(*) FROM articles) <> 6 THEN RAISE EXCEPTION 'Expected six articles'; END IF;
  SELECT array_agg(id ORDER BY rank DESC, id) INTO ids FROM (
    SELECT id, ts_rank(search_vector, plainto_tsquery('english', 'vector indexing')) AS rank
    FROM articles WHERE search_vector @@ plainto_tsquery('english', 'vector indexing')
  ) q;
  IF ids <> ARRAY[6,5] THEN RAISE EXCEPTION 'Ranked results mismatch: %', ids; END IF;
  SELECT array_agg(id ORDER BY id) INTO ids FROM articles WHERE category = 'guide'
    AND search_vector @@ plainto_tsquery('english', 'vector indexing');
  IF ids <> ARRAY[5] THEN RAISE EXCEPTION 'Filtered results mismatch: %', ids; END IF;
  IF (SELECT title FROM articles WHERE id = 5) <> 'Storage overview' THEN RAISE EXCEPTION 'Title changed'; END IF;
END $$;
SELECT 'PostgreSQL search check passed' AS result;
