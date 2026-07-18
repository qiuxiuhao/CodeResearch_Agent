# Alignment Benchmark v1

The catalog freezes four Dev and two Locked Test pair slots. `benchmark_v1.jsonl` must only contain
human-reviewed gold tied to immutable repository/index/paper fixtures. The implementation refuses duplicate
case IDs, pair leakage across splits, and contradictory no-implementation labels.

No current alignment system or LLM may generate gold labels. The release gate remains open until the six
authorized pairs and 92 double-reviewed cases described in `plan/plan_v1.7.0.md` are supplied.
