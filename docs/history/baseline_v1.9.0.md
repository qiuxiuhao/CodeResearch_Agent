# CodeResearch Agent v1.9.0 baseline

Verified on 2026-07-19 before v2.0 development.

## Source identity

- Branch at verification: `main`
- Commit: `d869f88e2c0132fae7cf52adc7def28f946751c1`
- Commit subject: `feat: implement evaluation and regression loop v1.9.0`
- Worktree: clean
- Release tag: annotated tag `v1.9.0` created after validation and points to the commit above
- Python: `/Users/qiu_star/miniforge3/envs/code-research-agent/bin/python`, CPython 3.11.15
- Node.js: 24.15.0

The full commit SHA, not the tag label or a worktree patch, is the reproducible source identity.

## Validation evidence

`bash scripts/validate.sh` completed successfully:

- Backend: 413 passed, 6 warnings
- Frontend: 18 files / 31 tests passed
- Frontend typecheck and production build: passed
- Build contract: passed

The warnings are dependency deprecations from Starlette/httpx and SWIG-backed packages. The frontend build also reports large Mermaid-related chunks; neither warning failed the release contract.

## Capability baseline

v1.9 includes the v1.4 structured fact/index contracts, v1.5 retrieval ordering and generation isolation, v1.6 Research Agent run/checkpoint/recovery contracts, v1.7 paper-code alignment stores and review contracts, v1.8 metadata-only observability, and v1.9 evaluation datasets, metrics, comparisons, gates, bad-case lifecycle, replay manifests, API, and dashboard.

The v2.0 implementation must preserve business IDs, retrieval ordering, evidence authority, run terminal semantics, checkpoint recovery, alignment decisions, trace privacy/completeness, evaluation immutability, and Recorder on/off equivalence.

## Known release blocker

`ALIGNMENT_BENCHMARK_PENDING` remains open:

- Alignment Dev pairs with human gold: 0
- Alignment Locked pairs with human gold: 0
- No system output, legacy alignment output, or LLM output is accepted as human gold.

This debt does not block v2.0 infrastructure work, but it blocks v2.0 RC and GA until the authorized six-pair dataset is independently double-annotated, adjudicated, frozen, and evaluated.

