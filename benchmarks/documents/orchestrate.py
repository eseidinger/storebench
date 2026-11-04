#!/usr/bin/env python3
"""Run one document read or write load with host-side resource samples."""
import argparse
import hashlib
import http.client
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infrastructure/documents.compose.yaml"
LOAD = ROOT / "benchmarks/documents/load.py"
WRITE_LOAD = ROOT / "benchmarks/documents/write_load.py"
DEFAULT_WRITE_PROFILE = ROOT / "workloads/documents/profiles/catalog-maintenance-write-v1.json"
DOCKER_SOCKET = Path(os.environ.get("STOREBENCH_DOCKER_SOCKET", "/var/run/docker.sock"))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def write_json(path, value):
    path.write_bytes(json_bytes(value))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost", timeout=10)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.socket_path))


def docker_get(path, socket_path=DOCKER_SOCKET):
    connection = UnixConnection(socket_path)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"Docker API {response.status} for {path}: {body[:200]!r}")
        return json.loads(body)
    finally:
        connection.close()


def compose(*arguments):
    command = ["docker", "compose", "-f", str(COMPOSE), *arguments]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"docker compose {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def effective_limits(inspect, desired):
    host = inspect["HostConfig"]
    nano_cpus = host.get("NanoCpus") or 0
    quota, period = host.get("CpuQuota") or 0, host.get("CpuPeriod") or 0
    cpu_cores = nano_cpus / 1e9 if nano_cpus else quota / period if quota > 0 and period > 0 else None
    memory_bytes = host.get("Memory") or None
    expected_cpu, expected_memory = float(desired["cpus"]), int(desired["mem_limit"])
    if cpu_cores is None or not math.isclose(cpu_cores, expected_cpu, rel_tol=0, abs_tol=0.001):
        raise RuntimeError(f"Effective CPU limit {cpu_cores} differs from Compose {expected_cpu}")
    if memory_bytes != expected_memory:
        raise RuntimeError(f"Effective memory limit {memory_bytes} differs from Compose {expected_memory}")
    if not inspect["State"]["Running"] or inspect["State"].get("Health", {}).get("Status") != "healthy":
        raise RuntimeError("Target container is not running and healthy")
    return {"cpu_cores": cpu_cores, "memory_bytes": memory_bytes,
            "container_id": inspect["Id"], "container_started_at": inspect["State"]["StartedAt"],
            "image_ref": inspect["Config"]["Image"], "image_id": inspect["Image"]}


def host_snapshot(path):
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:")):
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0]) * 1024
    disk = shutil.disk_usage(path)
    return {"platform": platform.platform(), "cpu_count": os.cpu_count(),
            "memory_bytes": meminfo, "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free}


def sum_io(items, operation):
    if items is None:
        return None
    return sum(item.get("value", 0) for item in items if item.get("op", "").lower() == operation)


def flatten_store_stats(raw, container_id, started_at, sampled_ns, sampled_utc):
    cpu = raw.get("cpu_stats", {})
    memory = raw.get("memory_stats", {})
    networks = raw.get("networks")
    io = raw.get("blkio_stats", {}).get("io_service_bytes_recursive")
    throttling = cpu.get("throttling_data", {})
    return {"role": "store", "status": "ok", "sampled_utc": sampled_utc,
            "sampled_monotonic_ns": sampled_ns, "container_id": container_id,
            "container_started_at": started_at,
            "cpu_total_ns": cpu.get("cpu_usage", {}).get("total_usage"),
            "memory_usage_bytes": memory.get("usage"), "memory_limit_bytes": memory.get("limit"),
            "memory_inactive_file_bytes": memory.get("stats", {}).get("inactive_file"),
            "block_read_bytes": sum_io(io, "read"), "block_write_bytes": sum_io(io, "write"),
            "network_rx_bytes": sum(value.get("rx_bytes", 0) for value in networks.values()) if networks else None,
            "network_tx_bytes": sum(value.get("tx_bytes", 0) for value in networks.values()) if networks else None,
            "pids": raw.get("pids_stats", {}).get("current"),
            "throttled_periods": throttling.get("throttled_periods"),
            "throttled_time_ns": throttling.get("throttled_time")}


def sample_client(pid, sampled_ns, sampled_utc):
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text()
    except FileNotFoundError:
        return None
    fields = raw.rsplit(")", 1)[1].split()
    ticks = int(fields[11]) + int(fields[12])
    return {"role": "client", "status": "ok", "sampled_utc": sampled_utc,
            "sampled_monotonic_ns": sampled_ns, "pid": pid,
            "process_start_ticks": int(fields[19]),
            "cpu_total_ns": int(ticks * 1e9 / os.sysconf("SC_CLK_TCK")),
            "memory_usage_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
            "memory_limit_bytes": None, "block_read_bytes": None, "block_write_bytes": None,
            "network_rx_bytes": None, "network_tx_bytes": None}


class Sampler(threading.Thread):
    def __init__(self, container_id, started_at, output, interval_seconds):
        super().__init__(daemon=True)
        self.container_id = container_id
        self.started_at = started_at
        self.output = output
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.client_pid = None
        self.error_count = 0
        self.sample_count = 0
        self.restart_count = 0

    def run(self):
        with self.output.open("wb") as stream:
            while not self.stop_event.is_set():
                requested_utc = utc_now()
                try:
                    raw = docker_get(f"/containers/{quote(self.container_id)}/stats?stream=false&one-shot=true")
                    inspect = docker_get(f"/containers/{quote(self.container_id)}/json")
                    started_at = inspect["State"]["StartedAt"]
                    if started_at != self.started_at:
                        self.restart_count += 1
                        self.started_at = started_at
                    sampled_ns = time.monotonic_ns()
                    sampled_utc = utc_now()
                    row = flatten_store_stats(raw, self.container_id, started_at, sampled_ns, sampled_utc)
                    row["requested_utc"] = requested_utc
                    self.sample_count += 1
                except Exception as error:
                    sampled_ns = time.monotonic_ns()
                    sampled_utc = utc_now()
                    row = {"role": "store", "status": "error", "sampled_utc": sampled_utc,
                           "sampled_monotonic_ns": sampled_ns, "container_id": self.container_id,
                           "error": str(error)}
                    self.error_count += 1
                stream.write(json_bytes(row))
                if self.client_pid is not None:
                    try:
                        client = sample_client(self.client_pid, time.monotonic_ns(), utc_now())
                        if client is not None:
                            stream.write(json_bytes(client))
                    except Exception as error:
                        stream.write(json_bytes({"role": "client", "status": "error",
                                                 "sampled_utc": utc_now(), "error": str(error)}))
                stream.flush()
                self.stop_event.wait(self.interval_seconds)

    def stop(self):
        self.stop_event.set()
        self.join(timeout=15)
        if self.is_alive():
            raise RuntimeError("Resource sampler did not stop")


def phase_for(timestamp, repetitions):
    sample = datetime.fromisoformat(timestamp)
    for repetition in repetitions:
        phases = repetition["phase_intervals"]
        for phase in ("setup", "prepare", "warmup", "measure", "validate"):
            start = phases.get(f"{phase}_started_utc")
            finish = phases.get(f"{phase}_finished_utc")
            if start and finish and datetime.fromisoformat(start) <= sample <= datetime.fromisoformat(finish):
                return repetition["repetition"], phase
    return None, "outside"


def annotate_samples(path, repetitions):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["repetition"], row["phase"] = phase_for(row["sampled_utc"], repetitions)
    with path.open("wb") as stream:
        for row in rows:
            stream.write(json_bytes(row))
    return rows


def resource_summary(rows):
    result = {}
    for role in ("store", "client"):
        measured = [row for row in rows if row["role"] == role and row["status"] == "ok"
                    and row["phase"] == "measure"]
        measured.sort(key=lambda row: row["sampled_monotonic_ns"])
        valid_cpu_ns = 0
        valid_elapsed_ns = 0
        for previous, current in zip(measured, measured[1:]):
            if previous["repetition"] != current["repetition"]:
                continue
            if previous.get("cpu_total_ns") is None or current.get("cpu_total_ns") is None:
                continue
            if role == "store" and previous.get("container_started_at") != current.get("container_started_at"):
                continue
            if role == "client" and previous.get("process_start_ticks") != current.get("process_start_ticks"):
                continue
            delta_ns = current["sampled_monotonic_ns"] - previous["sampled_monotonic_ns"]
            cpu_delta = current["cpu_total_ns"] - previous["cpu_total_ns"]
            if delta_ns > 0 and cpu_delta >= 0:
                valid_cpu_ns += cpu_delta
                valid_elapsed_ns += delta_ns
        memory = [row["memory_usage_bytes"] for row in measured if row.get("memory_usage_bytes") is not None]
        result[role] = {"measure_samples": len(measured),
                        "cpu_cores_mean": valid_cpu_ns / valid_elapsed_ns if valid_elapsed_ns else None,
                        "memory_peak_bytes": max(memory) if memory else None}
    return result


def sample_interval_summary(rows):
    samples = sorted((row for row in rows if row["role"] == "store" and row["status"] == "ok"),
                     key=lambda row: row["sampled_monotonic_ns"])
    intervals = [(current["sampled_monotonic_ns"] - previous["sampled_monotonic_ns"]) / 1e9
                 for previous, current in zip(samples, samples[1:])]
    return {"count": len(intervals), "mean_seconds": sum(intervals) / len(intervals) if intervals else None,
            "max_seconds": max(intervals) if intervals else None}


def run(args):
    defaults = json.loads(args.write_profile.read_text()) if args.workload == "write" else {
        "rate_per_second": 20.0, "concurrency": 8, "warmup_seconds": 2.0,
        "measure_seconds": 5.0, "repetitions": 1,
        "latency_target_ms": 100.0, "max_failure_rate": 0.001}
    settings = {"rate": args.rate if args.rate is not None else defaults["rate_per_second"],
                "concurrency": args.concurrency if args.concurrency is not None else defaults["concurrency"],
                "warmup_seconds": args.warmup_seconds if args.warmup_seconds is not None else defaults["warmup_seconds"],
                "measure_seconds": args.measure_seconds if args.measure_seconds is not None else defaults["measure_seconds"],
                "repetitions": args.repetitions if args.repetitions is not None else defaults["repetitions"],
                "latency_target_ms": args.latency_target_ms if args.latency_target_ms is not None else defaults["latency_target_ms"],
                "max_failure_rate": args.max_failure_rate if args.max_failure_rate is not None else defaults["max_failure_rate"]}
    if not math.isfinite(settings["rate"]) or settings["rate"] <= 0 or settings["concurrency"] < 1 or \
       not math.isfinite(settings["warmup_seconds"]) or settings["warmup_seconds"] < 0 or \
       not math.isfinite(settings["measure_seconds"]) or settings["measure_seconds"] <= 0 or \
       settings["repetitions"] < 1 or not math.isfinite(settings["latency_target_ms"]) or \
       settings["latency_target_ms"] <= 0 or not math.isfinite(settings["max_failure_rate"]) or \
       not 0 <= settings["max_failure_rate"] <= 1:
        raise ValueError("Invalid load settings")
    output = args.output or (ROOT / "results/documents/orchestrated" /
                              f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{args.workload}-{args.store}-{uuid.uuid4().hex[:8]}")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "host-orchestrated-document-load", "store": args.store,
                "workload": args.workload,
                "started_utc": utc_now(), "sampler_enabled": not args.no_sampler,
                "sampler_interval_seconds": args.sample_interval if not args.no_sampler else None,
                "host": host_snapshot(output), "status": "running"}
    started_container = False
    sampler = None
    process = None
    try:
        configured = json.loads(compose("config", "--format", "json"))["services"][args.store]
        active = {name.strip() for name in compose("ps", "--services", "--status", "running").splitlines()
                  if name.strip()}
        if active - {args.store}:
            raise RuntimeError(f"Other Compose services are running: {', '.join(sorted(active - {args.store}))}")
        if args.store not in active:
            compose("up", "-d", "--wait", args.store)
            started_container = True
        container_id = compose("ps", "-q", args.store).strip()
        if not container_id:
            raise RuntimeError("Compose did not return a target container ID")
        inspect = docker_get(f"/containers/{quote(container_id)}/json")
        manifest["effective_limits"] = effective_limits(inspect, configured)
        manifest["compose_requested"] = {"cpu_cores": float(configured["cpus"]),
                                          "memory_bytes": int(configured["mem_limit"]),
                                          "image_ref": configured["image"]}
        command = [sys.executable, str(WRITE_LOAD if args.workload == "write" else LOAD),
                   "--store", args.store, "--input", str(args.input),
                   "--output", str(output / "load"),
                   "--rate-per-second" if args.workload == "write" else "--rate", str(settings["rate"]),
                   "--concurrency", str(settings["concurrency"]),
                   "--warmup-seconds", str(settings["warmup_seconds"]),
                   "--measure-seconds", str(settings["measure_seconds"]),
                   "--repetitions", str(settings["repetitions"]),
                   "--latency-target-ms", str(settings["latency_target_ms"]),
                   "--max-failure-rate", str(settings["max_failure_rate"])]
        if args.workload == "write":
            command.extend(["--profile", str(args.write_profile)])
        manifest["load_arguments"] = settings
        if args.workload == "write":
            manifest["write_profile"] = str(args.write_profile)
        if not args.no_sampler:
            sampler = Sampler(container_id, inspect["State"]["StartedAt"],
                              output / "container-metrics.jsonl", args.sample_interval)
            sampler.start()
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        if sampler is not None:
            sampler.client_pid = process.pid
        stdout, stderr = process.communicate()
        (output / "load.stdout.txt").write_text(stdout)
        (output / "load.stderr.txt").write_text(stderr)
        manifest["load_exit_code"] = process.returncode
        if sampler is not None:
            sampler.stop()
            restart_count = sampler.restart_count
            sampler = None
        manifest["load_manifest_sha256"] = sha256_file(output / "load/manifest.json") \
            if (output / "load/manifest.json").exists() else None
        load_manifest = json.loads((output / "load/manifest.json").read_text()) \
            if manifest["load_manifest_sha256"] else {"repetitions": []}
        final_inspect = docker_get(f"/containers/{quote(container_id)}/json")
        container_changed = (final_inspect["State"]["StartedAt"] != inspect["State"]["StartedAt"] or
                             not final_inspect["State"]["Running"])
        manifest["container_restarts"] = int(container_changed)
        if not args.no_sampler:
            rows = annotate_samples(output / "container-metrics.jsonl", load_manifest["repetitions"])
            manifest["resource_samples_sha256"] = sha256_file(output / "container-metrics.jsonl")
            manifest["resource_sample_count"] = sum(row["role"] == "store" and row["status"] == "ok" for row in rows)
            manifest["resource_sample_errors"] = sum(row["role"] == "store" and row["status"] == "error" for row in rows)
            manifest["client_sample_errors"] = sum(row["role"] == "client" and row["status"] == "error" for row in rows)
            manifest["container_restarts"] = max(restart_count, int(container_changed))
            manifest["actual_sample_intervals"] = sample_interval_summary(rows)
            manifest["resource_summary"] = resource_summary(rows)
            manifest["status"] = "passed" if process.returncode == 0 and \
                not manifest["resource_sample_errors"] and not manifest["client_sample_errors"] and \
                not manifest["container_restarts"] and \
                all(manifest["resource_summary"][role]["cpu_cores_mean"] is not None
                    for role in ("store", "client")) else "incomplete"
        else:
            manifest["status"] = "passed" if process.returncode == 0 and \
                load_manifest.get("status") == "passed" and not container_changed else "incomplete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        cleanup_errors = []
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if sampler is not None:
            try:
                sampler.stop()
            except Exception as error:
                cleanup_errors.append(str(error))
        if started_container:
            try:
                compose("down")  # Keep named volumes; restore the prior stopped state.
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            manifest["status"] = "failed"
            manifest["cleanup_errors"] = cleanup_errors
        manifest["finished_utc"] = utc_now()
        write_json(output / "orchestration.json", manifest)
    if manifest["status"] != "passed":
        raise RuntimeError(f"Orchestrated run incomplete; inspect {output / 'orchestration.json'}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("postgres", "couchdb"), required=True)
    parser.add_argument("--workload", choices=("read", "write"), default="read")
    parser.add_argument("--write-profile", type=Path, default=DEFAULT_WRITE_PROFILE)
    parser.add_argument("--input", type=Path, default=ROOT / "results/documents/storefront-v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--warmup-seconds", type=float)
    parser.add_argument("--measure-seconds", type=float)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--no-sampler", action="store_true")
    parser.add_argument("--latency-target-ms", type=float)
    parser.add_argument("--max-failure-rate", type=float)
    args = parser.parse_args()
    if not math.isfinite(args.sample_interval) or args.sample_interval <= 0:
        parser.error("sample interval must be positive")
    output = run(args)
    print(f"{args.store}: limits checked, sampler {'disabled' if args.no_sampler else 'captured'}; "
          f"artifacts: {output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
