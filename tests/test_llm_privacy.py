from backend.app.llm.privacy import is_sensitive_path, sanitize_payload


def test_sensitive_files_and_values_are_redacted():
    assert is_sensitive_path("project/.env.production")
    assert is_sensitive_path("keys/server.pem")
    payload, count = sanitize_payload({
        "source": 'API_KEY="abc123"\nurl = "postgres://user:pass@example/db"',
        "file_path": "models/model.py",
    })
    assert count == 2
    assert "abc123" not in payload["source"]
    assert "user:pass" not in payload["source"]


def test_sensitive_path_payload_is_excluded():
    payload, count = sanitize_payload({"file_path": ".env", "source": "PASSWORD=x"})
    assert "file_path" not in payload
    assert count >= 1
