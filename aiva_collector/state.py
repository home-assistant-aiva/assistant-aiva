from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CollectorConfig


def state_file(config: CollectorConfig) -> Path:
    state_dir = config.path("state_dir")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "collector_state.json"


def save_state(
    config: CollectorConfig,
    *,
    last_summary_file: str | None,
    last_idempotency_key_hash: str | None,
    last_status: str,
    processed_files: list[str] | None = None,
    backend_state: dict[str, Any] | None = None,
) -> Path:
    path = state_file(config)
    payload: dict[str, Any] = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_summary_file": last_summary_file,
        "last_idempotency_key_hash": last_idempotency_key_hash,
        "last_status": last_status,
        "processed_files": processed_files or [],
    }
    if backend_state:
        forbidden = {"collector_token", "token", "authorization", "secret", "token_hash"}
        payload.update({key: value for key, value in backend_state.items() if key not in forbidden})
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=True)
    return path
