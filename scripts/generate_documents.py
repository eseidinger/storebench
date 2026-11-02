#!/usr/bin/env python3
"""Generate identical SQL and mongosh fixtures from the versioned JSON catalog."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
products = json.loads((ROOT / "workloads/documents/products.json").read_text())
assert len({p["id"] for p in products}) == len(products)
output = ROOT / "implementations/native/documents"

sql = [
    "\\set ON_ERROR_STOP on",
    "BEGIN;",
    "DROP TABLE IF EXISTS products;",
    "CREATE TABLE products (id text PRIMARY KEY, doc jsonb NOT NULL);",
]
for product in products:
    payload = json.dumps(product, separators=(",", ":"))
    sql.append(f"INSERT INTO products (id, doc) VALUES ('{product['id']}', '{payload}'::jsonb);")
sql += [
    "CREATE INDEX products_category_idx ON products ((doc->>'category'));",
    "CREATE INDEX products_attributes_gin_idx ON products USING gin ((doc->'attributes'));",
    "COMMIT;",
]
(output / "postgresql/seed.sql").write_text("\n".join(sql) + "\n")

js = [
    "const database = db.getSiblingDB('storebench');",
    "database.products.drop();",
    "database.products.insertMany(" + json.dumps(products, separators=(",", ":")) + ");",
    "database.products.createIndex({ id: 1 }, { unique: true });",
    "database.products.createIndex({ category: 1 });",
    "database.products.createIndex({ attributes: 1 });",
    "print('Inserted ' + database.products.countDocuments({}) + ' products');",
]
(output / "mongodb/seed.js").write_text("\n".join(js) + "\n")
