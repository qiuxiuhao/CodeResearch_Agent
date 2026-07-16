from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.agents.nodes.teaching_diagram_generate_node import teaching_diagram_generate_node
from backend.app.agents.nodes.teaching_diagram_plan_node import teaching_diagram_plan_node
from backend.app.agents.nodes.teaching_diagram_review_vlm_node import teaching_diagram_review_vlm_node
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.providers.seedream_provider import SeedreamProvider
from backend.app.image_generation.runtime import create_image_generation_runtime
from backend.app.vision.config import VisionSettings
from backend.app.vision.providers.glm_v_provider import GLMVProvider
from backend.app.vision.providers.qwen_vl_provider import QwenVLProvider
from backend.app.vision.runtime import create_vision_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual image-generation smoke test. This may incur cost.")
    parser.add_argument("--provider", choices=["qwen_image", "seedream"], required=True)
    parser.add_argument("--review", action="store_true", help="Run VLM Review after image generation and local composition.")
    parser.add_argument("--review-provider", choices=["qwen_vl", "glm_v"], default="qwen_vl")
    parser.add_argument("--output-root", default="/tmp/code_research_agent_smoke_image")
    parser.add_argument("--i-understand-cost", action="store_true", required=True)
    parser.add_argument("--i-understand-image-transfer", action="store_true", required=True)
    args = parser.parse_args()
    if not args.i_understand_cost:
        raise SystemExit("Pass --i-understand-cost to acknowledge the real external request and possible fee.")
    if not args.i_understand_image_transfer:
        raise SystemExit("Pass --i-understand-image-transfer to acknowledge the sanitized public teaching spec may be sent to the image provider.")

    settings = ImageGenerationSettings.from_env(True, external_image_consent=True, teaching_review_vlm_enabled=args.review).model_copy(update={
        "cache_enabled": False,
        "max_provider_requests": 1,
    })
    provider = (
        QwenImageProvider(settings.qwen_image, settings.qwen_image.timeout_seconds)
        if args.provider == "qwen_image"
        else SeedreamProvider(settings.seedream, settings.seedream.timeout_seconds)
    )
    if not provider.configured:
        raise SystemExit(f"{args.provider} is not fully configured (api key, model, and base URL are required).")
    review_provider = None
    if args.review:
        vision_settings = VisionSettings.from_env(False).model_copy(update={"cache_enabled": False, "max_provider_requests": 1})
        review_provider = (
            QwenVLProvider(vision_settings.qwen_vl, vision_settings.qwen_vl.timeout_seconds)
            if args.review_provider == "qwen_vl"
            else GLMVProvider(vision_settings.glm_v, vision_settings.glm_v.timeout_seconds)
        )
        if not review_provider.configured:
            raise SystemExit(f"{args.review_provider} is not fully configured (api key, model, and base URL are required).")
    request_width, request_height = provider.request_size()
    print(json.dumps({
        "about_to_send_paid_request": True,
        "about_to_transfer_image_spec": True,
        "provider": provider.name,
        "model": provider.model,
        "timeout_seconds": getattr(provider, "timeout_seconds", None),
        "max_retries": getattr(provider, "max_retries", None),
        "request_size": {"width": request_width, "height": request_height},
        "review_enabled": args.review,
        "review_provider": getattr(review_provider, "name", None),
        "review_model": getattr(review_provider, "model", None),
        "review_timeout_seconds": getattr(review_provider, "timeout_seconds", None),
        "review_max_retries": getattr(review_provider, "max_retries", None),
        "review_max_output_tokens": getattr(review_provider, "max_output_tokens", None),
        "allowed_result_domains": getattr(provider, "allowed_domains", []),
        "review_external_allowlist": "configured provider base URL only; no source code or paper is sent",
    }, ensure_ascii=False, indent=2))
    output_dir = Path(args.output_root) / "task_smoke_image"
    state = _synthetic_state(output_dir)
    state["teaching_review_vlm_enabled"] = args.review
    state["external_teaching_review_consent"] = args.review
    state = teaching_diagram_plan_node(state)
    image_runtime = create_image_generation_runtime(settings, [provider])
    state = teaching_diagram_generate_node(state, image_runtime)
    if args.review and review_provider is not None:
        state = teaching_diagram_review_vlm_node(
            state,
            create_vision_runtime(vision_settings, [review_provider]),
            image_runtime,
        )
    manifest = state["teaching_diagram_manifest"]
    print(json.dumps({
        "status": manifest.get("status"),
        "provider": provider.name,
        "model": provider.model,
        "diagram_count": len(manifest.get("diagrams", [])),
        "warnings": manifest.get("warnings", []),
        "validated_outputs": [
            {
                "review": _review_summary(item.get("review")),
                "diagram_id": item.get("diagram_id"),
                "blueprint_sha256": (item.get("blueprint_png") or {}).get("sha256"),
                "raw_sha256": (item.get("generated_raw") or {}).get("sha256"),
                "final_sha256": (item.get("final_asset") or {}).get("sha256"),
                "review_passed": (item.get("review") or {}).get("passed"),
                "provider_attempts": [
                    {
                        "provider": attempt.get("provider"),
                        "model": attempt.get("model"),
                        "status": attempt.get("status"),
                        "latency_ms": attempt.get("latency_ms"),
                        "cache_hit": attempt.get("cache_hit", attempt.get("status") == "cache_hit"),
                    }
                    for attempt in item.get("provider_attempts", [])
                ],
                "display_variant": item.get("display_variant"),
                "fallback_reason": item.get("fallback_reason"),
                "fallback_blueprint": (item.get("blueprint_png") or {}).get("path"),
            }
            for item in manifest.get("diagrams", [])
        ],
    }, ensure_ascii=False, indent=2))


def _synthetic_state(output_dir: Path) -> dict:
    return {
        "output_dir": str(output_dir),
        "teaching_diagrams_enabled": True,
        "image_generation_enabled": True,
        "external_image_consent": True,
        "external_vision_consent": False,
        "external_teaching_review_consent": False,
        "model_analysis": [{
            "class_name": "SyntheticNet",
            "file_path": "synthetic/model.py",
            "start_line": 1,
            "is_main_model_candidate": True,
            "model_inputs": ["x"],
            "model_outputs": ["logits"],
            "layers": [{"assigned_name": "encoder", "name": "encoder", "layer_type": "SyntheticEncoder", "line_no": 2}],
            "forward_steps": [{"order": 1, "target": "features", "expression": "self.encoder(x)", "uses_layers": ["encoder"], "line_no": 5, "explanation": "合成 encoder"}],
        }],
        "function_analysis": [],
        "file_analysis": [],
        "library_calls": [],
        "paper_analysis": {},
        "paper_code_alignment": {},
        "diagrams": [{"id": "model_flow", "diagram_type": "model_flow"}],
        "paper_figure_analysis": {},
        "teaching_plan_budget": {"max_provider_requests": 0, "sent_provider_requests": 0},
        "teaching_image_budget": {},
        "teaching_review_budget": {"max_provider_requests": 0, "sent_provider_requests": 0},
    }


def _review_summary(review: dict | None) -> dict | None:
    if not review:
        return None
    metadata = review.get("metadata") or {}
    return {
        "provider": metadata.get("provider"),
        "model": metadata.get("model"),
        "overall_score": review.get("overall_score"),
        "latency_ms": metadata.get("latency_ms"),
        "cache_hit": metadata.get("cache_hit", False),
        "passed": review.get("passed"),
    }


if __name__ == "__main__":
    main()
