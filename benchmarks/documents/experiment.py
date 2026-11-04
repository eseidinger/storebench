#!/usr/bin/env python3
"""Run and report ordered, paired document read or write experiments."""
import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT / "workloads/documents/profiles/read-only-experiment-v1.json"
DEFAULT_INPUT = ROOT / "results/documents/storefront-v1"
STORES = ("postgres", "couchdb")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate_plan(plan):
    plan = dict(plan)
    workload = plan.get("workload", "read")
    if workload == "write":
        if not isinstance(plan.get("name"), str) or not plan["name"] or \
           not isinstance(plan.get("operation_percent"), dict) or \
           not isinstance(plan.get("request_count"), int):
            raise ValueError("Write experiment requires a complete write workload profile")
    if plan.get("version") != 1 or not isinstance(plan.get("seed"), int):
        raise ValueError("Expected experiment plan version 1 and an integer seed")
    if workload not in ("read", "write"):
        raise ValueError("workload must be read or write")
    if not isinstance(plan.get("input_profile"), str) or not plan["input_profile"]:
        raise ValueError("input_profile must name the fixture profile")
    for key in ("concurrencies", "rates_per_second"):
        values = plan.get(key)
        if not isinstance(values, list) or not values or len(set(values)) != len(values) or \
           any(not finite_positive(value) for value in values):
            raise ValueError(f"{key} must contain unique positive numbers")
    if any(not isinstance(value, int) for value in plan["concurrencies"]):
        raise ValueError("concurrencies must contain integers")
    if not isinstance(plan.get("repetitions"), int) or plan["repetitions"] < 1:
        raise ValueError("repetitions must be positive")
    for key in ("measure_seconds", "latency_target_ms", "sample_interval_seconds",
                "max_sample_interval_factor"):
        if not finite_positive(plan.get(key)):
            raise ValueError(f"{key} must be positive")
    if plan["max_sample_interval_factor"] < 1:
        raise ValueError("max_sample_interval_factor must be at least 1")
    warmup = plan.get("warmup_seconds")
    if not isinstance(warmup, (int, float)) or not math.isfinite(warmup) or warmup < 0:
        raise ValueError("warmup_seconds must be nonnegative")
    failure = plan.get("max_failure_rate")
    if not isinstance(failure, (int, float)) or not math.isfinite(failure) or not 0 <= failure <= 1:
        raise ValueError("max_failure_rate must be between 0 and 1")
    overhead = plan.get("sampler_overhead")
    if not isinstance(overhead, dict) or not isinstance(overhead.get("pairs"), int) or \
       isinstance(overhead["pairs"], bool) or overhead["pairs"] < 0:
        raise ValueError("sampler_overhead pairs must be nonnegative")
    if overhead["pairs"] and (overhead.get("concurrency") not in plan["concurrencies"] or
                              overhead.get("rate_per_second") not in plan["rates_per_second"]):
        raise ValueError("sampler_overhead requires a matrix point when pairs are enabled")
    if workload == "write":
        required = math.ceil(max(plan["rates_per_second"]) *
                             max(plan["warmup_seconds"], plan["measure_seconds"]))
        if plan["request_count"] < required:
            raise ValueError(f"Write profile needs at least {required} requests for the highest rate")
    return plan


def schedule(plan):
    rng = random.Random(plan["seed"])
    steps = []
    # Keep the order balanced at each matrix point; the initial store is seeded.
    for concurrency in plan["concurrencies"]:
        for rate in plan["rates_per_second"]:
            first = rng.choice(STORES)
            for repetition in range(1, plan["repetitions"] + 1):
                order = (first, STORES[1 - STORES.index(first)])
                if repetition % 2 == 0:
                    order = order[::-1]
                for store in order:
                    steps.append({"kind": "matrix", "store": store, "concurrency": concurrency,
                                  "rate_per_second": rate, "repetition": repetition,
                                  "sampler_enabled": True})
    overhead = plan["sampler_overhead"]
    for pair in range(1, overhead["pairs"] + 1):
        stores = list(STORES)
        rng.shuffle(stores)
        for store in stores:
            enabled_first = rng.choice((True, False))
            for enabled in (enabled_first, not enabled_first):
                steps.append({"kind": "overhead", "store": store,
                              "concurrency": overhead["concurrency"],
                              "rate_per_second": overhead["rate_per_second"],
                              "pair": pair, "sampler_enabled": enabled})
    return steps


def run_step(step, plan, input_dir, output, write_profile=None):
    workload = plan.get("workload", "read")
    command = [sys.executable, str(ROOT / "benchmarks/documents/orchestrate.py"),
               "--workload", workload, "--store", step["store"],
               "--input", str(input_dir), "--output", str(output),
               "--rate", str(step["rate_per_second"]), "--concurrency", str(step["concurrency"]),
               "--warmup-seconds", str(plan["warmup_seconds"]),
               "--measure-seconds", str(plan["measure_seconds"]), "--repetitions", "1",
               "--sample-interval", str(plan["sample_interval_seconds"]),
               "--latency-target-ms", str(plan["latency_target_ms"]),
               "--max-failure-rate", str(plan["max_failure_rate"])]
    if workload == "write":
        command.extend(["--write-profile", str(write_profile)])
    if not step["sampler_enabled"]:
        command.append("--no-sampler")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    # Orchestrator creates its output directory, including its own stdout/stderr.
    if output.exists():
        (output / "experiment.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (output / "experiment.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    result = {**step, "output": str(output), "exit_code": completed.returncode,
              "status": "failed"}
    orchestration_path = output / "orchestration.json"
    load_path = output / "load/manifest.json"
    if orchestration_path.exists():
        orchestration = json.loads(orchestration_path.read_text(encoding="utf-8"))
        result["orchestration_status"] = orchestration["status"]
        result["actual_sample_intervals"] = orchestration.get("actual_sample_intervals")
        result["resource_summary"] = orchestration.get("resource_summary")
        result["resource_sample_count"] = orchestration.get("resource_sample_count")
    if load_path.exists():
        load = json.loads(load_path.read_text(encoding="utf-8"))
        result["load_kind_ok"] = load.get("kind") == (
            "open-loop-concurrent-document-writes" if workload == "write"
            else "open-loop-read-only-direct-client")
        if workload == "write":
            result["write_profile_sha256"] = load.get("profile_sha256")
            result["write_profile_ok"] = load.get("profile_sha256") == hashlib.sha256(
                write_profile.read_bytes()).hexdigest()
        if load.get("repetitions"):
            repetition = load["repetitions"][0]
            result["measure"] = repetition["measure"]
            result["setup_ns"] = repetition.get("setup_ns")
            result["preparation"] = repetition.get("preparation")
            result["correctness_status"] = repetition["status"]
            result["within_provisional_targets"] = repetition["within_provisional_targets"]
            if workload == "write":
                result["validation"] = repetition.get("validation")
    intervals = result.get("actual_sample_intervals") or {}
    sample_ok = (not step["sampler_enabled"] or
                 (intervals.get("count", 0) >= 1 and
                  intervals.get("max_seconds", math.inf) <=
                  plan["sample_interval_seconds"] * plan["max_sample_interval_factor"]))
    result["sample_interval_ok"] = sample_ok
    result["status"] = "passed" if completed.returncode == 0 and \
        result.get("orchestration_status") == "passed" and \
        result.get("correctness_status") == "passed" and "measure" in result and sample_ok and \
        result.get("load_kind_ok") is True and \
        (workload != "write" or (result.get("write_profile_ok") is True and
                                 (result.get("validation") or {}).get("status") == "passed")) else "failed"
    result["qualifies"] = result["status"] == "passed" and result.get("within_provisional_targets") is True
    return result


def summarize(results, plan):
    points = defaultdict(list)
    for result in results:
        if result["kind"] == "matrix":
            points[(result["store"], result["concurrency"], result["rate_per_second"])].append(result)
    matrix = []
    capacity = []
    for (store, concurrency, rate), runs in sorted(points.items()):
        throughput = [run["measure"]["completed_within_window_per_second"] for run in runs
                      if run.get("measure")]
        p95 = [run["measure"]["end_to_end_p95_ns"] / 1e6 for run in runs
               if run.get("measure") and run["measure"]["end_to_end_p95_ns"] is not None]
        setup = [run["setup_ns"] / 1e9 for run in runs if run.get("setup_ns") is not None]
        preparation = [run["preparation"]["elapsed_ns"] / 1e9 for run in runs
                       if run.get("preparation") and run["preparation"].get("elapsed_ns") is not None]
        index_bytes = [run["preparation"]["storage"]["index_file_bytes"] for run in runs
                       if run.get("preparation") and run["preparation"].get("storage") and
                       run["preparation"]["storage"].get("index_file_bytes") is not None]
        point = {"store": store, "concurrency": concurrency, "rate_per_second": rate,
                 "runs": len(runs), "expected_runs": plan["repetitions"],
                 "all_qualify": len(runs) == plan["repetitions"] and
                 all(run["qualifies"] for run in runs),
                 "completed_per_second_median": statistics.median(throughput) if throughput else None,
                 "completed_per_second_range": [min(throughput), max(throughput)] if throughput else None,
                 "run_p95_ms_median": statistics.median(p95) if p95 else None,
                 "run_p95_ms_range": [min(p95), max(p95)] if p95 else None,
                 "setup_seconds_median": statistics.median(setup) if setup else None,
                 "preparation_seconds_median": statistics.median(preparation) if preparation else None,
                 "index_file_mib_median": statistics.median(index_bytes) / (1024 ** 2)
                 if index_bytes else None}
        if plan.get("workload", "read") == "write":
            failures = [run["measure"]["technical_failure_rate"] for run in runs
                        if run.get("measure") and run["measure"].get("technical_failure_rate") is not None]
            conflicts = [run["measure"]["conflicts"] for run in runs
                         if run.get("measure") and run["measure"].get("conflicts") is not None]
            point["technical_failure_rate_median"] = statistics.median(failures) if failures else None
            point["conflicts_per_run_median"] = statistics.median(conflicts) if conflicts else None
            for status in ("conflict_exhausted", "condition_rejected", "duplicate_rejected", "dropped"):
                values = [run["measure"]["statuses"].get(status, 0) for run in runs
                          if run.get("measure") and run["measure"].get("statuses") is not None]
                point[f"{status}_per_run_median"] = statistics.median(values) if values else None
        matrix.append(point)
    for store in STORES:
        for concurrency in plan["concurrencies"]:
            qualified = [point for point in matrix if point["store"] == store and
                         point["concurrency"] == concurrency and point["all_qualify"]]
            best = max(qualified, key=lambda point: point["rate_per_second"]) if qualified else None
            capacity.append({"store": store, "concurrency": concurrency,
                             "highest_tested_qualifying_rate": best["rate_per_second"] if best else None,
                             "completed_per_second_median": best["completed_per_second_median"] if best else None,
                             "highest_configured_rate_qualifies": bool(best and
                                 best["rate_per_second"] == max(plan["rates_per_second"]))})
    pairs = []
    for store in STORES:
        for pair in range(1, plan["sampler_overhead"]["pairs"] + 1):
            pair_runs = [run for run in results if run["kind"] == "overhead" and
                         run["store"] == store and run["pair"] == pair]
            if len(pair_runs) != 2 or not all(run["status"] == "passed" for run in pair_runs):
                pairs.append({"store": store, "pair": pair, "status": "incomplete"})
                continue
            on = next(run for run in pair_runs if run["sampler_enabled"])
            off = next(run for run in pair_runs if not run["sampler_enabled"])
            on_p95 = on["measure"]["end_to_end_p95_ns"]
            off_p95 = off["measure"]["end_to_end_p95_ns"]
            on_rate = on["measure"]["completed_within_window_per_second"]
            off_rate = off["measure"]["completed_within_window_per_second"]
            pairs.append({"store": store, "pair": pair, "status": "passed",
                          "p95_on_over_off": on_p95 / off_p95 if off_p95 else None,
                          "throughput_on_over_off": on_rate / off_rate if off_rate else None})
    overhead = []
    for store in STORES:
        complete = [item for item in pairs if item["store"] == store and item["status"] == "passed"]
        p95_ratios = [item["p95_on_over_off"] for item in complete if item["p95_on_over_off"] is not None]
        throughput_ratios = [item["throughput_on_over_off"] for item in complete
                             if item["throughput_on_over_off"] is not None]
        overhead.append({"store": store, "completed_pairs": len(complete),
                         "p95_ratio_median": statistics.median(p95_ratios) if p95_ratios else None,
                         "throughput_ratio_median": statistics.median(throughput_ratios)
                         if throughput_ratios else None})
    return {"matrix": matrix, "capacity": capacity, "overhead_pairs": pairs,
            "sampler_overhead": overhead,
            "complete": len(results) == len(schedule(plan)) and all(run["status"] == "passed" for run in results)}


def markdown_report(report):
    workload = report.get("workload", "read")
    title = "Document concurrent-write experiment" if workload == "write" else "Document read-only experiment"
    lines = [f"# {title}", "",
             f"Runs: {len(report['runs'])}; execution complete: {report['summary']['complete']}.", "",
             "A point qualifies only when every independent run passes correctness, latency, failure,",
             "resource and sampling checks. Run p95 values are summarized by median and range;",
             "raw request percentiles are never pooled or averaged across runs.", "",
             "## Highest tested qualifying load", "",
             "| Store | Workers | Offered/s | Completed/s (median) | Top rate qualifies |",
             "| --- | ---: | ---: | ---: | --- |"]
    for row in report["summary"]["capacity"]:
        lines.append(f"| {row['store']} | {row['concurrency']} | "
                     f"{row['highest_tested_qualifying_rate']} | {row['completed_per_second_median']} | "
                     f"{row['highest_configured_rate_qualifies']} |")
    lines += ["", "A qualifying highest configured rate leaves the capacity ceiling unbracketed.", "",
              "## Matrix", "",
              "| Store | Workers | Offered/s | Qualifies | Runs | Completed/s median [range] | Run p95 ms median [range] |",
              "| --- | ---: | ---: | --- | ---: | --- | --- |"]
    for row in report["summary"]["matrix"]:
        lines.append(f"| {row['store']} | {row['concurrency']} | {row['rate_per_second']} | "
                     f"{row['all_qualify']} | {row['runs']}/{row['expected_runs']} | "
                     f"{row['completed_per_second_median']} {row['completed_per_second_range']} | "
                     f"{row['run_p95_ms_median']} {row['run_p95_ms_range']} |")
    if workload == "write":
        lines += ["", "## Write outcomes", "",
                  "p95 covers successful logical writes. Technical failures are unexpected errors,",
                  "dropped requests and exhausted conflicts. Duplicate and stock-condition rejections",
                  "are business outcomes and are reported separately. All values below are medians",
                  "of independent run-level counts or rates.", "",
                  "| Store | Workers | Offered/s | Technical failure rate | Conflicts | Exhausted | Stock rejected | Duplicate rejected | Dropped |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row in report["summary"]["matrix"]:
            lines.append(f"| {row['store']} | {row['concurrency']} | {row['rate_per_second']} | "
                         f"{row['technical_failure_rate_median']} | {row['conflicts_per_run_median']} | "
                         f"{row['conflict_exhausted_per_run_median']} | "
                         f"{row['condition_rejected_per_run_median']} | "
                         f"{row['duplicate_rejected_per_run_median']} | "
                         f"{row['dropped_per_run_median']} |")
    lines += ["", "## Setup and index footprint", "",
              "Setup includes fixture loading and index creation. Preparation includes lazy index builds,",
              "view builds and correctness diagnostics. Index sizes are measured after preparation.", "",
              "| Store | Workers | Offered/s | Setup s median | Prepare s median | Index MiB median |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["summary"]["matrix"]:
        lines.append(f"| {row['store']} | {row['concurrency']} | {row['rate_per_second']} | "
                     f"{row['setup_seconds_median']} | {row['preparation_seconds_median']} | "
                     f"{row['index_file_mib_median']} |")
    lines += ["", "## Sampler overhead", ""]
    if report["summary"]["overhead_pairs"]:
        lines += ["Ratios compare paired runs at the same offered rate; 1.0 means no measured change.", "",
                  "| Store | Complete pairs | p95 on/off median | Throughput on/off median |",
                  "| --- | ---: | ---: | ---: |"]
        for row in report["summary"]["sampler_overhead"]:
            lines.append(f"| {row['store']} | {row['completed_pairs']} | {row['p95_ratio_median']} | "
                         f"{row['throughput_ratio_median']} |")
    else:
        lines.append("Skipped by this profile.")
    lines += ["", "See report.json and each run's orchestration.json, load/manifest.json and operations.jsonl."]
    return "\n".join(lines) + "\n"


def run(args):
    plan_bytes = args.plan.read_bytes()
    plan = validate_plan(json.loads(plan_bytes))
    if not (args.input / "manifest.json").exists():
        if args.input != DEFAULT_INPUT:
            raise FileNotFoundError(f"Input fixture missing: {args.input}")
        subprocess.run([sys.executable, str(ROOT / "scripts/generate_document_workload.py")],
                       cwd=ROOT, check=True)
    input_manifest_bytes = (args.input / "manifest.json").read_bytes()
    input_manifest = json.loads(input_manifest_bytes)
    if input_manifest.get("profile") != plan["input_profile"]:
        raise ValueError(f"Input fixture profile {input_manifest.get('profile')!r} does not match "
                         f"experiment plan {plan['input_profile']!r}")
    output = args.output or ROOT / "results/documents/experiments" / \
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{plan.get('workload', 'read')}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    (output / "plan.json").write_bytes(plan_bytes)
    profile_copy = None
    if plan.get("workload", "read") == "write":
        profile_copy = output / "plan.json"
    steps = schedule(plan)
    workload = plan.get("workload", "read")
    report = {"kind": "document-concurrent-write-experiment" if workload == "write"
              else "document-read-only-experiment", "workload": workload,
              "plan": str(args.plan),
              "plan_copy": str(output / "plan.json"),
              "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
              "input_profile": plan["input_profile"],
              "input_manifest_sha256": hashlib.sha256(input_manifest_bytes).hexdigest(),
              "started_utc": datetime.now(timezone.utc).isoformat(), "runs": []}
    if profile_copy is not None:
        profile = json.loads(profile_copy.read_text(encoding="utf-8"))
        report["write_profile"] = profile["name"]
        report["write_profile_copy"] = str(profile_copy)
        report["write_profile_sha256"] = hashlib.sha256(profile_copy.read_bytes()).hexdigest()
    for number, step in enumerate(steps, 1):
        target = output / f"run-{number:03d}-{step['kind']}-{step['store']}"
        print(f"[{number}/{len(steps)}] {step['kind']} {step['store']} "
              f"workers={step['concurrency']} rate={step['rate_per_second']} "
              f"sampler={step['sampler_enabled']}", flush=True)
        result = run_step(step, plan, args.input, target, profile_copy)
        report["runs"].append(result)
        write_json(output / "progress.json", report)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = summarize(report["runs"], plan)
    write_json(output / "report.json", report)
    (output / "report.md").write_text(markdown_report(report), encoding="utf-8")
    print(f"Report: {output / 'report.md'}")
    if not report["summary"]["complete"]:
        raise RuntimeError(f"Some runs failed; inspect {output / 'report.json'}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
