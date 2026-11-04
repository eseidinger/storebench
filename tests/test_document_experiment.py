"""Check experiment ordering, gates and per-run aggregation without Docker."""
import json
import unittest
from pathlib import Path

from benchmarks.documents.experiment import markdown_report, schedule, summarize, validate_plan


def plan():
    return {"version": 1, "input_profile": "storefront-v1", "seed": 42,
            "concurrencies": [1], "rates_per_second": [5, 20],
            "repetitions": 2, "warmup_seconds": 0, "measure_seconds": 2,
            "latency_target_ms": 100, "max_failure_rate": 0.001,
            "sample_interval_seconds": 0.25, "max_sample_interval_factor": 2.5,
            "sampler_overhead": {"concurrency": 1, "rate_per_second": 5, "pairs": 1}}


class ExperimentTest(unittest.TestCase):
    def test_quick_profiles_schedule_one_run_per_store(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("read-only-quick-v1", "catalog-maintenance-write-quick-v1",
                     "contested-stock-write-quick-v1"):
            with self.subTest(profile=name):
                path = root / "workloads/documents/profiles" / f"{name}.json"
                quick = validate_plan(json.loads(path.read_text()))
                self.assertEqual(quick["input_profile"], "storefront-quick-v1")
                self.assertEqual(quick["sampler_overhead"], {"pairs": 0})
                self.assertEqual(len(schedule(quick)), 2)
                self.assertEqual({step["store"] for step in schedule(quick)},
                                 {"postgres", "couchdb"})

    def test_write_profiles_cover_highest_rate_and_schedule_both_stores(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("catalog-maintenance-write-v1", "contested-stock-write-v1"):
            with self.subTest(profile=name):
                path = root / "workloads/documents/profiles" / f"{name}.json"
                write_plan = validate_plan(json.loads(path.read_text()))
                self.assertEqual(write_plan["workload"], "write")
                self.assertEqual(len(schedule(write_plan)), 62)
                self.assertEqual({step["store"] for step in schedule(write_plan)},
                                 {"postgres", "couchdb"})

    def test_write_profile_supports_short_experiment_settings(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "workloads/documents/profiles/contested-stock-write-v1.json"
        source = json.loads(path.read_text())
        source.update(repetitions=1, warmup_seconds=0.5, measure_seconds=3,
                      latency_target_ms=200, max_failure_rate=0.1)
        resolved = validate_plan(source)
        self.assertEqual(resolved["repetitions"], 1)
        self.assertEqual(resolved["warmup_seconds"], 0.5)
        self.assertEqual(resolved["measure_seconds"], 3)
        self.assertEqual(resolved["latency_target_ms"], 200)
        self.assertEqual(resolved["max_failure_rate"], 0.1)
        self.assertEqual(source["input_profile"], "storefront-v1")

    def test_schedule_balances_order_and_pairs(self):
        steps = schedule(validate_plan(plan()))
        self.assertEqual(steps, schedule(plan()))
        self.assertEqual(len(steps), 12)
        for offset in (0, 4):
            self.assertEqual(steps[offset]["store"], steps[offset + 3]["store"])
            self.assertNotEqual(steps[offset]["store"], steps[offset + 2]["store"])
        for store in ("postgres", "couchdb"):
            pair = [step for step in steps if step["kind"] == "overhead" and step["store"] == store]
            self.assertEqual({step["sampler_enabled"] for step in pair}, {True, False})

    def test_report_uses_independent_run_gates_and_rates(self):
        results = []
        for step in schedule(plan()):
            result = {**step, "status": "passed", "qualifies": True,
                      "setup_ns": 2_000_000_000,
                      "preparation": {"elapsed_ns": 1_000_000_000,
                                      "storage": {"index_file_bytes": 1_048_576}},
                      "measure": {"completed_within_window_per_second": step["rate_per_second"],
                                  "end_to_end_p95_ns": 10_000_000}}
            if step["kind"] == "matrix" and step["store"] == "postgres" and \
               step["rate_per_second"] == 20 and step["repetition"] == 2:
                result["qualifies"] = False
            results.append(result)
        report = summarize(results, plan())
        postgres = next(row for row in report["capacity"] if row["store"] == "postgres")
        couchdb = next(row for row in report["capacity"] if row["store"] == "couchdb")
        self.assertEqual(postgres["highest_tested_qualifying_rate"], 5)
        self.assertEqual(couchdb["highest_tested_qualifying_rate"], 20)
        self.assertTrue(couchdb["highest_configured_rate_qualifies"])
        self.assertEqual(report["sampler_overhead"][0]["p95_ratio_median"], 1)
        self.assertEqual(report["matrix"][0]["index_file_mib_median"], 1)
        self.assertEqual(report["matrix"][0]["setup_seconds_median"], 2)
        rendered = markdown_report({"runs": results, "summary": report})
        self.assertIn("## Setup and index footprint", rendered)
        self.assertIn("| couchdb | 1 | 5 | 2.0 | 1.0 | 1.0 |", rendered)

    def test_invalid_plan(self):
        bad = plan()
        bad["concurrencies"] = [1, 1]
        with self.assertRaises(ValueError):
            validate_plan(bad)

    def test_write_report_keeps_conflicts_and_business_rejections_separate(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "workloads/documents/profiles/catalog-maintenance-write-v1.json"
        write_plan = json.loads(path.read_text())
        write_plan.update(concurrencies=[8], rates_per_second=[20], repetitions=1)
        write_plan["sampler_overhead"]["pairs"] = 1
        rows = []
        for step in schedule(validate_plan(write_plan)):
            rows.append({**step, "status": "passed", "qualifies": True,
                         "setup_ns": 1_000_000_000,
                         "preparation": {"elapsed_ns": 2_000_000_000,
                                         "storage": {"index_file_bytes": 1_048_576}},
                         "measure": {"completed_within_window_per_second": 18,
                                     "end_to_end_p95_ns": 20_000_000,
                                     "technical_failure_rate": 0.05, "conflicts": 4,
                                     "statuses": {"ok": 18, "conflict_exhausted": 1,
                                                  "condition_rejected": 1}}})
        summary = summarize(rows, write_plan)
        self.assertEqual(summary["matrix"][0]["conflicts_per_run_median"], 4)
        self.assertEqual(summary["matrix"][0]["condition_rejected_per_run_median"], 1)
        rendered = markdown_report({"workload": "write", "runs": rows, "summary": summary})
        self.assertIn("# Document concurrent-write experiment", rendered)
        self.assertIn("## Write outcomes", rendered)
        self.assertIn("Stock rejected", rendered)


if __name__ == "__main__":
    unittest.main()
