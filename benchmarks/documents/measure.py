#!/usr/bin/env python3
"""One serial, direct-client document measurement with per-operation artifacts.

This is a pilot latency measurement. It does not establish sustainable throughput
or a store ranking: no concurrent load, rate control, or resource sampler exists.
"""
import argparse
import hashlib
import json
import platform
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

if __package__:
    from .conformance import (CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, execute,
                              load_input, verify)
else:
    from conformance import (CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, execute,
                             load_input, verify)

ROOT = Path(__file__).resolve().parents[2]
READ_CODES = {"P1", "P2", "P3", "P4"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * percent + 99) // 100 - 1)]


def group_name(request):
    code = request["operation"]
    if code == "P1":
        return f"P1:{request['access_class']}"
    if code == "P2":
        return f"P2:{request['query']}"
    if code == "P3":
        return f"P3:depth-{request['depth']}"
    return code


def result_size(request, result):
    if request["operation"] == "P1":
        return (1 if result is not None else 0, len(canonical(result)) if result is not None else 0)
    if request["operation"] in ("P2", "P3"):
        return len(result), len(canonical(result))
    if request["operation"] == "P4":
        return len(result), len(canonical(result))
    return 0, None  # Write acknowledgments are not represented as logical documents.


def store_version(store):
    if store.name == "postgres":
        with store.connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            return cursor.fetchone()[0]
    return store.request("GET", "/")["version"]


def warmup(store, requests, count):
    if not count:
        return 0
    reads = [request for request in requests if request["operation"] in READ_CODES]
    if not reads:
        raise ValueError("No read requests available for warmup")
    # Exercise the view and Mango/SQL index before timing the mixed trace.
    first_filter = next((r for r in reads if r["operation"] == "P2"), None)
    first_summary = next((r for r in reads if r["operation"] == "P4"), None)
    leading = [r for r in (first_filter, first_summary) if r is not None]
    selected = (leading + reads * ((count // len(reads)) + 2))[:count]
    for request in selected:
        execute(store, request)
    return len(selected)


def write_json(path, value):
    path.write_bytes(canonical(value) + b"\n")


def summarize(records):
    groups = defaultdict(list)
    errors = defaultdict(int)
    for row in records:
        if row["status"] == "ok":
            groups[row["group"]].append(row["elapsed_ns"])
        else:
            errors[row["group"]] += 1
    return {group: {
        "count": len(groups[group]), "errors": errors[group],
        "p50_ns": percentile(groups[group], 50) if groups[group] else None,
        "p95_ns": percentile(groups[group], 95) if groups[group] else None,
        "p99_ns": percentile(groups[group], 99) if groups[group] else None,
        "min_ns": min(groups[group]) if groups[group] else None,
        "max_ns": max(groups[group]) if groups[group] else None,
    } for group in sorted(groups.keys() | errors.keys())}


def measure(store, requests, operations_path):
    records = []
    with operations_path.open("wb") as stream:
        for request in requests:
            started_utc = utc_now()
            started_ns = time.perf_counter_ns()
            elapsed_ns = None
            try:
                result = execute(store, request)
                elapsed_ns = time.perf_counter_ns() - started_ns
                # Correctness and logical-size accounting occur outside elapsed_ns.
                check_started_ns = time.perf_counter_ns()
                verify(store, request, result)
                validation_ns = time.perf_counter_ns() - check_started_ns
                count, size = result_size(request, result)
                row = {"sequence": request["sequence"], "operation": request["operation"],
                       "group": group_name(request), "start_utc": started_utc,
                       "elapsed_ns": elapsed_ns, "validation_ns": validation_ns,
                       "result_count": count, "logical_result_bytes": size, "status": "ok"}
            except Exception as error:
                if elapsed_ns is None:
                    elapsed_ns = time.perf_counter_ns() - started_ns
                row = {"sequence": request["sequence"], "operation": request["operation"],
                       "group": group_name(request), "start_utc": started_utc,
                       "elapsed_ns": elapsed_ns, "status": "error", "error": str(error)}
                records.append(row)
                stream.write(canonical(row) + b"\n")
                stream.flush()
                raise RuntimeError(f"sequence {request['sequence']} {request['operation']}: {error}") from error
            records.append(row)
            stream.write(canonical(row) + b"\n")
    return records


def run(args):
    documents, requests = load_input(args.input)
    input_manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    output = args.output or (ROOT / "results/documents/runs" /
                              f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{args.store}-{uuid.uuid4().hex[:8]}")
    output.mkdir(parents=True, exist_ok=False)
    store = None
    manifest = {
        "kind": "serial-direct-client-pilot", "store": args.store,
        "client": "python", "python_version": platform.python_version(),
        "psycopg_version": psycopg.__version__ if args.store == "postgres" else None,
        "host_platform": platform.platform(),
        "input_manifest_sha256": sha256_file(args.input / "manifest.json"),
        "input_profile": input_manifest["profile"],
        "input_files": input_manifest["files"],
        "runner_sha256": sha256_file(Path(__file__)),
        "conformance_sha256": sha256_file(Path(__file__).with_name("conformance.py")),
        "warmup_requested": args.warmup_requests,
        "concurrency": 1, "rate_control": False, "resource_metrics": False,
        "validation_outside_elapsed_ns": True,
        "started_utc": utc_now(), "status": "running",
    }
    records = []
    try:
        store = PostgreSQL() if args.store == "postgres" else CouchDB()
        manifest["store_version"] = store_version(store)
        setup_started = time.perf_counter_ns()
        manifest["seeded_documents"] = store.seed(documents)
        manifest["setup_ns"] = time.perf_counter_ns() - setup_started
        warm_started = time.perf_counter_ns()
        manifest["warmup_completed"] = warmup(store, requests, args.warmup_requests)
        manifest["warmup_ns"] = time.perf_counter_ns() - warm_started
        manifest["measure_started_utc"] = utc_now()
        measure_started = time.perf_counter_ns()
        records = measure(store, requests, output / "operations.jsonl")
        manifest["measure_wall_ns"] = time.perf_counter_ns() - measure_started
        manifest["measure_finished_utc"] = utc_now()
        manifest["status"] = "passed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        if (output / "operations.jsonl").exists():
            records = [json.loads(line) for line in (output / "operations.jsonl").open()]
        raise
    finally:
        if store is not None:
            store.close()
        manifest["finished_utc"] = utc_now()
        manifest["recorded_requests"] = len(records)
        manifest["completed_requests"] = sum(row["status"] == "ok" for row in records)
        write_json(output / "summary.json", summarize(records))
        manifest["artifacts"] = {name: sha256_file(output / name) for name in
                                 ("operations.jsonl", "summary.json") if (output / name).exists()}
        write_json(output / "manifest.json", manifest)
    return output, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("postgres", "couchdb"), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warmup-requests", type=int, default=100)
    args = parser.parse_args()
    if args.warmup_requests < 0:
        parser.error("--warmup-requests must not be negative")
    output, manifest = run(args)
    print(f"{args.store}: {manifest['status']}, {manifest['completed_requests']} requests; artifacts: {output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, psycopg.Error) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
