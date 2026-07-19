#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from backend.app.evaluation.alignment_gold import audit_alignment_gold
from backend.app.evaluation.dataset_catalog import load_case_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the human-reviewed Alignment Gold release shape.")
    parser.add_argument("path", nargs="?", default="evaluation/alignment/benchmark_v1.jsonl")
    parser.add_argument("--release", action="store_true", help="Require 4 Dev + 2 Locked and 72/20 cases.")
    args = parser.parse_args()
    cases = load_case_jsonl(args.path)
    audit = audit_alignment_gold(cases, require_release_shape=args.release)
    print(json.dumps(asdict(audit), ensure_ascii=False, sort_keys=True))
    return 0 if audit.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
