from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def compute_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return float(Decimal(str(value)).quantize(Decimal("0.000001")).normalize())
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return float(value.quantize(Decimal("0.000001")).normalize())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = Decimal(text.replace(",", "."))
            return float(number.quantize(Decimal("0.000001")).normalize())
        except (InvalidOperation, ValueError):
            return text
    if isinstance(value, dict):
        ignored = {"idempotency_key", "processed_at", "sent_at", "detected_at", "file_path", "local_path"}
        return {str(k): _normalize_value(v) for k, v in sorted(value.items()) if str(k) not in ignored}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def compute_normalized_data_hash(normalized_rows_or_summary: Any) -> str:
    normalized = _normalize_value(normalized_rows_or_summary)
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_file_id(
    file_sha256: str,
    file_name: str,
    *,
    commerce_id: str | None = None,
    collector_id: str | None = None,
    backend_url: str | None = None,
) -> str:
    base = "|".join(
        (
            str(commerce_id or ""),
            str(collector_id or ""),
            str(backend_url or "").rstrip("/").lower(),
            file_sha256,
            Path(file_name).name,
        )
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def wait_for_stable_file(path: str | Path, checks: int = 2, interval_seconds: float = 1.0) -> bool:
    target = Path(path)
    stable_count = 0
    last: tuple[int, int] | None = None
    attempts = max(checks + 1, checks * 3)
    for _ in range(attempts):
        try:
            stat = target.stat()
        except OSError:
            return False
        current = (stat.st_size, stat.st_mtime_ns)
        if current == last:
            stable_count += 1
            if stable_count >= checks:
                return True
        else:
            stable_count = 0
            last = current
        time.sleep(interval_seconds)
    return False
