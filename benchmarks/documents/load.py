#!/usr/bin/env python3
"""Open-loop, read-only direct-client load for one document store at a time."""
import argparse
import hashlib
import json
import math
import platform
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg

if __package__:
    from .conformance import (CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, execute,
                              load_input, sha256, verify)
    from .measure import group_name, percentile, result_size, store_version, utc_now, write_json
else:
    from conformance import (CouchDB, DEFAULT_INPUT, PostgreSQL, canonical, execute,
                             load_input, sha256, verify)
    from measure import group_name, percentile, result_size, store_version, utc_now, write_json

ROOT = Path(__file__).resolve().parents[2]
READ_CODES = {"P1", "P2", "P3", "P4"}


def derive_read_requests(documents, requests):
    """Recalculate the serial trace's read expectations for the immutable initial fixture."""
    state = {document["id"]: document for document in documents}
    totals = {}
    for document in documents:
        row = totals.setdefault(document["category"], {"count": 0, "price_cents_sum": 0})
        row["count"] += 1
        row["price_cents_sum"] += document["price_cents"]
    derived = []
    for source in requests:
        if source["operation"] not in READ_CODES:
            continue
        request = dict(source)
        request["sequence"] = len(derived)
        code = request["operation"]
        if code == "P1":
            document = state.get(request["id"])
            request["expected_sha256"] = sha256(canonical(document)) if document is not None else None
        elif code in ("P2", "P3"):
            rows = sorted((document for document in documents
                           if document["category"] == request["category"] and
                           all(document["attributes"].get(key) == value
                               for key, value in request["attributes"].items())),
                          key=lambda document: (document["category"], document["id"]))
            after = request.get("after")
            if after is not None:
                rows = [document for document in rows if [document["category"], document["id"]] > after]
            rows = rows[:request["limit"]]
            request["expected_ids"] = [document["id"] for document in rows]
            request["expected_result_sha256"] = sha256(canonical(rows))
        else:
            request["expected_totals"] = totals
        derived.append(request)
    if not derived or {request["operation"] for request in derived} != READ_CODES:
        raise ValueError("Read-only load requires P1, P2, P3, and P4 requests")
    return derived


def write_jsonl(path, rows):
    with path.open("wb") as stream:
        for row in rows:
            stream.write(canonical(row) + b"\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_read_paths(store, requests):
    """Build lazy indexes/views and verify one request per read group before timing."""
    representatives = {}
    for request in requests:
        representatives.setdefault(group_name(request), request)
    selected = sorted(representatives.values(),
                      key=lambda request: (request["operation"] != "P4", request["operation"],
                                           group_name(request)))
    groups = []
    diagnostics = []
    started = time.perf_counter_ns()
    for request in selected:
        group = group_name(request)
        operation_started = time.perf_counter_ns()
        result = execute(store, request)
        verify(store, request, result)
        groups.append({"group": group, "sequence": request["sequence"],
                       "elapsed_ns": time.perf_counter_ns() - operation_started})
        if isinstance(store, CouchDB) and request["operation"] in ("P2", "P3"):
            explain = store.explain_filter(request)
            index = explain.get("index") or {}
            expected_ddoc, expected_name, _ = store.filter_index(request)
            if index.get("name") != expected_name or \
               index.get("ddoc") != f"_design/{expected_ddoc}":
                raise RuntimeError(f"{group}: unexpected CouchDB index {index}")
            checked_result, stats, warning = store.filter_execution_stats(request)
            verify(store, request, checked_result)
            diagnostics.append({"group": group, "sequence": request["sequence"],
                                "selected_index": index, "covering": explain.get("covering"),
                                "execution_stats": stats, "warning": warning,
                                "explain": explain})
    return {"elapsed_ns": time.perf_counter_ns() - started, "groups": groups}, diagnostics


class Recorder:
    def __init__(self, stream=None):
        self.stream = stream
        self.lock = threading.Lock()
        self.statuses = Counter()
        self.groups = defaultdict(list)
        self.group_errors = Counter()
        self.lags = []
        self.completed_in_window = 0

    def add(self, row, deadline_ns):
        with self.lock:
            self.statuses[row["status"]] += 1
            if row["status"] == "ok":
                self.groups[row["group"]].append((row["elapsed_ns"], row["end_to_end_ns"]))
                if row["finished_offset_ns"] < deadline_ns:
                    self.completed_in_window += 1
            elif row["status"] == "error":
                self.group_errors[row["group"]] += 1
            self.lags.append(row["schedule_lag_ns"])
            if self.stream is not None:
                self.stream.write(canonical(row) + b"\n")

    def summary(self, planned_duration_ns, elapsed_wall_ns, connection_count):
        groups = {}
        for group in sorted(self.groups.keys() | self.group_errors.keys()):
            samples = self.groups[group]
            service = [value[0] for value in samples]
            end_to_end = [value[1] for value in samples]
            groups[group] = {
                "completed": len(samples), "errors": self.group_errors[group],
                "service_p50_ns": percentile(service, 50) if service else None,
                "service_p95_ns": percentile(service, 95) if service else None,
                "service_p99_ns": percentile(service, 99) if service else None,
                "end_to_end_p50_ns": percentile(end_to_end, 50) if end_to_end else None,
                "end_to_end_p95_ns": percentile(end_to_end, 95) if end_to_end else None,
                "end_to_end_p99_ns": percentile(end_to_end, 99) if end_to_end else None,
            }
        offered = sum(self.statuses.values())
        all_end_to_end = [end_to_end for samples in self.groups.values() for _, end_to_end in samples]
        return {
            "planned_duration_ns": planned_duration_ns, "actual_wall_ns": elapsed_wall_ns,
            "offered": offered, "started": offered - self.statuses["dropped"],
            "completed": self.statuses["ok"], "errors": self.statuses["error"],
            "dropped": self.statuses["dropped"],
            "offered_failure_rate": (self.statuses["error"] + self.statuses["dropped"]) / offered
            if offered else None,
            "end_to_end_p95_ns": percentile(all_end_to_end, 95) if all_end_to_end else None,
            "completed_within_window": self.completed_in_window,
            "offered_per_second": offered * 1e9 / planned_duration_ns if planned_duration_ns else None,
            "completed_within_window_per_second": self.completed_in_window * 1e9 / planned_duration_ns
            if planned_duration_ns else None,
            "schedule_lag_p99_ns": percentile(self.lags, 99) if self.lags else None,
            "client_connections": connection_count,
            "groups": groups,
        }


class ClientPool:
    def __init__(self, factory, concurrency):
        self.factory = factory
        self.executor = ThreadPoolExecutor(max_workers=concurrency)
        self.semaphore = threading.Semaphore(concurrency)
        self.local = threading.local()
        self.clients = []
        self.clients_lock = threading.Lock()
        self.concurrency = concurrency

    def client(self):
        if not hasattr(self.local, "client"):
            client = self.factory()
            self.local.client = client
            with self.clients_lock:
                self.clients.append(client)
        return self.local.client

    def drain(self):
        for _ in range(self.concurrency):
            self.semaphore.acquire()
        for _ in range(self.concurrency):
            self.semaphore.release()

    def close(self):
        self.executor.shutdown(wait=True)
        for client in self.clients:
            client.close()


def run_phase(pool, requests, rate, duration_seconds, recorder):
    duration_ns = int(duration_seconds * 1e9)
    start_ns = time.perf_counter_ns()
    deadline_ns = start_ns + duration_ns

    def worker(slot, request, due_ns):
        started_utc = utc_now()
        started_ns = time.perf_counter_ns()
        elapsed_ns = None
        try:
            result = execute(pool.client(), request)
            finished_ns = time.perf_counter_ns()
            elapsed_ns = finished_ns - started_ns
            validation_started = time.perf_counter_ns()
            verify(pool.client(), request, result)
            validation_ns = time.perf_counter_ns() - validation_started
            count, size = result_size(request, result)
            row = {"slot": slot, "sequence": request["sequence"], "operation": request["operation"],
                   "group": group_name(request), "status": "ok", "start_utc": started_utc,
                   "schedule_lag_ns": max(0, started_ns - due_ns),
                   "elapsed_ns": elapsed_ns, "end_to_end_ns": finished_ns - due_ns,
                   "finished_offset_ns": finished_ns - start_ns,
                   "validation_ns": validation_ns, "result_count": count,
                   "logical_result_bytes": size}
        except Exception as error:
            finished_ns = time.perf_counter_ns()
            row = {"slot": slot, "sequence": request["sequence"], "operation": request["operation"],
                   "group": group_name(request), "status": "error", "start_utc": started_utc,
                   "schedule_lag_ns": max(0, started_ns - due_ns),
                   "elapsed_ns": elapsed_ns if elapsed_ns is not None else finished_ns - started_ns,
                   "end_to_end_ns": finished_ns - due_ns,
                   "finished_offset_ns": finished_ns - start_ns, "error": str(error)}
        finally:
            try:
                recorder.add(row, duration_ns)
            finally:
                pool.semaphore.release()

    slot = 0
    while True:
        due_ns = start_ns + int(slot * 1e9 / rate)
        if due_ns >= deadline_ns:
            break
        remaining_ns = due_ns - time.perf_counter_ns()
        if remaining_ns > 0:
            time.sleep(remaining_ns / 1e9)
        request = requests[slot % len(requests)]
        if pool.semaphore.acquire(blocking=False):
            try:
                pool.executor.submit(worker, slot, request, due_ns)
            except Exception:
                pool.semaphore.release()
                raise
        else:
            now_ns = time.perf_counter_ns()
            recorder.add({"slot": slot, "sequence": request["sequence"],
                          "operation": request["operation"], "group": group_name(request),
                          "status": "dropped", "schedule_lag_ns": max(0, now_ns - due_ns)}, duration_ns)
        slot += 1
    pool.drain()
    return recorder.summary(duration_ns, time.perf_counter_ns() - start_ns, len(pool.clients))


def run(args):
    documents, serial_requests = load_input(args.input)
    requests = derive_read_requests(documents, serial_requests)
    input_manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    output = args.output or (ROOT / "results/documents/load-runs" /
                              f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{args.store}-{uuid.uuid4().hex[:8]}")
    output.mkdir(parents=True, exist_ok=False)
    read_trace_sha256 = write_jsonl(output / "read-requests.jsonl", requests)
    factory = PostgreSQL if args.store == "postgres" else CouchDB
    manifest = {
        "kind": "open-loop-read-only-direct-client", "store": args.store,
        "client": "python", "python_version": platform.python_version(),
        "transport": "psycopg persistent connection per worker" if args.store == "postgres"
                     else "urllib HTTP request per operation",
        "psycopg_version": psycopg.__version__ if args.store == "postgres" else None,
        "host_platform": platform.platform(), "started_utc": utc_now(),
        "input_profile": input_manifest["profile"],
        "input_manifest_sha256": hashlib.sha256((args.input / "manifest.json").read_bytes()).hexdigest(),
        "read_trace_sha256": read_trace_sha256, "read_request_count": len(requests),
        "read_mix": dict(sorted(Counter(r["operation"] for r in requests).items())),
        "rate_per_second": args.rate, "concurrency": args.concurrency,
        "warmup_seconds": args.warmup_seconds, "measure_seconds": args.measure_seconds,
        "repetitions_requested": args.repetitions,
        "latency_target_ms": args.latency_target_ms,
        "max_offered_failure_rate": args.max_failure_rate,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reference_validation_outside_service_time": True,
        "resource_metrics": False, "status": "running", "repetitions": [],
    }
    try:
        for number in range(1, args.repetitions + 1):
            repetition_dir = output / f"repeat-{number:02d}"
            repetition_dir.mkdir()
            phases = {}
            admin = factory()
            try:
                if "store_version" not in manifest:
                    manifest["store_version"] = store_version(admin)
                phases["setup_started_utc"] = utc_now()
                setup_started = time.perf_counter_ns()
                admin.seed(documents)
                setup_ns = time.perf_counter_ns() - setup_started
                phases["setup_finished_utc"] = utc_now()
                phases["prepare_started_utc"] = utc_now()
                preparation, query_diagnostics = prepare_read_paths(admin, requests)
                preparation["storage"] = admin.storage_size()
                phases["prepare_finished_utc"] = utc_now()
                if query_diagnostics:
                    plans_path = repetition_dir / "query-plans.json"
                    write_json(plans_path, query_diagnostics)
                    preparation["query_plans_sha256"] = hashlib.sha256(plans_path.read_bytes()).hexdigest()
            finally:
                admin.close()
            pool = ClientPool(factory, args.concurrency)
            try:
                phases["warmup_started_utc"] = utc_now()
                warmup = run_phase(pool, requests, args.rate, args.warmup_seconds, Recorder()) \
                    if args.warmup_seconds else None
                phases["warmup_finished_utc"] = utc_now()
                if warmup and warmup["errors"]:
                    raise RuntimeError(f"Warmup had {warmup['errors']} errors")
                with (repetition_dir / "operations.jsonl").open("wb") as stream:
                    phases["measure_started_utc"] = utc_now()
                    measured = run_phase(pool, requests, args.rate, args.measure_seconds, Recorder(stream))
                    phases["measure_finished_utc"] = utc_now()
            finally:
                pool.close()
            summary = {"repetition": number, "setup_ns": setup_ns, "preparation": preparation,
                       "warmup": warmup,
                       "measure": measured, "phase_intervals": phases,
                       "status": "passed" if not measured["errors"] else "failed"}
            summary["within_provisional_targets"] = (
                measured["end_to_end_p95_ns"] is not None and
                measured["end_to_end_p95_ns"] <= args.latency_target_ms * 1e6 and
                measured["offered_failure_rate"] <= args.max_failure_rate)
            write_json(repetition_dir / "summary.json", summary)
            summary["artifacts"] = {name: hashlib.sha256((repetition_dir / name).read_bytes()).hexdigest()
                                    for name in ("operations.jsonl", "summary.json")}
            manifest["repetitions"].append(summary)
            write_json(output / "manifest.json", manifest)
        manifest["status"] = "passed" if all(r["status"] == "passed" for r in manifest["repetitions"]) else "failed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        manifest["finished_utc"] = utc_now()
        write_json(output / "manifest.json", manifest)
    if manifest["status"] != "passed":
        raise RuntimeError(f"Load run had errors; inspect {output / 'manifest.json'}")
    return output, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("postgres", "couchdb"), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rate", type=float, default=20.0, help="offered requests per second")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--warmup-seconds", type=float, default=2.0)
    parser.add_argument("--measure-seconds", type=float, default=5.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--latency-target-ms", type=float, default=100.0)
    parser.add_argument("--max-failure-rate", type=float, default=0.001,
                        help="maximum (errors + dropped) / offered")
    args = parser.parse_args()
    if not math.isfinite(args.rate) or args.rate <= 0 or args.concurrency < 1 or \
       not math.isfinite(args.warmup_seconds) or args.warmup_seconds < 0 or \
       not math.isfinite(args.measure_seconds) or args.measure_seconds <= 0 or args.repetitions < 1 or \
       not math.isfinite(args.latency_target_ms) or args.latency_target_ms <= 0 or \
       not math.isfinite(args.max_failure_rate) or not 0 <= args.max_failure_rate <= 1:
        parser.error("rate, concurrency, measure duration, and repetitions must be positive")
    output, manifest = run(args)
    print(f"{args.store}: {manifest['status']}; artifacts: {output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, psycopg.Error) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
