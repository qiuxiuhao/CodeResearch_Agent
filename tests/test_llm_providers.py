import json

import httpx

from backend.app.llm.config import ProviderSettings
from backend.app.llm.providers.deepseek_provider import DeepSeekProvider
from backend.app.llm.types import ProviderRequest
from backend.app.schemas.llm_explanation import FileLLMExplanation


def test_provider_uses_declared_json_object_capability():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "file_path": "main.py", "summary": "入口", "architecture_role": "启动",
                "reading_guide": [], "key_relationships": [], "uncertainties": [], "evidence_refs": ["file:main.py"],
            })}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekProvider(
            ProviderSettings(name="deepseek", api_key="test", base_url="https://example.test", model="chat"),
            5,
            client,
        )
        response = provider.generate(ProviderRequest(
            task_type="file_explain", system_prompt="system", input_payload={},
            response_model=FileLLMExplanation, max_output_tokens=100,
        ))
    assert captured["response_format"] == {"type": "json_object"}
    assert "tools" not in captured
    assert response.total_tokens == 11
