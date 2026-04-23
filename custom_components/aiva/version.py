"""Runtime version helpers for the AIVA integration."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


@lru_cache
def get_integration_version() -> str:
    """Return the version declared in the integration manifest."""
    manifest_path = Path(__file__).with_name("manifest.json")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "unknown"

    version = manifest.get("version")
    return str(version) if version else "unknown"
