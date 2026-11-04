#!/usr/bin/env python3
"""Generate a deterministic document fixture, logical requests, and reference results."""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "workloads/documents/profiles/storefront-v1.json"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def percentile(values, percent):
    return sorted(values)[(len(values) - 1) * percent // 100]


def validate(profile):
    if profile["profile_version"] != 1 or profile["schema_version"] != 1:
        raise ValueError("Unsupported profile or schema version")
    if profile["document_count"] < 1000 or profile["request_count"] < 100 or profile["request_count"] % 100:
        raise ValueError("Require at least 1000 documents and a request count divisible by 100")
    if sum(profile["categories"].values()) != 100 or sum(profile["mix_percent"].values()) != 100:
        raise ValueError("Category weights and operation mix must each total 100")
    if set(profile["mix_percent"]) != {f"P{i}" for i in range(1, 9)}:
        raise ValueError("Operation mix must contain P1 through P8")
    if profile["mix_percent"]["P8"]:
        raise ValueError("P8 requests are not supported by this first generator version")
    if not 0 <= profile["optional_absent_percent"] <= 100:
        raise ValueError("Invalid optional field omission rate")
    if profile["payload_bytes"]["min"] < 256 or profile["payload_bytes"]["max"] < profile["payload_bytes"]["min"]:
        raise ValueError("Invalid payload size range")
    if profile["page"]["filter"] not in {item["name"] for item in profile["filters"]}:
        raise ValueError("Page filter is not defined")


def weighted_categories(profile):
    return [category for category, weight in profile["categories"].items() for _ in range(weight)]


def make_product(number, category, rng, min_bytes, max_bytes, optional_absent_percent):
    colors = {"apparel": ["blue", "blue", "blue", "red", "black"],
              "footwear": ["black", "brown", "blue"], "gear": ["green", "blue", "black"]}
    prices = {"apparel": (3000, 20000), "footwear": (5000, 30000), "gear": (500, 15000)}
    stocks = {"apparel": (10, 101), "footwear": (5, 51), "gear": (20, 151)}
    product = {
        "id": f"p{number:06d}", "name": f"{category.title()} Product {number:06d}",
        "category": category, "price_cents": rng.randrange(*prices[category]),
        "stock": rng.randrange(*stocks[category]), "version": 1,
        "attributes": {"color": rng.choice(colors[category]), "waterproof": rng.choice([True, False])},
    }
    if rng.randrange(100) >= optional_absent_percent:
        product["attributes"]["size"] = rng.choice(["S", "M", "L", "XL"])
    if rng.randrange(100) >= optional_absent_percent:
        product["attributes"]["material"] = rng.choice(["cotton", "leather", "nylon"])
    # Repeated domain text makes the payload size realistic enough for transport and rewrite tests.
    phrases = ["Lightweight construction for daily use. ", "Care instructions and product details. ",
               "Available through the seasonal catalog. "]
    target = rng.randrange(min_bytes, max_bytes + 1)
    phrase = rng.choice(phrases)
    product["description"] = ""
    while len(encoded(product)) < target:
        product["description"] += phrase
    while len(encoded(product)) > max_bytes and product["description"]:
        product["description"] = product["description"][:-1]
    if not min_bytes <= len(encoded(product)) <= max_bytes:
        raise ValueError("Cannot fit generated document into payload range")
    return product


def build_catalog(profile):
    rng = random.Random(profile["seed"])
    categories = weighted_categories(profile)
    products = []
    for number in range(1, profile["document_count"] + 1):
        category = rng.choice(categories)
        products.append(make_product(number, category, rng, profile["payload_bytes"]["min"],
                                     profile["payload_bytes"]["max"], profile["optional_absent_percent"]))
    # Explicitly control rare and medium selectivity while retaining generated category correlations.
    gear = [p for p in products if p["category"] == "gear"]
    apparel = [p for p in products if p["category"] == "apparel"]
    if not gear or len(apparel) < profile["document_count"] // 100:
        raise ValueError("Generated category distribution cannot support filters")
    gear[0]["attributes"]["edition"] = "limited"
    for product in apparel[:profile["document_count"] // 100]:
        product["attributes"]["edition"] = "seasonal"
    # Keep all product sizes within the declared class after adding optional edition fields.
    for product in [gear[0], *apparel[:profile["document_count"] // 100]]:
        while len(encoded(product)) > profile["payload_bytes"]["max"]:
            product["description"] = product["description"][:-1]
    return products


def matches(product, query):
    return (product["category"] == query["category"] and
            all(product["attributes"].get(key) == value for key, value in query["attributes"].items()))


def filtered(state, query):
    return sorted((p for p in state.values() if matches(p, query)), key=lambda p: (p["category"], p["id"]))


def summary(state):
    totals = {}
    for product in state.values():
        row = totals.setdefault(product["category"], {"count": 0, "price_cents_sum": 0})
        row["count"] += 1
        row["price_cents_sum"] += product["price_cents"]
    return {key: totals[key] for key in sorted(totals)}


def schedule(profile, catalog):
    rng = random.Random(profile["seed"] + 1)
    state = {p["id"]: json.loads(encoded(p)) for p in catalog}
    queries = {q["name"]: q for q in profile["filters"]}
    ids = [p["id"] for p in catalog]
    hot_ids = ids[:max(1, len(ids) * profile["point_read"]["hot_key_percent"] // 100)]
    operation_codes = []
    for code, weight in profile["mix_percent"].items():
        operation_codes.extend([code] * (profile["request_count"] * weight // 100))
    assert len(operation_codes) == profile["request_count"]
    rng.shuffle(operation_codes)
    requests = []
    next_id = len(ids) + 1
    stock_change_count = 0
    for index, code in enumerate(operation_codes):
        request = {"sequence": index, "operation": code}
        if code == "P1":
            missing = rng.randrange(100) < profile["point_read"]["missing_percent"]
            access_class = "missing" if missing else ("hot" if rng.randrange(100) < profile["point_read"]["hot_percent"] else "uniform")
            key = f"missing-{index}" if missing else rng.choice(hot_ids if access_class == "hot" else ids)
            request.update(id=key, access_class=access_class,
                           expected_sha256=digest(encoded(state[key])) if key in state else None)
        elif code == "P2":
            query = profile["filters"][index % len(profile["filters"])]
            result = filtered(state, query)[:query["limit"]]
            request.update(query=query["name"], category=query["category"], attributes=query["attributes"],
                           limit=query["limit"], expected_ids=[p["id"] for p in result],
                           expected_result_sha256=digest(encoded(result)))
        elif code == "P3":
            page = profile["page"]
            query = queries[page["filter"]]
            rows = filtered(state, query)
            depth = page["depths"][index % len(page["depths"])]
            offset = (depth - 1) * page["limit"]
            cursor = [rows[min(offset, len(rows)) - 1]["category"], rows[min(offset, len(rows)) - 1]["id"]] if offset and rows else None
            result = rows[offset:offset + page["limit"]]
            request.update(query=query["name"], category=query["category"], attributes=query["attributes"],
                           limit=page["limit"], depth=depth, after=cursor, expected_ids=[p["id"] for p in result],
                           expected_result_sha256=digest(encoded(result)))
        elif code == "P4":
            request["expected_totals"] = summary(state)
        elif code == "P5":
            product = make_product(next_id, rng.choice(weighted_categories(profile)), rng,
                                   profile["payload_bytes"]["min"], profile["payload_bytes"]["max"],
                                   profile["optional_absent_percent"])
            state[product["id"]] = product
            request.update(document=product, expected_sha256=digest(encoded(product)))
            next_id += 1
        elif code == "P6":
            key = rng.choice(ids)
            product = state[key]
            old_version = product["version"]
            product["attributes"]["featured"] = not product["attributes"].get("featured", False)
            product["version"] += 1
            request.update(id=key, attribute="featured", value=product["attributes"]["featured"],
                           if_version=old_version, expected_version=product["version"],
                           expected_sha256=digest(encoded(product)))
        elif code == "P7":
            key = rng.choice(ids)
            product = state[key]
            old_version = product["version"]
            delta = 1 if stock_change_count % 2 else -1
            stock_change_count += 1
            if product["stock"] + delta < 0:
                delta = 1
            product["stock"] += delta
            product["version"] += 1
            request.update(id=key, delta=delta, if_version=old_version, expected_stock=product["stock"],
                           expected_version=product["version"], expected_sha256=digest(encoded(product)))
        else:
            raise ValueError(f"Unsupported operation: {code}")
        requests.append(request)
    return requests


def write_jsonl(path, rows):
    with path.open("wb") as stream:
        for row in rows:
            stream.write(encoded(row) + b"\n")
    return {"file": path.name, "sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}


def generate(profile_path, output):
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    validate(profile)
    catalog = build_catalog(profile)
    requests = schedule(profile, catalog)
    output.mkdir(parents=True, exist_ok=True)
    files = {"documents": write_jsonl(output / "documents.jsonl", catalog),
             "requests": write_jsonl(output / "requests.jsonl", requests)}
    sizes = [len(encoded(p)) for p in catalog]
    initial_state = {p["id"]: p for p in catalog}
    hit_counts = {q["name"]: len(filtered(initial_state, q)) for q in profile["filters"]}
    optional_fields = ("size", "material")
    manifest = {
        "profile": profile["name"], "profile_sha256": digest(profile_path.read_bytes()),
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "schema_version": profile["schema_version"], "seed": profile["seed"],
        "reference_semantics": "serial",
        "document_count": len(catalog), "request_count": len(requests),
        "operation_counts": {code: sum(r["operation"] == code for r in requests) for code in profile["mix_percent"]},
        "point_read_classes": dict(sorted(Counter(r["access_class"] for r in requests if r["operation"] == "P1").items())),
        "filter_request_counts": dict(sorted(Counter(r["query"] for r in requests if r["operation"] == "P2").items())),
        "page_depth_counts": dict(sorted(Counter(str(r["depth"]) for r in requests if r["operation"] == "P3").items())),
        "category_counts": dict(sorted(Counter(p["category"] for p in catalog).items())),
        "optional_absent_counts": {field: sum(field not in p["attributes"] for p in catalog) for field in optional_fields},
        "null_value_count": sum(value is None for p in catalog for value in p.values()) +
                            sum(value is None for p in catalog for value in p["attributes"].values()),
        "filter_hit_counts": hit_counts,
        "document_bytes": {"min": min(sizes), "p50": percentile(sizes, 50), "p95": percentile(sizes, 95),
                           "p99": percentile(sizes, 99), "max": max(sizes)},
        "files": files,
    }
    (output / "manifest.json").write_bytes(encoded(manifest) + b"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=ROOT / "results/documents/storefront-v1")
    args = parser.parse_args()
    print(json.dumps(generate(args.profile, args.output), ensure_ascii=False, indent=2))
