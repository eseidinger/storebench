"""Check read-only oracle derivation and offered-load accounting without Docker."""
import importlib.util
import time
import unittest


@unittest.skipUnless(importlib.util.find_spec("psycopg"), "requires document client dependencies")
class DocumentLoadTest(unittest.TestCase):
    def test_read_oracle_uses_initial_fixture(self):
        from benchmarks.documents.conformance import canonical, sha256
        from benchmarks.documents.load import derive_read_requests

        documents = [
            {"id": "a", "category": "gear", "price_cents": 100, "attributes": {"color": "blue"}},
            {"id": "b", "category": "gear", "price_cents": 200, "attributes": {"color": "blue"}},
        ]
        serial = [
            {"sequence": 0, "operation": "P6", "id": "a"},
            {"sequence": 1, "operation": "P1", "id": "a", "access_class": "hot",
             "expected_sha256": "stale-after-write"},
            {"sequence": 2, "operation": "P2", "category": "gear", "attributes": {"color": "blue"},
             "limit": 2, "query": "broad", "expected_ids": []},
            {"sequence": 3, "operation": "P3", "category": "gear", "attributes": {"color": "blue"},
             "limit": 1, "query": "broad", "depth": 2, "after": ["gear", "a"], "expected_ids": []},
            {"sequence": 4, "operation": "P4", "expected_totals": {}},
        ]
        derived = derive_read_requests(documents, serial)
        self.assertEqual([r["sequence"] for r in derived], [0, 1, 2, 3])
        self.assertEqual(derived[0]["expected_sha256"], sha256(canonical(documents[0])))
        self.assertEqual(derived[1]["expected_ids"], ["a", "b"])
        self.assertEqual(derived[2]["expected_ids"], ["b"])
        self.assertEqual(derived[3]["expected_totals"],
                         {"gear": {"count": 2, "price_cents_sum": 300}})

    def test_saturated_schedule_counts_drops(self):
        from benchmarks.documents.conformance import canonical, sha256
        from benchmarks.documents.load import ClientPool, Recorder, run_phase

        class SlowStore:
            name = "fake"

            def point(self, product_id):
                time.sleep(0.02)
                return {"id": product_id}

            def close(self):
                pass

        request = {"sequence": 0, "operation": "P1", "id": "a", "access_class": "hot",
                   "expected_sha256": sha256(canonical({"id": "a"}))}
        pool = ClientPool(SlowStore, 1)
        try:
            summary = run_phase(pool, [request], 200.0, 0.1, Recorder())
        finally:
            pool.close()
        self.assertEqual(summary["offered"], 20)
        self.assertGreater(summary["dropped"], 0)
        self.assertEqual(summary["offered"], summary["completed"] + summary["errors"] + summary["dropped"])
        self.assertAlmostEqual(summary["offered_failure_rate"], summary["dropped"] / summary["offered"])
        self.assertGreater(summary["end_to_end_p95_ns"], 0)
        self.assertEqual(summary["client_connections"], 1)
        self.assertEqual(summary["groups"]["P1:hot"]["errors"], 0)

    def test_preparation_checks_each_read_group_before_timing(self):
        from benchmarks.documents.load import derive_read_requests, prepare_read_paths
        from benchmarks.documents.conformance import CouchDB

        documents = [{"id": "a", "category": "gear", "price_cents": 100,
                      "attributes": {"color": "blue"}}]
        serial = [
            {"sequence": 0, "operation": "P1", "id": "a", "access_class": "hot"},
            {"sequence": 1, "operation": "P1", "id": "a", "access_class": "hot"},
            {"sequence": 2, "operation": "P2", "category": "gear", "attributes": {"color": "blue"},
             "limit": 10, "query": "broad"},
            {"sequence": 3, "operation": "P2", "category": "gear", "attributes": {"color": "red"},
             "limit": 10, "query": "empty"},
            {"sequence": 4, "operation": "P3", "category": "gear", "attributes": {},
             "limit": 10, "depth": 1, "after": None},
            {"sequence": 5, "operation": "P4"},
        ]
        requests = derive_read_requests(documents, serial)

        class FakeStore:
            def __init__(self):
                self.calls = []

            def point(self, product_id):
                self.calls.append("P1")
                return documents[0]

            def filter(self, request):
                self.calls.append(request["operation"])
                return [d for d in documents if d["category"] == request["category"] and
                        all(d["attributes"].get(k) == v for k, v in request["attributes"].items())]

            def totals(self):
                self.calls.append("P4")
                return {"gear": {"count": 1, "price_cents_sum": 100}}

        store = FakeStore()
        preparation, diagnostics = prepare_read_paths(store, requests)
        self.assertEqual(store.calls, ["P4", "P1", "P2", "P2", "P3"])
        self.assertEqual(len(preparation["groups"]), 5)
        self.assertEqual(diagnostics, [])

        query = CouchDB.filter_query(requests[2])
        self.assertEqual(query["use_index"], ["benchmark_category_color_id", "category_color_id"])
        self.assertEqual(query["sort"], [{"category": "asc"},
                                         {"attributes.color": "asc"}, {"id": "asc"}])
        self.assertFalse(query["allow_fallback"])
        fallback = CouchDB.filter_query({**requests[2], "attributes": {"material": "wool"}})
        self.assertEqual(fallback["use_index"], ["benchmark_category_id", "category_id"])


if __name__ == "__main__":
    unittest.main()
