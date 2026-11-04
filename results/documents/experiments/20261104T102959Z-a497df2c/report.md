# Document read-only experiment

Runs: 6; execution complete: False.

A point qualifies only when every independent run passes correctness, latency, failure,
resource and sampling checks. Run p95 values are summarized by median and range;
raw request percentiles are never pooled or averaged across runs.

## Highest tested qualifying load

| Store | Workers | Offered/s | Completed/s (median) | Top rate qualifies |
| --- | ---: | ---: | ---: | --- |
| postgres | 1 | 5 | 5.0 | True |
| couchdb | 1 | None | None | False |

A qualifying highest configured rate leaves the capacity ceiling unbracketed.

## Matrix

| Store | Workers | Offered/s | Qualifies | Runs | Completed/s median [range] | Run p95 ms median [range] |
| --- | ---: | ---: | --- | ---: | --- | --- |
| couchdb | 1 | 5 | False | 1/1 | 2.6666666666666665 [2.6666666666666665, 2.6666666666666665] | 994.877834 [994.877834, 994.877834] |
| postgres | 1 | 5 | True | 1/1 | 5.0 [5.0, 5.0] | 15.996796 [15.996796, 15.996796] |

## Sampler overhead

Ratios compare paired runs at the same offered rate; 1.0 means no measured change.

| Store | Complete pairs | p95 on/off median | Throughput on/off median |
| --- | ---: | ---: | ---: |
| postgres | 1 | 1.1319912291806429 | 1.0 |
| couchdb | 0 | None | None |

See report.json and each run's orchestration.json, load/manifest.json and operations.jsonl.
