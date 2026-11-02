\set ON_ERROR_STOP on
DO $$
BEGIN
  IF (SELECT count(*) FROM products) <> 6 THEN RAISE EXCEPTION 'Expected six products'; END IF;
  IF (SELECT doc->>'name' FROM products WHERE id = 'p001') <> 'Trail Jacket' THEN
    RAISE EXCEPTION 'Product lookup mismatch';
  END IF;
  IF (SELECT array_agg(id ORDER BY id) FROM products WHERE doc->'attributes' @> '{"color":"blue","waterproof":true}'::jsonb) <> ARRAY['p001','p003','p005'] THEN
    RAISE EXCEPTION 'Nested filter mismatch';
  END IF;
  IF (SELECT doc #>> '{attributes,waterproof}' FROM products WHERE id='p002') <> 'true' THEN
    RAISE EXCEPTION 'Partial update mismatch';
  END IF;
  IF EXISTS (
    SELECT 1 FROM (
      SELECT doc->>'category' AS category, count(*) AS n, sum((doc->>'price_cents')::integer) AS total
      FROM products GROUP BY doc->>'category'
    ) AS actual
    FULL JOIN (VALUES ('apparel', 2::bigint, 22800::bigint), ('footwear', 2, 24800), ('gear', 2, 19800))
      AS expected(category, n, total) USING (category)
    WHERE actual.n IS DISTINCT FROM expected.n OR actual.total IS DISTINCT FROM expected.total
  ) THEN RAISE EXCEPTION 'Category aggregation mismatch'; END IF;
END $$;
SELECT 'PostgreSQL documents check passed' AS result;
