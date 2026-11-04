"""Check reproducibility and the serial reference trace of the document fixture."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_document_workload.py"
PROFILE = ROOT / "workloads/documents/profiles/storefront-v1.json"


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def hash_document(document):
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class DocumentWorkloadGeneratorTest(unittest.TestCase):
    def test_reproducible_serial_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            profile = json.loads(PROFILE.read_text())
            profile["document_count"] = 1000
            profile["request_count"] = 100
            profile_path = base / "profile.json"
            profile_path.write_text(json.dumps(profile))
            for output in (base / "first", base / "second"):
                subprocess.run([sys.executable, str(SCRIPT), "--profile", str(profile_path),
                                "--output", str(output)], check=True, capture_output=True)
            first, second = base / "first", base / "second"
            for filename in ("documents.jsonl", "requests.jsonl", "manifest.json"):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

            manifest = json.loads((first / "manifest.json").read_text())
            for artifact in manifest["files"].values():
                self.assertEqual(hashlib.sha256((first / artifact["file"]).read_bytes()).hexdigest(),
                                 artifact["sha256"])
            documents = rows(first / "documents.jsonl")
            requests = rows(first / "requests.jsonl")
            self.assertEqual(len(documents), 1000)
            self.assertEqual(len(requests), 100)
            self.assertEqual(len({p["id"] for p in documents}), 1000)
            self.assertTrue(all(512 <= len(json.dumps(p, sort_keys=True, ensure_ascii=False,
                                                    separators=(",", ":")).encode()) <= 2048
                                for p in documents))

            state = {p["id"]: p for p in documents}
            for sequence, request in enumerate(requests):
                self.assertEqual(request["sequence"], sequence)
                operation = request["operation"]
                if operation == "P1":
                    actual = state.get(request["id"])
                    self.assertEqual(request["expected_sha256"], hash_document(actual) if actual else None)
                elif operation in ("P2", "P3"):
                    results = sorted((p for p in state.values() if p["category"] == request["category"]
                                      and all(p["attributes"].get(key) == value
                                              for key, value in request["attributes"].items())),
                                     key=lambda p: (p["category"], p["id"]))
                    if operation == "P3":
                        after = request["after"]
                        results = [p for p in results if after is None or
                                   [p["category"], p["id"]] > after]
                    self.assertEqual([p["id"] for p in results[:request["limit"]]], request["expected_ids"])
                    self.assertEqual(hashlib.sha256(json.dumps(results[:request["limit"]], sort_keys=True,
                                           ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                                     request["expected_result_sha256"])
                elif operation == "P4":
                    totals = {}
                    for product in state.values():
                        row = totals.setdefault(product["category"], {"count": 0, "price_cents_sum": 0})
                        row["count"] += 1
                        row["price_cents_sum"] += product["price_cents"]
                    self.assertEqual(totals, request["expected_totals"])
                elif operation == "P5":
                    state[request["document"]["id"]] = request["document"]
                elif operation == "P6":
                    product = state[request["id"]]
                    self.assertEqual(product["version"], request["if_version"])
                    product["attributes"][request["attribute"]] = request["value"]
                    product["version"] += 1
                    self.assertEqual(hash_document(product), request["expected_sha256"])
                elif operation == "P7":
                    product = state[request["id"]]
                    self.assertEqual(product["version"], request["if_version"])
                    product["stock"] += request["delta"]
                    product["version"] += 1
                    self.assertGreaterEqual(product["stock"], 0)
                    self.assertEqual(hash_document(product), request["expected_sha256"])


if __name__ == "__main__":
    unittest.main()
