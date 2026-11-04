#!/usr/bin/env python3
"""Open-loop concurrent P5-P7 document writes with bounded CAS retries and final-state checks."""
import argparse
import copy
import hashlib
import json
import math
import platform
import random
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

if __package__:
    from .conformance import CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, load_input
    from .load import ClientPool, derive_read_requests, prepare_read_paths, write_jsonl
    from .measure import percentile, store_version, utc_now, write_json
else:
    from conformance import CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, load_input
    from load import ClientPool, derive_read_requests, prepare_read_paths, write_jsonl
    from measure import percentile, store_version, utc_now, write_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = ROOT / "workloads/documents/profiles/catalog-maintenance-write-v1.json"
WRITE_CODES = ("P5", "P6", "P7")
TECHNICAL_FAILURES = {"dropped", "conflict_exhausted", "error"}


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate_profile(profile, documents):
    if profile.get("version") != 1 or not isinstance(profile.get("seed"), int) or \
       not isinstance(profile.get("name"), str) or not profile["name"]:
        raise ValueError("Write profile requires version 1, a name and an integer seed")
    mix = profile.get("operation_percent")
    if not isinstance(mix, dict) or set(mix) != set(WRITE_CODES) or \
       any(not isinstance(value, int) or value < 0 for value in mix.values()) or sum(mix.values()) != 100:
        raise ValueError("P5-P7 percentages must be nonnegative integers totaling 100")
    count = profile.get("request_count")
    if not isinstance(count, int) or count < 100 or count % 100:
        raise ValueError("request_count must be at least 100 and divisible by 100")
    hot = profile.get("hot_key_count")
    if not isinstance(hot, int) or not 1 <= hot <= len(documents):
        raise ValueError("hot_key_count must be between 1 and the document count")
    for key in ("duplicate_create_percent", "negative_stock_percent"):
        value = profile.get(key)
        if not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError(f"{key} must be an integer percentage")
    for key in ("rate_per_second", "measure_seconds", "latency_target_ms"):
        if not positive(profile.get(key)):
            raise ValueError(f"{key} must be positive")
    for key in ("concurrency", "repetitions", "max_attempts"):
        if not isinstance(profile.get(key), int) or profile[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("warmup_seconds", "retry_backoff_ms"):
        value = profile.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be nonnegative")
    failure = profile.get("max_failure_rate")
    if not isinstance(failure, (int, float)) or not math.isfinite(failure) or not 0 <= failure <= 1:
        raise ValueError("max_failure_rate must be between 0 and 1")
    return profile


def make_requests(profile, documents):
    rng = random.Random(profile["seed"])
    hot_ids = [document["id"] for document in documents[:profile["hot_key_count"]]]
    requests = []
    for _ in range(profile["request_count"] // 100):
        codes = [code for code in WRITE_CODES for _ in range(profile["operation_percent"][code])]
        rng.shuffle(codes)
        for code in codes:
            sequence = len(requests)
            request = {"sequence": sequence, "operation": code}
            if code == "P5":
                duplicate = rng.randrange(100) < profile["duplicate_create_percent"]
                source = documents[sequence % len(documents)]
                document = copy.deepcopy(source)
                document["id"] = hot_ids[0] if duplicate else f"write-{profile['seed']}-{sequence:06d}"
                document["name"] = f"Write workload product {sequence:06d}"
                request.update(document=document, duplicate_expected=duplicate)
            else:
                request["id"] = rng.choice(hot_ids)
                if code == "P6":
                    request.update(attribute="featured", action="toggle")
                else:
                    request["delta"] = -1 if rng.randrange(100) < profile["negative_stock_percent"] else 1
            requests.append(request)
    return requests


def create_once(store, document):
    if isinstance(store, PostgreSQL):
        with store.connection.cursor() as cursor:
            cursor.execute("INSERT INTO benchmark_products (id, doc) VALUES (%s, %s) "
                           "ON CONFLICT DO NOTHING RETURNING id",
                           (document["id"], Jsonb(document)))
            return cursor.fetchone() is not None
    response = store.request("PUT", store.document_path(document["id"]),
                             {"_id": document["id"], **document}, conflict_ok=True)
    return response is not None and response.get("ok") is True


def read_for_cas(store, product_id):
    if isinstance(store, PostgreSQL):
        return store.point(product_id)
    return store.request("GET", store.document_path(product_id))


def cas_once(store, request, current, updated):
    if isinstance(store, CouchDB):
        response = store.request("PUT", store.document_path(request["id"]), updated, conflict_ok=True)
        return response is not None and response.get("ok") is True
    with store.connection.cursor() as cursor:
        if request["operation"] == "P6":
            cursor.execute(
                "UPDATE benchmark_products SET doc = jsonb_set("
                "jsonb_set(doc, '{attributes,featured}', %s::jsonb, true), "
                "'{version}', to_jsonb((doc->>'version')::integer + 1), true) "
                "WHERE id = %s AND (doc->>'version')::integer = %s RETURNING doc",
                (json.dumps(updated["attributes"]["featured"]), request["id"], current["version"]),
            )
        else:
            cursor.execute(
                "UPDATE benchmark_products SET doc = jsonb_set("
                "jsonb_set(doc, '{stock}', to_jsonb((doc->>'stock')::integer + %s), true), "
                "'{version}', to_jsonb((doc->>'version')::integer + 1), true) "
                "WHERE id = %s AND (doc->>'version')::integer = %s "
                "AND (doc->>'stock')::integer + %s >= 0 RETURNING doc",
                (request["delta"], request["id"], current["version"], request["delta"]),
            )
        row = cursor.fetchone()
        if row is None:
            return False
        if row[0] != updated:
            raise RuntimeError(f"{request['operation']} returned an unexpected PostgreSQL document")
        return True


def execute_write(store, request, max_attempts, retry_backoff_ms):
    code = request["operation"]
    if code == "P5":
        created = create_once(store, request["document"])
        if created:
            if request["duplicate_expected"]:
                raise RuntimeError("Existing ID was unexpectedly created")
            actual = store.point(request["document"]["id"])
            if actual != request["document"]:
                raise RuntimeError("Created document was not visible by ID")
            return {"status": "ok", "attempts": 1, "conflicts": 0}
        if not request["duplicate_expected"]:
            raise RuntimeError("Unique create was rejected")
        return {"status": "duplicate_rejected", "attempts": 1, "conflicts": 0}
    conflicts = 0
    for attempt in range(1, max_attempts + 1):
        stored = read_for_cas(store, request["id"])
        if stored is None:
            raise RuntimeError(f"Missing write target {request['id']}")
        current = store.logical(stored) if isinstance(store, CouchDB) else stored
        if code == "P7" and current["stock"] + request["delta"] < 0:
            return {"status": "condition_rejected", "attempts": attempt,
                    "conflicts": conflicts, "observed_stock": current["stock"]}
        updated = copy.deepcopy(stored)
        if code == "P6":
            updated["attributes"]["featured"] = not current["attributes"].get("featured", False)
        else:
            updated["stock"] = current["stock"] + request["delta"]
        updated["version"] = current["version"] + 1
        if cas_once(store, request, current, updated):
            return {"status": "ok", "attempts": attempt, "conflicts": conflicts,
                    "before_version": current["version"], "after_version": updated["version"],
                    "before_stock": current["stock"], "after_stock": updated["stock"]}
        conflicts += 1
        if attempt < max_attempts and retry_backoff_ms:
            time.sleep(retry_backoff_ms / 1000)
    return {"status": "conflict_exhausted", "attempts": max_attempts, "conflicts": conflicts}


class WriteRecorder:
    def __init__(self, stream=None):
        self.stream = stream
        self.lock = threading.Lock()
        self.rows = []

    def add(self, row):
        with self.lock:
            self.rows.append(row)
            if self.stream is not None:
                self.stream.write(canonical(row) + b"\n")

    def summary(self, duration_ns, wall_ns, connections):
        counts = Counter(row["status"] for row in self.rows)
        by_code = defaultdict(list)
        for row in self.rows:
            by_code[row["operation"]].append(row)
        groups = {}
        for code, rows in sorted(by_code.items()):
            times = [row["end_to_end_ns"] for row in rows if row["status"] == "ok"]
            groups[code] = {"offered": len(rows), "completed": sum(row["status"] == "ok" for row in rows),
                            "statuses": dict(sorted(Counter(row["status"] for row in rows).items())),
                            "end_to_end_p50_ns": percentile(times, 50) if times else None,
                            "end_to_end_p95_ns": percentile(times, 95) if times else None,
                            "end_to_end_p99_ns": percentile(times, 99) if times else None}
        success = [row["end_to_end_ns"] for row in self.rows if row["status"] == "ok"]
        offered = len(self.rows)
        return {"planned_duration_ns": duration_ns, "actual_wall_ns": wall_ns,
                "offered": offered, "completed": counts["ok"], "statuses": dict(sorted(counts.items())),
                "technical_failure_rate": sum(counts[status] for status in TECHNICAL_FAILURES) / offered
                if offered else None,
                "conflicts": sum(row.get("conflicts", 0) for row in self.rows),
                "retries": sum(max(0, row.get("attempts", 0) - 1) for row in self.rows),
                "end_to_end_p95_ns": percentile(success, 95) if success else None,
                "completed_within_window": sum(row["status"] == "ok" and
                                               row["finished_offset_ns"] < duration_ns for row in self.rows
                                               if "finished_offset_ns" in row),
                "completed_within_window_per_second": sum(row["status"] == "ok" and
                                                           row["finished_offset_ns"] < duration_ns
                                                           for row in self.rows if "finished_offset_ns" in row)
                * 1e9 / duration_ns,
                "client_connections": connections, "groups": groups}


def run_write_phase(pool, requests, rate, duration_seconds, max_attempts, retry_backoff_ms, recorder):
    duration_ns = int(duration_seconds * 1e9)
    start_ns = time.perf_counter_ns()
    deadline_ns = start_ns + duration_ns

    def worker(slot, request, due_ns):
        started_utc = utc_now()
        started_ns = time.perf_counter_ns()
        try:
            outcome = execute_write(pool.client(), request, max_attempts, retry_backoff_ms)
        except Exception as error:
            outcome = {"status": "error", "error": str(error), "attempts": 0, "conflicts": 0}
        finished_ns = time.perf_counter_ns()
        row = {"slot": slot, "sequence": request["sequence"], "operation": request["operation"],
               "id": request.get("id", request.get("document", {}).get("id")),
               "start_utc": started_utc, "schedule_lag_ns": max(0, started_ns - due_ns),
               "elapsed_ns": finished_ns - started_ns, "end_to_end_ns": finished_ns - due_ns,
               "finished_offset_ns": finished_ns - start_ns, **outcome}
        if request["operation"] == "P7":
            row["delta"] = request["delta"]
        try:
            recorder.add(row)
        finally:
            pool.semaphore.release()

    slot = 0
    while True:
        due_ns = start_ns + int(slot * 1e9 / rate)
        if due_ns >= deadline_ns:
            break
        if slot >= len(requests):
            raise ValueError("Write trace is shorter than the offered phase; increase request_count")
        remaining_ns = due_ns - time.perf_counter_ns()
        if remaining_ns > 0:
            time.sleep(remaining_ns / 1e9)
        request = requests[slot]
        if pool.semaphore.acquire(blocking=False):
            try:
                pool.executor.submit(worker, slot, request, due_ns)
            except Exception:
                pool.semaphore.release()
                raise
        else:
            recorder.add({"slot": slot, "sequence": request["sequence"],
                          "operation": request["operation"],
                          "id": request.get("id", request.get("document", {}).get("id")),
                          "status": "dropped", "attempts": 0, "conflicts": 0,
                          "schedule_lag_ns": max(0, time.perf_counter_ns() - due_ns)})
        slot += 1
    pool.drain()
    return recorder.summary(duration_ns, time.perf_counter_ns() - start_ns, len(pool.clients)), recorder.rows


def verify_final(store, documents, requests, rows):
    if sorted(row["sequence"] for row in rows) != list(range(len(rows))):
        raise RuntimeError("Write outcomes do not cover every offered sequence exactly once")
    initial = {document["id"]: document for document in documents}
    expected = {}
    created = set()
    for row in rows:
        request = requests[row["sequence"]]
        if request["operation"] in ("P6", "P7") or request.get("duplicate_expected"):
            product_id = request.get("id", request.get("document", {}).get("id"))
            expected.setdefault(product_id, copy.deepcopy(initial[product_id]))
        if row["status"] != "ok":
            if row["status"] == "duplicate_rejected" and not request.get("duplicate_expected"):
                raise RuntimeError("Unexpected duplicate rejection")
            if row["status"] == "condition_rejected" and request["operation"] != "P7":
                raise RuntimeError("Unexpected condition rejection")
            if row["status"] == "condition_rejected" and \
               (row.get("observed_stock") is None or
                row["observed_stock"] + request["delta"] >= 0):
                raise RuntimeError("Stock condition was rejected despite sufficient stock")
            continue
        code = request["operation"]
        if code == "P5":
            if request["duplicate_expected"]:
                raise RuntimeError("Duplicate create was accepted")
            product_id = request["document"]["id"]
            expected[product_id] = request["document"]
            created.add(product_id)
        else:
            product = expected[request["id"]]
            if code == "P6":
                product["attributes"]["featured"] = not product["attributes"].get("featured", False)
                if row["after_stock"] != row["before_stock"]:
                    raise RuntimeError("Attribute update changed stock")
            else:
                product["stock"] += request["delta"]
                if row["after_stock"] < 0 or \
                   row["after_stock"] != row["before_stock"] + request["delta"]:
                    raise RuntimeError("Successful stock update has an invalid transition")
            product["version"] += 1
            if row["after_version"] != row["before_version"] + 1:
                raise RuntimeError("Successful update did not increment version once")
    actual = {}
    for product_id, desired in sorted(expected.items()):
        found = store.point(product_id)
        if found != desired:
            raise RuntimeError(f"Final document mismatch for {product_id}")
        actual[product_id] = found
    for request in requests[:len(rows)]:
        if request["operation"] == "P5" and not request["duplicate_expected"] and \
           request["document"]["id"] not in created and store.point(request["document"]["id"]) is not None:
            raise RuntimeError(f"Unacknowledged create is visible: {request['document']['id']}")
    return {"status": "passed", "verified_documents": len(actual),
            "created_documents": len(created),
            "final_state_sha256": hashlib.sha256(canonical(actual)).hexdigest()}


def run(args):
    documents, serial_requests = load_input(args.input)
    fixture_manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    profile_bytes = args.profile.read_bytes()
    profile = validate_profile(json.loads(profile_bytes), documents)
    if fixture_manifest["profile"] != profile["input_profile"]:
        raise ValueError("Write profile does not match the input fixture")
    settings = {key: getattr(args, key) if getattr(args, key) is not None else profile[key]
                for key in ("rate_per_second", "concurrency", "warmup_seconds", "measure_seconds",
                            "repetitions", "max_attempts", "retry_backoff_ms", "latency_target_ms",
                            "max_failure_rate")}
    validate_profile({**profile, **settings}, documents)
    if math.ceil(settings["rate_per_second"] * max(settings["warmup_seconds"],
                                                     settings["measure_seconds"])) > profile["request_count"]:
        raise ValueError("Write trace is shorter than a phase; increase request_count")
    requests = make_requests(profile, documents)
    read_requests = derive_read_requests(documents, serial_requests)
    output = args.output or ROOT / "results/documents/write-runs" / \
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{args.store}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    request_sha = write_jsonl(output / "write-requests.jsonl", requests)
    factory = PostgreSQL if args.store == "postgres" else CouchDB
    manifest = {"kind": "open-loop-concurrent-document-writes", "store": args.store,
                "profile": profile["name"], "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
                "input_manifest_sha256": hashlib.sha256((args.input / "manifest.json").read_bytes()).hexdigest(),
                "write_requests_sha256": request_sha, "write_request_count": len(requests),
                "write_mix": dict(sorted(Counter(r["operation"] for r in requests).items())),
                "settings": settings, "python_version": platform.python_version(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "started_utc": utc_now(), "status": "running", "repetitions": []}
    try:
        for number in range(1, settings["repetitions"] + 1):
            repetition_dir = output / f"repeat-{number:02d}"
            repetition_dir.mkdir()
            phases = {}
            admin = factory()
            try:
                if "store_version" not in manifest:
                    manifest["store_version"] = store_version(admin)
                warmup = None
                if settings["warmup_seconds"]:
                    phases["warmup_started_utc"] = utc_now()
                    admin.seed(documents)
                    prepare_read_paths(admin, read_requests)
                    pool = ClientPool(factory, settings["concurrency"])
                    try:
                        warmup, _ = run_write_phase(pool, requests, settings["rate_per_second"],
                                                    settings["warmup_seconds"], settings["max_attempts"],
                                                    settings["retry_backoff_ms"], WriteRecorder())
                    finally:
                        pool.close()
                    phases["warmup_finished_utc"] = utc_now()
                    if warmup["statuses"].get("error", 0):
                        raise RuntimeError("Write warmup had unexpected errors")
                phases["setup_started_utc"] = utc_now()
                setup_started = time.perf_counter_ns()
                admin.seed(documents)
                setup_ns = time.perf_counter_ns() - setup_started
                phases["setup_finished_utc"] = utc_now()
                phases["prepare_started_utc"] = utc_now()
                preparation, diagnostics = prepare_read_paths(admin, read_requests)
                preparation["storage"] = admin.storage_size()
                phases["prepare_finished_utc"] = utc_now()
                if diagnostics:
                    plans_path = repetition_dir / "query-plans.json"
                    write_json(plans_path, diagnostics)
                    preparation["query_plans_sha256"] = hashlib.sha256(plans_path.read_bytes()).hexdigest()
                pool = ClientPool(factory, settings["concurrency"])
                try:
                    with (repetition_dir / "operations.jsonl").open("wb") as stream:
                        phases["measure_started_utc"] = utc_now()
                        measured, rows = run_write_phase(pool, requests, settings["rate_per_second"],
                                                         settings["measure_seconds"], settings["max_attempts"],
                                                         settings["retry_backoff_ms"], WriteRecorder(stream))
                        phases["measure_finished_utc"] = utc_now()
                finally:
                    pool.close()
                phases["validate_started_utc"] = utc_now()
                validation = verify_final(admin, documents, requests, rows)
                phases["validate_finished_utc"] = utc_now()
                summary = {"repetition": number, "setup_ns": setup_ns, "preparation": preparation,
                           "warmup": warmup, "measure": measured, "validation": validation,
                           "phase_intervals": phases,
                           "status": "passed" if measured["statuses"].get("error", 0) == 0 else "failed"}
                summary["within_provisional_targets"] = (
                    measured["end_to_end_p95_ns"] is not None and
                    measured["end_to_end_p95_ns"] <= settings["latency_target_ms"] * 1e6 and
                    measured["technical_failure_rate"] <= settings["max_failure_rate"])
                write_json(repetition_dir / "summary.json", summary)
                summary["artifacts"] = {name: hashlib.sha256((repetition_dir / name).read_bytes()).hexdigest()
                                        for name in ("operations.jsonl", "summary.json")}
                manifest["repetitions"].append(summary)
                write_json(output / "manifest.json", manifest)
            finally:
                admin.close()
        manifest["status"] = "passed" if all(r["status"] == "passed" for r in manifest["repetitions"]) else "failed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        manifest["finished_utc"] = utc_now()
        write_json(output / "manifest.json", manifest)
    if manifest["status"] != "passed":
        raise RuntimeError(f"Write load had errors; inspect {output / 'manifest.json'}")
    return output, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("postgres", "couchdb"), required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    for flag, kind in (("rate-per-second", float), ("concurrency", int),
                       ("warmup-seconds", float), ("measure-seconds", float),
                       ("repetitions", int), ("max-attempts", int),
                       ("retry-backoff-ms", float), ("latency-target-ms", float),
                       ("max-failure-rate", float)):
        parser.add_argument(f"--{flag}", type=kind)
    args = parser.parse_args()
    try:
        output, manifest = run(args)
    except (OSError, ValueError, RuntimeError, psycopg.Error) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    print(f"{args.store}: {manifest['status']}; artifacts: {output}")


if __name__ == "__main__":
    main()
