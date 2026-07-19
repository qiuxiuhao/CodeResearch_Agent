from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault("CRA_LEGACY_INTERNAL_API_ENABLED", "true")
