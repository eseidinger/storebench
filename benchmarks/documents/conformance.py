#!/usr/bin/env python3
"""Load and replay a generated document workload against PostgreSQL or CouchDB.

This is a serial correctness check, not a timed benchmark. Seed replaces only the
benchmark_products table / benchmark_products CouchDB database.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "results/documents/storefront-v1"
TABLE = "benchmark_products"
DATABASE = "benchmark_products"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_input(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["reference_semantics"] == "serial", "Only serial reference traces are supported")
    result = {}
    for name in ("documents", "requests"):
        info = manifest["files"][name]
        path = directory / info["file"]
        require(path.name == info["file"], f"Invalid {name} filename")
        require(sha256(path.read_bytes()) == info["sha256"], f"{name} checksum mismatch")
        result[name] = [json.loads(line) for line in path.open(encoding="utf-8")]
    require(len(result["documents"]) == manifest["document_count"], "Document count mismatch")
    require(len(result["requests"]) == manifest["request_count"], "Request count mismatch")
    require(all(r["sequence"] == i for i, r in enumerate(result["requests"])), "Request sequence mismatch")
    return result["documents"], result["requests"]


class PostgreSQL:
    name = "postgres"

    def __init__(self):
        self.connection = psycopg.connect(
            host=os.getenv("STOREBENCH_PG_HOST", "127.0.0.1"),
            port=int(os.getenv("STOREBENCH_PG_PORT", "5433")),
            dbname="storebench", user="storebench", password="storebench_local",
            autocommit=True,
        )

    def close(self):
        self.connection.close()

    def seed(self, documents):
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {TABLE}")
                cursor.execute(f"CREATE TABLE {TABLE} (id text PRIMARY KEY, doc jsonb NOT NULL)")
                cursor.executemany(f"INSERT INTO {TABLE} (id, doc) VALUES (%s, %s)",
                                   [(p["id"], Jsonb(p)) for p in documents])
                cursor.execute(f"CREATE INDEX benchmark_products_category_id ON {TABLE} ((doc->>'category'), id)")
                cursor.execute(f"CREATE INDEX benchmark_products_attributes ON {TABLE} USING gin ((doc->'attributes'))")
        return len(documents)

    def point(self, product_id):
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT doc FROM {TABLE} WHERE id = %s", (product_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def filter(self, request):
        after = request.get("after")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT doc FROM {TABLE} WHERE doc->>'category' = %s "
                "AND doc->'attributes' @> %s::jsonb AND (%s::text IS NULL OR id > %s) "
                "ORDER BY id LIMIT %s",
                (request["category"], json.dumps(request["attributes"]),
                 after[1] if after else None, after[1] if after else "", request["limit"]),
            )
            return [row[0] for row in cursor.fetchall()]

    def totals(self):
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT doc->>'category', count(*), sum((doc->>'price_cents')::bigint) "
                           f"FROM {TABLE} GROUP BY 1 ORDER BY 1")
            return {category: {"count": int(count), "price_cents_sum": int(total)}
                    for category, count, total in cursor.fetchall()}

    def create(self, document):
        with self.connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {TABLE} (id, doc) VALUES (%s, %s)",
                           (document["id"], Jsonb(document)))

    def attribute_update(self, request):
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE} SET doc = jsonb_set("
                "jsonb_set(doc, ARRAY['attributes', %s]::text[], %s::jsonb, true), "
                "'{version}', to_jsonb((doc->>'version')::integer + 1), true) "
                "WHERE id = %s AND (doc->>'version')::integer = %s",
                (request["attribute"], json.dumps(request["value"]),
                 request["id"], request["if_version"]),
            )
            require(cursor.rowcount == 1, "Attribute update precondition failed")

    def stock_update(self, request):
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE} SET doc = jsonb_set("
                "jsonb_set(doc, '{stock}', to_jsonb((doc->>'stock')::integer + %s), true), "
                "'{version}', to_jsonb((doc->>'version')::integer + 1), true) "
                "WHERE id = %s AND (doc->>'version')::integer = %s "
                "AND (doc->>'stock')::integer + %s >= 0",
                (request["delta"], request["id"], request["if_version"], request["delta"]),
            )
            require(cursor.rowcount == 1, "Stock update precondition failed")


class CouchDB:
    name = "couchdb"

    def __init__(self):
        self.server = os.getenv("STOREBENCH_COUCH_URL", "http://127.0.0.1:5985").rstrip("/")
        self.auth = "Basic " + base64.b64encode(b"storebench:storebench_local").decode()

    def close(self):
        pass

    def request(self, method, path, body=None, missing_ok=False):
        payload = canonical(body) if body is not None else None
        request = Request(self.server + path, data=payload, method=method,
                          headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"CouchDB HTTP {error.code}: {error.read().decode()}") from error

    def document_path(self, product_id):
        return f"/{DATABASE}/{quote(product_id, safe='')}"

    def seed(self, documents):
        setup = self.request("GET", "/_cluster_setup")
        if setup["state"] != "cluster_finished":
            result = self.request("POST", "/_cluster_setup", {"action": "enable_single_node",
                "bind_address": "0.0.0.0", "username": "storebench", "password": "storebench_local"})
            require(result.get("ok"), f"CouchDB setup failed: {result}")
        self.request("DELETE", f"/{DATABASE}", missing_ok=True)
        self.request("PUT", f"/{DATABASE}")
        for start in range(0, len(documents), 500):
            batch = [{"_id": p["id"], **p} for p in documents[start:start + 500]]
            response = self.request("POST", f"/{DATABASE}/_bulk_docs", {"docs": batch})
            require(len(response) == len(batch) and all("error" not in row for row in response),
                    f"CouchDB bulk insert failed at offset {start}: {response[:3]}")
        self.request("POST", f"/{DATABASE}/_index", {
            "index": {"fields": ["category", "id"]}, "ddoc": "benchmark_category_id",
            "name": "category_id", "type": "json"})
        self.request("PUT", f"/{DATABASE}/_design/catalog", {
            "_id": "_design/catalog", "views": {"category_totals": {
                "map": "function(doc) { if (doc.category && typeof doc.price_cents === 'number') emit(doc.category, doc.price_cents); }",
                "reduce": "_stats"}}})
        return len(documents)

    @staticmethod
    def logical(document):
        if document is None:
            return None
        return {key: value for key, value in document.items() if key not in ("_id", "_rev")}

    def point(self, product_id):
        return self.logical(self.request("GET", self.document_path(product_id), missing_ok=True))

    def filter(self, request):
        selector = {"category": request["category"],
                    "id": {"$gt": request["after"][1]} if request.get("after") else {"$gte": ""}}
        selector.update({f"attributes.{key}": value for key, value in request["attributes"].items()})
        result = self.request("POST", f"/{DATABASE}/_find", {
            "selector": selector, "sort": [{"category": "asc"}, {"id": "asc"}],
            "limit": request["limit"], "use_index": ["benchmark_category_id", "category_id"],
            "allow_fallback": False})
        return [self.logical(doc) for doc in result["docs"]]

    def totals(self):
        result = self.request("GET", f"/{DATABASE}/_design/catalog/_view/category_totals?group=true&update=true")
        return {row["key"]: {"count": row["value"]["count"],
                             "price_cents_sum": row["value"]["sum"]} for row in result["rows"]}

    def create(self, document):
        result = self.request("PUT", self.document_path(document["id"]), {"_id": document["id"], **document})
        require(result.get("ok"), "CouchDB create failed")

    def _change(self, request, field, value):
        document = self.request("GET", self.document_path(request["id"]))
        require(document["version"] == request["if_version"], "CouchDB update precondition failed")
        if field == "stock":
            stock = document["stock"] + value
            require(stock >= 0, "Negative stock")
            document["stock"] = stock
        else:
            document["attributes"][field] = value
        document["version"] += 1
        result = self.request("PUT", self.document_path(request["id"]), document)
        require(result.get("ok"), "CouchDB update failed")

    def attribute_update(self, request):
        self._change(request, request["attribute"], request["value"])

    def stock_update(self, request):
        self._change(request, "stock", request["delta"])


def execute(store, request):
    """Execute one logical operation; returned reads are fully decoded by the client."""
    code = request["operation"]
    if code == "P1":
        return store.point(request["id"])
    if code in ("P2", "P3"):
        return store.filter(request)
    if code == "P4":
        return store.totals()
    if code == "P5":
        store.create(request["document"])
        return None
    if code == "P6":
        store.attribute_update(request)
        return None
    if code == "P7":
        store.stock_update(request)
        return None
    raise RuntimeError(f"Unsupported operation {code}")


def verify(store, request, result):
    """Check the serial oracle after the operation; writes require a read-back."""
    code = request["operation"]
    if code == "P1":
        require((sha256(canonical(result)) if result else None) == request["expected_sha256"],
                "Point read mismatch")
    elif code in ("P2", "P3"):
        require([p["id"] for p in result] == request["expected_ids"], "Filtered IDs/order mismatch")
        require(sha256(canonical(result)) == request["expected_result_sha256"],
                "Filtered document mismatch")
    elif code == "P4":
        require(result == request["expected_totals"], "Category totals mismatch")
    elif code in ("P5", "P6", "P7"):
        product_id = request["document"]["id"] if code == "P5" else request["id"]
        require(sha256(canonical(store.point(product_id))) == request["expected_sha256"],
                f"{code} document mismatch")
    else:
        raise RuntimeError(f"Unsupported operation {code}")


def replay(store, requests):
    counts = {}
    for request in requests:
        code = request["operation"]
        try:
            verify(store, request, execute(store, request))
        except Exception as error:
            raise RuntimeError(f"{store.name} sequence {request['sequence']} {code}: {error}") from error
        counts[code] = counts.get(code, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "replay", "all"))
    parser.add_argument("--store", choices=("postgres", "couchdb", "both"), default="both")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    documents, requests = load_input(args.input)
    targets = ("postgres", "couchdb") if args.store == "both" else (args.store,)
    for target in targets:
        store = PostgreSQL() if target == "postgres" else CouchDB()
        try:
            if args.action in ("seed", "all"):
                print(f"{target}: seeded {store.seed(documents)} documents", flush=True)
            if args.action in ("replay", "all"):
                counts = replay(store, requests)
                print(f"{target}: verified {len(requests)} requests {json.dumps(counts, sort_keys=True)}", flush=True)
        finally:
            store.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, psycopg.Error) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
