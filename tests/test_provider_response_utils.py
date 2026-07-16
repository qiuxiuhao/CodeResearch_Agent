import pytest

from backend.app.utils.provider_response import optional_usage_int, parse_json_object


def test_json_object_parser_preserves_text_and_vision_boundaries():
    assert parse_json_object("```json\n{\"ok\": true}\n```") == {"ok": True}
    with pytest.raises(ValueError):
        parse_json_object("prefix {\"ok\": true} suffix")
    assert parse_json_object("prefix {\"ok\": true} suffix", allow_embedded=True) == {"ok": True}


def test_optional_usage_int_accepts_only_numeric_values():
    assert optional_usage_int(3.9) == 3
    assert optional_usage_int(4) == 4
    assert optional_usage_int("4") is None
    assert optional_usage_int(None) is None
