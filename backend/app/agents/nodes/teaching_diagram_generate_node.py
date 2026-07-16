from __future__ import annotations

from pathlib import Path

from backend.app.image_generation.runtime import ImageGenerationRuntime
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.schemas.state import AgentState
from backend.app.schemas.teaching_diagram import (
    TeachingDiagramManifest,
    TeachingDiagramManifestItem,
    TeachingDiagramProviderAttempt,
    TeachingDiagramSpec,
)
from backend.app.teaching_diagrams.blueprint_renderer import BlueprintRenderer
from backend.app.teaching_diagrams.compositor import TeachingDiagramCompositor
from backend.app.teaching_diagrams.manifest import atomic_write_manifest, manifest_status
from backend.app.teaching_diagrams.spec_assembler import public_spec_for_provider
from backend.app.utils.json_utils import save_json


def teaching_diagram_generate_node(
    state: AgentState,
    image_runtime: ImageGenerationRuntime | None = None,
) -> AgentState:
    manifest = TeachingDiagramManifest.model_validate(state.get("teaching_diagram_manifest", {}))
    if not manifest.teaching_diagrams_enabled:
        return state
    root = Path(state["output_dir"]) / "teaching_diagrams"
    task_root = Path(state["output_dir"])
    renderer = BlueprintRenderer()
    compositor = TeachingDiagramCompositor()
    items: list[TeachingDiagramManifestItem] = []
    warnings = list(manifest.warnings)
    for spec_payload in state.get("teaching_diagram_specs", []):
        try:
            spec = TeachingDiagramSpec.model_validate(spec_payload)
            spec_path = root / "specs" / f"{spec.diagram_id}.json"
            save_json(spec_path, spec.model_dump(mode="json"))
            blueprint = renderer.render(spec, root, task_root=task_root)
            generated_raw = None
            provider_attempts: list[TeachingDiagramProviderAttempt] = []
            ai_dir = root / "ai" / spec.diagram_id
            if (
                state.get("image_generation_enabled", False)
                and state.get("external_image_consent", False)
                and image_runtime is not None
                and image_runtime.router.has_available_provider
            ):
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
                ))
                warnings.extend(result.warnings)
                if result.image_path:
                    from backend.app.teaching_diagrams.assets import asset_from_file

                    generated_raw = asset_from_file(result.image_path, result.mime_type or "image/png", relative_to=task_root)
                    provider_attempts.append(TeachingDiagramProviderAttempt(
                        provider=str(result.metadata.get("provider", "unknown")),
                        model=result.metadata.get("model"),
                        status="cache_hit" if result.metadata.get("cache_hit") else "success",
                        latency_ms=result.metadata.get("latency_ms"),
                        cache_hit=bool(result.metadata.get("cache_hit")),
                    ))
                else:
                    provider_attempts.append(TeachingDiagramProviderAttempt(provider="image_router", status="failed"))
            composite = compositor.compose(
                spec=spec,
                blueprint_png=_task_path(task_root, blueprint["png"].path),
                ai_dir=ai_dir,
                generated_raw=_task_path(task_root, generated_raw.path) if generated_raw else None,
                task_root=task_root,
                max_bytes=image_runtime.settings.max_single_image_bytes if image_runtime else 10_485_760,
                max_width=image_runtime.settings.max_width if image_runtime else 1536,
                max_height=image_runtime.settings.max_height if image_runtime else 1536,
            )
            item_warnings = [*blueprint.get("warnings", []), *composite.get("warnings", [])]
            item = TeachingDiagramManifestItem(
                diagram_id=spec.diagram_id,
                title=spec.source_entity.title,
                related_mermaid_diagram_ids=spec.related_mermaid_diagram_ids,
                source_entity=spec.source_entity,
                spec_path=str(spec_path.relative_to(task_root)),
                blueprint_svg=blueprint["svg"],
                blueprint_png=blueprint["png"],
                generated_raw=generated_raw,
                styled_composite=composite["styled_composite"],
                final_asset=None,
                display_variant="blueprint",
                display_asset=blueprint["png"],
                fallback_reason="review_not_enabled_or_not_passed" if generated_raw else "ai_image_unavailable",
                provider_attempts=provider_attempts,
                warnings=item_warnings,
            )
            items.append(item)
        except Exception as exc:
            manifest.errors.append({
                "code": "teaching_diagram_generation_failed",
                "message": type(exc).__name__,
                "recoverable": True,
            })
    manifest.diagrams = items
    manifest.warnings = warnings
    manifest.budget = {
        "teaching_plan": state.get("teaching_plan_budget", {}),
        "teaching_image": image_runtime.budget.snapshot() if image_runtime else state.get("teaching_image_budget", {}),
        "teaching_review": state.get("teaching_review_budget", {}),
    }
    manifest.status = manifest_status(manifest)  # type: ignore[assignment]
    atomic_write_manifest(root / "manifest.json", manifest)
    return {
        **state,
        "teaching_diagram_manifest": manifest.model_dump(mode="json"),
        "teaching_image_budget": manifest.budget.get("teaching_image", {}),
    }


def _task_path(task_root: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else task_root / path
