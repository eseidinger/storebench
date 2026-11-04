"""Check direct measurement records without starting database containers."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("psycopg"), "requires document client dependencies")
class DocumentMeasureTest(unittest.TestCase):
    def test_success_records_and_summary(self):
        from benchmarks.documents.conformance import canonical, sha256
        from benchmarks.documents.measure import measure, summarize

        class Store:
            name = "fake"

            def __init__(self):
                self.documents = {"a": {"id": "a", "version": 1}}

            def point(self, product_id):
                return self.documents.get(product_id)

            def create(self, document):
                self.documents[document["id"]] = document

        new_document = {"id": "b", "version": 1}
        requests = [
            {"sequence": 0, "operation": "P1", "id": "a", "access_class": "hot",
             "expected_sha256": sha256(canonical({"id": "a", "version": 1}))},
            {"sequence": 1, "operation": "P5", "document": new_document,
             "expected_sha256": sha256(canonical(new_document))},
            {"sequence": 2, "operation": "P1", "id": "b", "access_class": "uniform",
             "expected_sha256": sha256(canonical(new_document))},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.jsonl"
            records = measure(Store(), requests, path)
            self.assertEqual(records, [json.loads(line) for line in path.read_text().splitlines()])
        self.assertEqual([row["status"] for row in records], ["ok"] * 3)
        self.assertTrue(all(row["elapsed_ns"] > 0 and row["validation_ns"] >= 0 for row in records))
        self.assertIsNone(records[1]["logical_result_bytes"])
        summary = summarize(records)
        self.assertEqual(summary["P1:hot"]["count"], 1)
        self.assertEqual(summary["P1:uniform"]["count"], 1)
        self.assertEqual(summary["P5"]["count"], 1)

    def test_failed_validation_is_recorded(self):
        from benchmarks.documents.measure import measure, summarize

        class Store:
            name = "fake"

            def point(self, product_id):
                return {"id": product_id}

        request = {"sequence": 0, "operation": "P1", "id": "a",
                   "access_class": "hot", "expected_sha256": "invalid"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.jsonl"
            with self.assertRaisesRegex(RuntimeError, "sequence 0 P1"):
                measure(Store(), [request], path)
            row = json.loads(path.read_text().splitlines()[0])
        self.assertEqual(row["status"], "error")
        self.assertGreater(row["elapsed_ns"], 0)
        self.assertEqual(summarize([row])["P1:hot"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
