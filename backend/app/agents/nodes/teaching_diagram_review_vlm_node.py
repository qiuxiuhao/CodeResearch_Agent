from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from shutil import copyfile

from backend.app.image_generation.cache import TeachingDiagramReviewCache
from backend.app.image_generation.runtime import ImageGenerationRuntime
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.llm.budget import BudgetManager
from backend.app.schemas.state import AgentState
from backend.app.schemas.teaching_diagram import (
    TeachingDiagramManifest,
    TeachingDiagramProviderAttempt,
    TeachingDiagramReview,
    TeachingDiagramSpec,
)
from backend.app.teaching_diagrams.assets import asset_from_file
from backend.app.teaching_diagrams.compositor import TeachingDiagramCompositor
from backend.app.teaching_diagrams.manifest import atomic_write_manifest, manifest_status
from backend.app.teaching_diagrams.spec_assembler import public_spec_for_provider
from backend.app.vision.router import VisionModelRouter
from backend.app.vision.runtime import VisionRuntime


REVIEW_PROMPT_VERSION = os.getenv("TEACHING_REVIEW_PROMPT_VERSION", "1.3.2")
REVIEW_SCHEMA_VERSION = os.getenv("TEACHING_REVIEW_SCHEMA_VERSION", "1.3.2")


def teaching_diagram_review_vlm_node(
    state: AgentState,
    vision_runtime: VisionRuntime | None = None,
    image_runtime: ImageGenerationRuntime | None = None,
) -> AgentState:
    manifest = TeachingDiagramManifest.model_validate(state.get("teaching_diagram_manifest", {}))
    if not manifest.diagrams:
        return state
    task_root = Path(state["output_dir"])
    cache = TeachingDiagramReviewCache(
        os.getenv("TEACHING_REVIEW_CACHE_PATH", "data/teaching_diagram_review_cache.sqlite3"),
        enabled=os.getenv("TEACHING_REVIEW_CACHE_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
    )
    review_budget = BudgetManager(4, int(os.getenv("TEACHING_REVIEW_MAX_PROVIDER_REQUESTS", manifest.budget.get("teaching_review", {}).get("max_provider_requests", 8))))
    review_router = None
    if vision_runtime is not None:
        review_router = VisionModelRouter(vision_runtime.settings, vision_runtime.router.providers, review_budget, vision_runtime.router.cache)

    for item in manifest.diagrams:
        _ensure_blueprint_default(item)
        if not state.get("teaching_review_vlm_enabled", False):
            _fallback(item, "teaching_review_disabled")
            continue
        if not state.get("external_vision_consent", False):
            _fallback(item, "external_vision_consent_missing")
            item.warnings.append("external_vision_consent_missing")
            continue
        if review_router is None or not review_router.has_available_provider:
            _fallback(item, "vision_provider_unavailable")
            item.warnings.append("vision_provider_unavailable")
            continue
        if not item.generated_raw or not item.styled_composite:
            _fallback(item, "styled_composite_unavailable")
            item.warnings.append("review_skipped_without_raw_or_composite")
            continue
        spec = TeachingDiagramSpec.model_validate(json.loads(_task_path(task_root, item.spec_path).read_text(encoding="utf-8")))
        review = _review_once(
            item=item,
            spec=spec,
            task_root=task_root,
            cache=cache,
            router=review_router,
            review_budget=review_budget,
            manifest=manifest,
        )
        if review and _review_passed(review):
            _accept_ai(item, task_root)
            item.review = review
            continue
        if review:
            item.review = review
        if _can_seedream_retry(item, image_runtime):
            regenerated = _regenerate_with_seedream(
                item=item,
                spec=spec,
                task_root=task_root,
                image_runtime=image_runtime,
                manifest=manifest,
            )
            if regenerated:
                review = _review_once(
                    item=item,
                    spec=spec,
                    task_root=task_root,
                    cache=cache,
                    router=review_router,
                    review_budget=review_budget,
                    manifest=manifest,
                )
                if review:
                    item.review = review
                if review and _review_passed(review):
                    _accept_ai(item, task_root)
                    continue
        _fallback(item, "review_failed_fallback_blueprint")

    manifest.status = manifest_status(manifest)  # type: ignore[assignment]
    manifest.budget["teaching_review"] = review_budget.snapshot()
    if image_runtime:
        manifest.budget["teaching_image"] = image_runtime.budget.snapshot()
    atomic_write_manifest(task_root / "teaching_diagrams" / "manifest.json", manifest)
    return {
        **state,
        "teaching_diagram_manifest": manifest.model_dump(mode="json"),
        "teaching_review_budget": review_budget.snapshot(),
        "teaching_image_budget": manifest.budget.get("teaching_image", state.get("teaching_image_budget", {})),
    }


def _review_once(
    *,
    item,
    spec: TeachingDiagramSpec,
    task_root: Path,
    cache: TeachingDiagramReviewCache,
    router: VisionModelRouter,
    review_budget: BudgetManager,
    manifest: TeachingDiagramManifest,
) -> TeachingDiagramReview | None:
    composite_path = _task_path(task_root, item.styled_composite.path)
    if not composite_path.is_file():
        item.warnings.append("styled_composite_unavailable")
        return None
    image_bytes = composite_path.read_bytes()
    public_spec = public_spec_for_provider(spec)
    public_spec_hash = str(public_spec.get("public_spec_hash") or spec.public_spec_hash)
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    for provider in [provider for provider in router.providers if provider.configured]:
        key = _review_cache_key(provider.name, provider.model, image_hash, public_spec_hash)
        try:
            cached = cache.get(key)
        except Exception:
            cached = None
            manifest.warnings.append(_warning("review_cache_error", item.diagram_id))
        if cached:
            review = _validated_cached_review(cached, item.diagram_id, manifest)
            if review is not None:
                review.metadata["cache_hit"] = True
                review_budget.record_cache_hit()
                return review
    result = router.analyze_structured_image(
        context_id=item.diagram_id,
        system_prompt=_review_prompt(),
        input_payload={
            "diagram_id": item.diagram_id,
            "public_spec": public_spec,
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "instructions": "Return only TeachingDiagramReview JSON. Do not infer facts outside public_spec.",
        },
        image_bytes=image_bytes,
        mime_type=item.styled_composite.mime_type,
        response_model=TeachingDiagramReview,
        task_type="teaching_diagram_review",
        prompt_version=REVIEW_PROMPT_VERSION,
        validator=lambda value: _validate_review(value, item.diagram_id),
    )
    manifest.warnings.extend(result.warnings)
    if result.value is None:
        item.warnings.append("review_provider_failed")
        return None
    review = _enforce_review_policy(TeachingDiagramReview.model_validate(result.value.model_dump(mode="json")))
    provider = str(review.metadata.get("provider") or "unknown")
    model = str(review.metadata.get("model") or "unknown")
    try:
        cache.set(_review_cache_key(provider, model, image_hash, public_spec_hash), review.model_dump(mode="json"))
    except Exception:
        manifest.warnings.append(_warning("review_cache_error", item.diagram_id))
    return review


def _regenerate_with_seedream(
    *,
    item,
    spec: TeachingDiagramSpec,
    task_root: Path,
    image_runtime: ImageGenerationRuntime | None,
    manifest: TeachingDiagramManifest,
) -> bool:
    if image_runtime is None:
        return False
    ai_dir = task_root / "teaching_diagrams" / "ai" / item.diagram_id
    result = image_runtime.router.generate(ImageGenerationRequest(
        diagram_id=spec.diagram_id,
        public_spec=public_spec_for_provider(spec),
        prompt_version=image_runtime.settings.prompt_version,
        schema_version=image_runtime.settings.schema_version,
        width=1280,
        height=720,
        mime_type="image/png",
        max_output_bytes=image_runtime.settings.max_single_image_bytes,
        output_dir=ai_dir,
    ), provider_names=["seedream"])
    manifest.warnings.extend(result.warnings)
    if not result.image_path:
        item.provider_attempts.append(TeachingDiagramProviderAttempt(provider="seedream", status="failed"))
        return False
    item.generated_raw = asset_from_file(result.image_path, result.mime_type or "image/png", relative_to=task_root)
    item.provider_attempts.append(TeachingDiagramProviderAttempt(
        provider=str(result.metadata.get("provider", "seedream")),
        model=result.metadata.get("model"),
        status="cache_hit" if result.metadata.get("cache_hit") else "success",
    ))
    composite = TeachingDiagramCompositor().compose(
        spec=spec,
        blueprint_png=_task_path(task_root, item.blueprint_png.path) if item.blueprint_png else task_root,
        ai_dir=ai_dir,
        generated_raw=result.image_path,
        task_root=task_root,
        max_bytes=image_runtime.settings.max_single_image_bytes,
        max_width=image_runtime.settings.max_width,
        max_height=image_runtime.settings.max_height,
    )
    item.warnings.extend(composite.get("warnings", []))
    item.styled_composite = composite.get("styled_composite")
    item.final_asset = None
    return item.styled_composite is not None


def _accept_ai(item, task_root: Path) -> None:
    if not item.styled_composite:
        _fallback(item, "styled_composite_unavailable")
        return
    styled = _task_path(task_root, item.styled_composite.path)
    final = task_root / "teaching_diagrams" / "ai" / item.diagram_id / "final.png"
    final.parent.mkdir(parents=True, exist_ok=True)
    copyfile(styled, final)
    item.final_asset = asset_from_file(final, "image/png", relative_to=task_root)
    item.display_variant = "ai"
    item.display_asset = item.final_asset
    item.fallback_reason = None


def _fallback(item, reason: str) -> None:
    item.display_variant = "blueprint"
    item.display_asset = item.blueprint_svg if "teaching_diagram_font_unavailable" in item.warnings and item.blueprint_svg else item.blueprint_png
    item.fallback_reason = reason


def _ensure_blueprint_default(item) -> None:
    if item.display_asset is None:
        item.display_asset = item.blueprint_png
    item.display_variant = "blueprint"


def _review_passed(review: TeachingDiagramReview) -> bool:
    return review.passed and review.recommendation == "pass"


def _enforce_review_policy(review: TeachingDiagramReview) -> TeachingDiagramReview:
    passed = (
        review.passed
        and review.overall_score >= 80
        and review.accuracy_score >= 4
        and review.spec_coverage_score >= 4
        and review.label_readability_score >= 4
        and review.beginner_clarity_score >= 4
        and review.safety_score == 5
        and not review.missing_required_items
        and not review.hallucinated_items
        and not review.incorrect_shapes
        and not review.incorrect_formulas
        and not review.unreadable_labels
    )
    return review.model_copy(update={
        "passed": passed,
        "recommendation": "pass" if passed else "fallback_blueprint",
    })


def _validated_cached_review(cached: dict, diagram_id: str, manifest: TeachingDiagramManifest) -> TeachingDiagramReview | None:
    try:
        review = TeachingDiagramReview.model_validate(cached)
        _validate_review(review, diagram_id)
        return _enforce_review_policy(review)
    except Exception:
        manifest.warnings.append(_warning("review_cache_error", diagram_id))
        return None


def _validate_review(value, diagram_id: str) -> None:
    if getattr(value, "diagram_id", None) != diagram_id:
        raise ValueError("VLM returned review for an unexpected diagram_id.")


def _can_seedream_retry(item, image_runtime: ImageGenerationRuntime | None) -> bool:
    if image_runtime is None:
        return False
    return not any(attempt.provider == "seedream" and attempt.status in {"success", "cache_hit"} for attempt in item.provider_attempts)


def _review_cache_key(provider: str, model: str, image_hash: str, public_spec_hash: str) -> dict:
    return {
        "review_provider": provider,
        "review_model": model,
        "review_prompt_version": REVIEW_PROMPT_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "generated_image_hash": image_hash,
        "public_spec_hash": public_spec_hash,
    }


def _review_prompt() -> str:
    return (
        "You are reviewing a locally composited teaching diagram image. "
        "Use the public_spec as the source of truth. Check only the visible styled_composite image. "
        "Fail the image if it shows hallucinated modules, wrong arrows, wrong tensor shapes, wrong formulas, "
        "unsafe content, or unreadable critical labels. Return strict JSON matching TeachingDiagramReview."
    )


def _task_path(task_root: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else task_root / path


def _warning(code: str, diagram_id: str) -> dict:
    return {
        "code": code,
        "task_type": "teaching_diagram_review",
        "context_id": diagram_id,
        "message": code.replace("_", " "),
        "recoverable": True,
    }
