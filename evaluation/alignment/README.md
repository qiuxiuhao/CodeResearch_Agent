# Alignment Benchmark v1

The catalog freezes four Dev and two Locked Test pair slots. `benchmark_v1.jsonl` must only contain
human-reviewed gold tied to immutable repository/index/paper fixtures. The implementation refuses duplicate
case IDs, pair leakage across splits, and contradictory no-implementation labels.

No current alignment system or LLM may generate gold labels. The release gate remains open until the six
authorized pairs and 92 double-reviewed cases described in `plan/plan_v1.7.0.md` are supplied.

v1.9 keeps this debt under the stable identifier `ALIGNMENT_BENCHMARK_PENDING`. The deterministic suite in
`backend/app/evaluation/mock_runner.py` is a synthetic contract test only and cannot close the debt. Validate
future human Gold with:

```bash
python scripts/validate_alignment_gold.py evaluation/alignment/benchmark_v1.jsonl --release
```

Release readiness requires four Dev pairs, two Locked Test pairs, 72 positive cases, 20 confirmed negative
cases, two distinct annotator hashes per case, and agreed/adjudicated labels. System output, Legacy Alignment,
and LLM proposals are rejected as Gold sources.
