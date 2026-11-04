"""Check Docker-resource parsing without requiring a running Docker daemon."""
import os
import unittest

from benchmarks.documents.orchestrate import (effective_limits, flatten_store_stats,
                                               phase_for, resource_summary, sample_client)


class DocumentOrchestratorTest(unittest.TestCase):
    def test_effective_limits_and_sample_fields(self):
        inspect = {"HostConfig": {"NanoCpus": 2_000_000_000, "Memory": 4_294_967_296},
                   "State": {"Running": True, "Health": {"Status": "healthy"},
                             "StartedAt": "2026-11-04T10:00:00Z"},
                   "Id": "abc", "Config": {"Image": "postgres:17.6"}, "Image": "sha256:abc"}
        limits = effective_limits(inspect, {"cpus": 2, "mem_limit": "4294967296"})
        self.assertEqual(limits["cpu_cores"], 2)
        self.assertEqual(limits["memory_bytes"], 4_294_967_296)
        with self.assertRaisesRegex(RuntimeError, "memory limit"):
            effective_limits(inspect, {"cpus": 2, "mem_limit": "1000"})

        raw = {"cpu_stats": {"cpu_usage": {"total_usage": 100},
                             "throttling_data": {"throttled_time": 3}},
               "memory_stats": {"usage": 2048, "limit": 4096, "stats": {"inactive_file": 512}},
               "networks": {"eth0": {"rx_bytes": 7, "tx_bytes": 9}},
               "blkio_stats": {"io_service_bytes_recursive": [
                   {"op": "Read", "value": 11}, {"op": "Write", "value": 13}]}}
        sample = flatten_store_stats(raw, "abc", limits["container_started_at"], 50,
                                     "2026-11-04T10:00:00+00:00")
        self.assertEqual(sample["cpu_total_ns"], 100)
        self.assertEqual(sample["block_read_bytes"], 11)
        self.assertEqual(sample["network_tx_bytes"], 9)
        self.assertIsNone(sample["throttled_periods"])

    def test_phase_and_rates_do_not_bridge_repetitions(self):
        repetitions = [
            {"repetition": 1, "phase_intervals": {
                "prepare_started_utc": "2026-11-04T09:59:58+00:00",
                "prepare_finished_utc": "2026-11-04T09:59:59+00:00",
                "measure_started_utc": "2026-11-04T10:00:00+00:00",
                "measure_finished_utc": "2026-11-04T10:00:02+00:00"}},
            {"repetition": 2, "phase_intervals": {
                "measure_started_utc": "2026-11-04T10:00:10+00:00",
                "measure_finished_utc": "2026-11-04T10:00:12+00:00"}},
        ]
        self.assertEqual(phase_for("2026-11-04T09:59:58+00:00", repetitions), (1, "prepare"))
        self.assertEqual(phase_for("2026-11-04T10:00:01+00:00", repetitions), (1, "measure"))
        self.assertEqual(phase_for("2026-11-04T10:00:05+00:00", repetitions), (None, "outside"))
        rows = []
        for repetition, offset, cpu in ((1, 0, 0), (1, 1, 1_000_000_000),
                                        (2, 10, 10_000_000_000), (2, 11, 11_000_000_000)):
            rows.append({"role": "store", "status": "ok", "phase": "measure",
                         "repetition": repetition, "sampled_monotonic_ns": offset * 1_000_000_000,
                         "cpu_total_ns": cpu, "memory_usage_bytes": 100 + offset,
                         "container_started_at": "same"})
        summary = resource_summary(rows)
        self.assertEqual(summary["store"]["cpu_cores_mean"], 1.0)
        self.assertEqual(summary["store"]["memory_peak_bytes"], 111)
        self.assertIsNone(summary["client"]["cpu_cores_mean"])

    def test_client_proc_sample(self):
        row = sample_client(os.getpid(), 100, "2026-11-04T10:00:00+00:00")
        self.assertEqual(row["pid"], os.getpid())
        self.assertGreater(row["memory_usage_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
