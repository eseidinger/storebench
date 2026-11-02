\set ON_ERROR_STOP on
DO $$
DECLARE
  ids integer[];
BEGIN
  IF (SELECT count(*) FROM documents) <> 6 THEN RAISE EXCEPTION 'Expected six documents'; END IF;
  SELECT array_agg(id ORDER BY rank) INTO ids FROM (
    SELECT id, row_number() OVER (ORDER BY embedding <=> '[1,0,0]', id) AS rank
    FROM documents
  ) q WHERE rank <= 3;
  IF ids <> ARRAY[1,3,2] THEN RAISE EXCEPTION 'Updated top-k mismatch: %', ids; END IF;
  SELECT array_agg(id ORDER BY rank) INTO ids FROM (
    SELECT id, row_number() OVER (ORDER BY embedding <=> '[1,0,0]', id) AS rank
    FROM documents WHERE category = 'guide'
  ) q WHERE rank <= 2;
  IF ids <> ARRAY[1,6] THEN RAISE EXCEPTION 'Filtered top-k mismatch: %', ids; END IF;
  IF (SELECT category FROM documents WHERE id = 3) <> 'article' THEN RAISE EXCEPTION 'Metadata changed'; END IF;
END $$;
SELECT 'PostgreSQL vector check passed' AS result;
