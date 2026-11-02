\set ON_ERROR_STOP on
-- All operations use the same six-product starting dataset.
-- 1. Read one product.
SELECT doc FROM products WHERE id = 'p001';
-- 2. Filter on nested attributes, sorted by stable ID.
SELECT id FROM products WHERE doc->'attributes' @> '{"color":"blue","waterproof":true}'::jsonb ORDER BY id;
-- 3. Change one nested attribute without replacing the other fields.
UPDATE products SET doc = jsonb_set(doc, '{attributes,waterproof}', 'true'::jsonb) WHERE id = 'p002';
-- 4. Aggregate by category after the update.
SELECT doc->>'category' AS category, count(*) AS product_count,
       sum((doc->>'price_cents')::integer) AS total_price_cents
FROM products GROUP BY doc->>'category' ORDER BY category;
