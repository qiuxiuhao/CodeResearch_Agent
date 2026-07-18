from __future__ import annotations

import argparse
import json

from backend.app.alignment.benchmark import load_alignment_benchmark, load_alignment_predictions
from backend.app.alignment.metrics import evaluate_alignment_predictions


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a versioned paper-code alignment benchmark.")
    parser.add_argument("benchmark")
    parser.add_argument("--predictions")
    parser.add_argument("--output")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    cases = load_alignment_benchmark(args.benchmark)
    summary: dict = {
        "case_count": len(cases),
        "dev_count": sum(item.split == "dev" for item in cases),
        "locked_test_count": sum(item.split == "locked_test" for item in cases),
        "pair_count": len({item.repo_paper_pair_id for item in cases}),
    }
    if args.predictions:
        predictions = load_alignment_predictions(args.predictions)
        summary["metrics"] = evaluate_alignment_predictions(cases, predictions)
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not args.allow_incomplete and (summary["pair_count"] != 6 or summary["case_count"] != 92):
        print("Alignment release gate requires 6 pairs and 92 human-reviewed cases.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
