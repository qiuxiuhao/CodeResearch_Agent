from __future__ import annotations

import json
import os
from pathlib import Path
from shutil import copyfile

from backend.app.image_generation.cache import TeachingDiagramReviewCache
from backend.app.schemas.state import AgentState
from backend.app.schemas.teaching_diagram import TeachingDiagramManifest, TeachingDiagramReview
from backend.app.teaching_diagrams.manifest import atomic_write_manifest, manifest_status


def teaching_diagram_review_vlm_node(state: AgentState) -> AgentState:
    manifest = TeachingDiagramManifest.model_validate(state.get("teaching_diagram_manifest", {}))
    if not manifest.diagrams:
        return state
    cache = TeachingDiagramReviewCache(
        os.getenv("TEACHING_REVIEW_CACHE_PATH", "data/teaching_diagram_review_cache.sqlite3"),
        enabled=os.getenv("TEACHING_REVIEW_CACHE_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
    )
    for item in manifest.diagrams:
        if not state.get("teaching_review_vlm_enabled", False) or not state.get("external_vision_consent", False):
            item.fallback_reason = "teaching_review_disabled_or_not_authorized"
            item.display_variant = "blueprint"
            item.display_asset = item.blueprint_png
            continue
        if item.styled_composite is None or item.final_asset is None:
            item.fallback_reason = "styled_composite_unavailable"
            item.display_variant = "blueprint"
            item.display_asset = item.blueprint_png
            continue
        public_spec_hash = _public_spec_hash(item.spec_path)
        key = {
            "review_provider": "local_mvp",
            "review_model": "local_mvp",
            "review_prompt_version": "1.3.0",
            "review_schema_version": "1.3.0",
            "generated_image_hash": item.styled_composite.sha256,
            "public_spec_hash": public_spec_hash,
        }
        try:
            cached = cache.get(key)
        except Exception:
            cached = None
            manifest.warnings.append({
                "code": "review_cache_error",
                "message": "Teaching diagram review cache read failed.",
                "recoverable": True,
            })
        if cached:
            review = TeachingDiagramReview.model_validate(cached)
            review.metadata["cache_hit"] = True
        else:
            review = TeachingDiagramReview(
                diagram_id=item.diagram_id,
                passed=True,
                overall_score=88,
                accuracy_score=5,
                spec_coverage_score=5,
                label_readability_score=4,
                beginner_clarity_score=4,
                safety_score=5,
                recommendation="pass",
                metadata={"review_mode": "local_mvp", "cache_hit": False},
            )
            try:
                cache.set(key, review.model_dump(mode="json"))
            except Exception:
                manifest.warnings.append({
                    "code": "review_cache_error",
                    "message": "Teaching diagram review cache write failed.",
                    "recoverable": True,
                })
        item.review = review
        item.display_variant = "ai"
        item.display_asset = item.final_asset
        item.fallback_reason = None
        final_path = Path(item.final_asset.path)
        composite_path = Path(item.styled_composite.path)
        if composite_path.is_file() and final_path != composite_path:
            copyfile(composite_path, final_path)
    manifest.status = manifest_status(manifest)  # type: ignore[assignment]
    atomic_write_manifest(Path(state["output_dir"]) / "teaching_diagrams" / "manifest.json", manifest)
    return {**state, "teaching_diagram_manifest": manifest.model_dump(mode="json")}


def _public_spec_hash(spec_path: str) -> str:
    try:
        payload = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        return str(payload.get("public_spec_hash") or "")
    except Exception:
        return ""
