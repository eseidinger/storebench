"""Check experiment ordering, gates and per-run aggregation without Docker."""
import unittest

from benchmarks.documents.experiment import schedule, summarize, validate_plan


def plan():
    return {"version": 1, "input_profile": "storefront-v1", "seed": 42,
            "concurrencies": [1], "rates_per_second": [5, 20],
            "repetitions": 2, "warmup_seconds": 0, "measure_seconds": 2,
            "latency_target_ms": 100, "max_failure_rate": 0.001,
            "sample_interval_seconds": 0.25, "max_sample_interval_factor": 2.5,
            "sampler_overhead": {"concurrency": 1, "rate_per_second": 5, "pairs": 1}}


class ExperimentTest(unittest.TestCase):
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

    def test_invalid_plan(self):
        bad = plan()
        bad["concurrencies"] = [1, 1]
        with self.assertRaises(ValueError):
            validate_plan(bad)


if __name__ == "__main__":
    unittest.main()
