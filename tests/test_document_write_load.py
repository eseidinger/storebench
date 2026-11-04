"""Check deterministic write traces, bounded conflicts and final-state invariants."""
import copy
import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.documents.write_load import execute_write, make_requests, validate_profile, verify_final


def product(product_id, stock=2):
    return {"id": product_id, "name": "Product", "category": "gear", "price_cents": 100,
            "stock": stock, "version": 1, "attributes": {"color": "blue"}}


class WriteLoadTest(unittest.TestCase):
    def test_versioned_profiles_cover_their_phase_durations(self):
        root = Path(__file__).resolve().parents[1]
        profiles = root / "workloads/documents/profiles"
        for name in ("catalog-maintenance-write-v1", "contested-stock-write-v1"):
            with self.subTest(profile=name):
                profile = json.loads((profiles / f"{name}.json").read_text())
                documents = [product(f"p{number:06d}") for number in range(100)]
                validate_profile(profile, documents)
                offered = math.ceil(profile["rate_per_second"] * max(profile["warmup_seconds"],
                                                                     profile["measure_seconds"]))
                self.assertGreaterEqual(profile["request_count"], offered)
                self.assertEqual((profile["warmup_seconds"], profile["measure_seconds"],
                                  profile["repetitions"]), (30, 60, 3))
                self.assertEqual(len(make_requests(profile, documents)), profile["request_count"])

    def test_trace_is_deterministic_and_uses_reserved_create_ids(self):
        profile = {"version": 1, "name": "test", "seed": 7, "input_profile": "storefront-v1",
                   "request_count": 200, "operation_percent": {"P5": 20, "P6": 30, "P7": 50},
                   "hot_key_count": 2, "duplicate_create_percent": 0,
                   "negative_stock_percent": 50, "rate_per_second": 20,
                   "concurrency": 2, "warmup_seconds": 0, "measure_seconds": 2,
                   "repetitions": 1, "max_attempts": 3, "retry_backoff_ms": 0,
                   "latency_target_ms": 100, "max_failure_rate": 0.1}
        documents = [product("a"), product("b"), product("c")]
        self.assertEqual(validate_profile(profile, documents), profile)
        requests = make_requests(profile, documents)
        self.assertEqual(requests, make_requests(profile, documents))
        self.assertEqual(sum(r["operation"] == "P5" for r in requests), 40)
        self.assertEqual(sum(r["operation"] == "P6" for r in requests), 60)
        self.assertEqual(sum(r["operation"] == "P7" for r in requests), 100)
        self.assertEqual(len({r["document"]["id"] for r in requests if r["operation"] == "P5"}), 40)
        self.assertTrue(all(r.get("id") in ("a", "b") for r in requests
                            if r["operation"] in ("P6", "P7")))

    def test_conflict_is_retried_and_stock_floor_rejects(self):
        request = {"operation": "P7", "id": "a", "delta": -1}
        with patch("benchmarks.documents.write_load.read_for_cas", side_effect=[product("a"), product("a")]), \
             patch("benchmarks.documents.write_load.cas_once", side_effect=[False, True]) as cas:
            result = execute_write(object(), request, 3, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["after_stock"], 1)
        self.assertEqual(cas.call_count, 2)
        with patch("benchmarks.documents.write_load.read_for_cas", return_value=product("a", 0)), \
             patch("benchmarks.documents.write_load.cas_once") as cas:
            rejected = execute_write(object(), request, 3, 0)
        self.assertEqual(rejected["status"], "condition_rejected")
        cas.assert_not_called()

    def test_final_state_reconstructs_confirmed_updates_only(self):
        initial = product("a", 1)
        requests = [{"sequence": 0, "operation": "P6", "id": "a"},
                    {"sequence": 1, "operation": "P7", "id": "a", "delta": -1},
                    {"sequence": 2, "operation": "P7", "id": "a", "delta": -1},
                    {"sequence": 3, "operation": "P5", "document": product("new"),
                     "duplicate_expected": False}]
        rows = [{"sequence": 0, "operation": "P6", "status": "ok",
                 "before_version": 1, "after_version": 2,
                 "before_stock": 1, "after_stock": 1},
                {"sequence": 1, "operation": "P7", "status": "ok",
                 "before_version": 2, "after_version": 3,
                 "before_stock": 1, "after_stock": 0},
                {"sequence": 2, "operation": "P7", "status": "condition_rejected",
                 "observed_stock": 0},
                {"sequence": 3, "operation": "P5", "status": "ok"}]
        actual = copy.deepcopy(initial)
        actual["attributes"]["featured"] = True
        actual["stock"] = 0
        actual["version"] = 3

        class FakeStore:
            def point(self, product_id):
                return {"a": actual, "new": product("new")}.get(product_id)

        validation = verify_final(FakeStore(), [initial], requests, rows)
        self.assertEqual(validation["verified_documents"], 2)
        self.assertEqual(validation["created_documents"], 1)
        actual["stock"] = 1
        with self.assertRaisesRegex(RuntimeError, "Final document mismatch"):
            verify_final(FakeStore(), [initial], requests, rows)


if __name__ == "__main__":
    unittest.main()
