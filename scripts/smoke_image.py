from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.agents.nodes.teaching_diagram_generate_node import teaching_diagram_generate_node
from backend.app.agents.nodes.teaching_diagram_plan_node import teaching_diagram_plan_node
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.providers.seedream_provider import SeedreamProvider
from backend.app.image_generation.runtime import create_image_generation_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual image-generation smoke test. This may incur cost.")
    parser.add_argument("--provider", choices=["qwen_image", "seedream"], required=True)
    parser.add_argument("--output-root", default="/tmp/code_research_agent_smoke_image")
    parser.add_argument("--i-understand-cost", action="store_true", required=True)
    args = parser.parse_args()
    if not args.i_understand_cost:
        raise SystemExit("Pass --i-understand-cost to acknowledge the real external request and possible fee.")

    settings = ImageGenerationSettings.from_env(True, external_image_consent=True).model_copy(update={
        "cache_enabled": False,
        "max_provider_requests": 1,
    })
    provider = (
        QwenImageProvider(settings.qwen_image)
        if args.provider == "qwen_image"
        else SeedreamProvider(settings.seedream)
    )
    if not provider.configured:
        raise SystemExit(f"{args.provider} API key is not configured.")
    output_dir = Path(args.output_root) / "task_smoke_image"
    state = _synthetic_state(output_dir)
    state = teaching_diagram_plan_node(state)
    state = teaching_diagram_generate_node(state, create_image_generation_runtime(settings, [provider]))
    manifest = state["teaching_diagram_manifest"]
    print(json.dumps({
        "status": manifest.get("status"),
        "provider": provider.name,
        "model": provider.model,
        "diagram_count": len(manifest.get("diagrams", [])),
        "warnings": manifest.get("warnings", []),
        "validated_outputs": [
            {
                "diagram_id": item.get("diagram_id"),
                "blueprint_sha256": (item.get("blueprint_png") or {}).get("sha256"),
                "raw_sha256": (item.get("generated_raw") or {}).get("sha256"),
                "final_sha256": (item.get("final_asset") or {}).get("sha256"),
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


if __name__ == "__main__":
    main()
