\set ON_ERROR_STOP on
BEGIN;
DROP TABLE IF EXISTS products;
CREATE TABLE products (id text PRIMARY KEY, doc jsonb NOT NULL);
INSERT INTO products (id, doc) VALUES ('p001', '{"id":"p001","name":"Trail Jacket","category":"apparel","price_cents":12900,"stock":12,"attributes":{"color":"blue","size":"M","waterproof":true}}'::jsonb);
INSERT INTO products (id, doc) VALUES ('p002', '{"id":"p002","name":"City Jacket","category":"apparel","price_cents":9900,"stock":8,"attributes":{"color":"black","size":"L","waterproof":false}}'::jsonb);
INSERT INTO products (id, doc) VALUES ('p003', '{"id":"p003","name":"Hiking Boots","category":"footwear","price_cents":15900,"stock":5,"attributes":{"color":"blue","size":"42","waterproof":true}}'::jsonb);
INSERT INTO products (id, doc) VALUES ('p004', '{"id":"p004","name":"Running Shoes","category":"footwear","price_cents":8900,"stock":20,"attributes":{"color":"red","size":"42","waterproof":false}}'::jsonb);
INSERT INTO products (id, doc) VALUES ('p005', '{"id":"p005","name":"Day Pack","category":"gear","price_cents":7900,"stock":15,"attributes":{"color":"blue","capacity_l":20,"waterproof":true}}'::jsonb);
INSERT INTO products (id, doc) VALUES ('p006', '{"id":"p006","name":"Travel Pack","category":"gear","price_cents":11900,"stock":7,"attributes":{"color":"green","capacity_l":35,"waterproof":false}}'::jsonb);
CREATE INDEX products_category_idx ON products ((doc->>'category'));
CREATE INDEX products_attributes_gin_idx ON products USING gin ((doc->'attributes'));
COMMIT;
