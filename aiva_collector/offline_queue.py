from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import CollectorClient
from .config import CollectorConfig
from .errors import BackendError
from .file_fingerprint import compute_normalized_data_hash
from .local_state import (
    add_event,
    get_file,
    list_due_queue_items,
    update_file_state,
    update_queue_item,
    upsert_upload_queue,
    utc_now,
)
from .summarizer import idempotency_key


QUEUE_STATUSES = {"pending", "processing", "sent", "error", "retrying", "duplicate"}
BACKOFF_MINUTES = [5, 15, 30, 60]
SENSITIVE_KEYS = {"token", "collector_token", "authorization", "password", "secret"}


@dataclass
class QueueProcessResult:
    attempted: int = 0
    sent: int = 0
    duplicate: int = 0
    retrying: int = 0
    errors: int = 0
    skipped: int = 0


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _assert_no_sensitive_keys(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS or lowered.endswith("_token"):
                raise ValueError(f"Campo sensible no permitido en payload offline: {path}.{key}")
            _assert_no_sensitive_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_sensitive_keys(child, path=f"{path}[{index}]")


def _queue_dir(config: CollectorConfig) -> Path:
    path = config.path("state_dir") / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _payload_path(config: CollectorConfig, file_id: str) -> Path:
    return _queue_dir(config) / f"{file_id}.json"


def retry_delay(retry_count: int) -> timedelta:
    if retry_count < len(BACKOFF_MINUTES):
        return timedelta(minutes=BACKOFF_MINUTES[retry_count])
    return timedelta(hours=6)


def next_retry_at(retry_count: int, *, now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + retry_delay(retry_count)).isoformat()


def max_retry_count(config: CollectorConfig, default: int = 10) -> int:
    return int(config.raw.get("offline_queue_max_retry_count", default))


def _payload_kind(payload: dict[str, Any]) -> str:
    return str(payload.get("_aiva_queue_kind") or "summary")


def _payload_idempotency_key(payload: dict[str, Any]) -> str:
    if _payload_kind(payload) == "data_source_discovery":
        base = json.dumps(
            {
                "commerce_id": payload.get("commerce_id"),
                "collector_id": payload.get("collector_id"),
                "source_type": payload.get("source_type"),
                "detected_path": payload.get("detected_path"),
                "detected_host": payload.get("detected_host"),
                "detected_engine": payload.get("detected_engine"),
                "name": payload.get("name"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()
    return idempotency_key(payload)


def _send_payload(client: CollectorClient, payload: dict[str, Any]) -> dict[str, Any]:
    if _payload_kind(payload) == "data_source_discovery":
        discovery = dict(payload)
        discovery.pop("_aiva_queue_kind", None)
        discovery.pop("commerce_id", None)
        return client.post_data_source_discovery(discovery)
    return client.send_summary(payload)


def enqueue_payload(
    conn,
    config: CollectorConfig,
    *,
    file_id: str,
    payload: dict[str, Any],
    last_error: str | None = None,
) -> dict[str, str]:
    _assert_no_sensitive_keys(payload)
    idem = _payload_idempotency_key(payload)
    payload_hash = compute_normalized_data_hash(payload)
    path = _payload_path(config, file_id)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(_json_dumps(payload) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    upsert_upload_queue(
        conn,
        file_id=file_id,
        idempotency_key=idem,
        payload_hash=payload_hash,
        payload_json_path=str(path),
        last_error=last_error,
    )
    add_event(conn, file_id=file_id, event_type="queued", level="warning", message=last_error or "Payload encolado para reintento.")
    return {"idempotency_key": idem, "payload_hash": payload_hash, "payload_json_path": str(path)}


def _load_payload(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        raise ValueError("upload_queue no tiene payload_json_path")
    path = Path(path_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Payload offline invalido: JSON raiz no es objeto")
    _assert_no_sensitive_keys(data)
    return data


def _is_duplicate_response(exc: BackendError) -> bool:
    return exc.status_code == 409 or "duplicate" in str(exc).lower() or "duplicado" in str(exc).lower()


def _is_temporary_backend_error(exc: BackendError) -> bool:
    if exc.status_code is None:
        return True
    return exc.status_code == 429 or exc.status_code >= 500


def is_temporary_backend_error(exc: BackendError) -> bool:
    return _is_temporary_backend_error(exc)


def _timestamped_dest(directory: Path, source: Path, *, suffix: str | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    extra = f".{suffix}" if suffix else ""
    return directory / f"{source.stem}.{stamp}{extra}{source.suffix}"


def _move_original_to_processed(config: CollectorConfig, file_row: dict[str, Any] | None) -> tuple[list[str], str | None]:
    if not file_row:
        return [], "registro processed_files no encontrado"
    source = Path(str(file_row["file_path"]))
    if not source.exists():
        return [], "archivo original no encontrado, payload ya fue enviado"
    if not bool(config.raw.get("move_processed_files", True)):
        return [], None
    target_dir = config.path("processed_dir")
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = _timestamped_dest(target_dir, source)
    if bool(config.raw.get("keep_original_files", False)):
        shutil.copy2(source, dest)
    else:
        shutil.move(str(source), str(dest))
    return [str(dest)], None


def _mark_sent(conn, config: CollectorConfig, item: dict[str, Any], response: dict[str, Any], *, duplicate: bool = False) -> tuple[list[str], str | None]:
    if str(item["file_id"]).startswith("discovery-"):
        status = "duplicate" if duplicate else "sent"
        update_queue_item(conn, str(item["file_id"]), status=status, last_error=None, next_retry_at=None)
        add_event(
            conn,
            file_id=str(item["file_id"]),
            event_type="discovery_retry_success",
            level="info",
            message="Discovery pendiente enviado correctamente." if not duplicate else "Backend confirmo discovery duplicado/idempotente.",
            context={"duplicate": duplicate},
        )
        return [], None
    file_row = get_file(conn, str(item["file_id"]))
    moved, warning = _move_original_to_processed(config, file_row)
    status = "duplicate" if duplicate else "sent"
    update_queue_item(conn, str(item["file_id"]), status=status, last_error=warning, next_retry_at=None)
    update_file_state(
        conn,
        str(item["file_id"]),
        status=status,
        sent_at=utc_now(),
        backend_summary_id=response.get("summary_id") or response.get("id"),
        backend_response_code=response.get("_http_status_code", 409 if duplicate else 200),
        backend_response_json=response,
        error_message=warning,
    )
    add_event(
        conn,
        file_id=str(item["file_id"]),
        event_type="retry_success",
        level="info",
        message="Payload pendiente enviado correctamente." if not duplicate else "Backend confirmo duplicado/idempotente.",
        context={"moved": moved, "warning": warning, "duplicate": duplicate},
    )
    return moved, warning


def process_queue(
    conn,
    config: CollectorConfig,
    *,
    client: CollectorClient | None = None,
    force: bool = False,
) -> QueueProcessResult:
    client = client or CollectorClient(config)
    result = QueueProcessResult()
    for item in list_due_queue_items(conn, force=force):
        result.attempted += 1
        file_id = str(item["file_id"])
        retry_count = int(item.get("retry_count") or 0)
        update_queue_item(conn, file_id, status="processing")
        add_event(conn, file_id=file_id, event_type="retry_started", level="info", message="Reintento de payload pendiente iniciado.")
        try:
            payload = _load_payload(item.get("payload_json_path"))
            if _payload_idempotency_key(payload) != item.get("idempotency_key"):
                raise ValueError("idempotency_key del payload no coincide con upload_queue")
            response = _send_payload(client, payload)
        except BackendError as exc:
            if _is_duplicate_response(exc):
                _mark_sent(conn, config, item, {"duplicate": True, "_http_status_code": exc.status_code or 409}, duplicate=True)
                result.duplicate += 1
                continue
            if _is_temporary_backend_error(exc):
                next_count = retry_count + 1
                if next_count > max_retry_count(config):
                    message = f"Se supero max_retry_count={max_retry_count(config)}: {exc}"
                    update_queue_item(conn, file_id, status="error", retry_count=next_count, next_retry_at=None, last_error=message)
                    update_file_state(conn, file_id, status="error", retry_count=next_count, error_message=message)
                    add_event(conn, file_id=file_id, event_type="retry_gave_up", level="error", message=message)
                    result.errors += 1
                else:
                    retry_at = next_retry_at(retry_count)
                    update_queue_item(
                        conn,
                        file_id,
                        status="retrying",
                        retry_count=next_count,
                        next_retry_at=retry_at,
                        last_error=str(exc),
                    )
                    update_file_state(conn, file_id, status="pending_send", retry_count=next_count, error_message=str(exc))
                    add_event(conn, file_id=file_id, event_type="retry_failed", level="warning", message=str(exc))
                    add_event(conn, file_id=file_id, event_type="retry_scheduled", level="info", message=f"Proximo reintento: {retry_at}")
                    result.retrying += 1
                continue
            message = str(exc)
            update_queue_item(conn, file_id, status="error", last_error=message, next_retry_at=None)
            update_file_state(conn, file_id, status="error", error_message=message, backend_response_code=exc.status_code)
            add_event(conn, file_id=file_id, event_type="retry_gave_up", level="error", message=message)
            result.errors += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            message = f"Payload offline invalido: {exc}"
            update_queue_item(conn, file_id, status="error", last_error=message, next_retry_at=None)
            update_file_state(conn, file_id, status="error", error_message=message)
            add_event(conn, file_id=file_id, event_type="retry_gave_up", level="error", message=message)
            result.errors += 1
        else:
            _mark_sent(conn, config, item, response)
            result.sent += 1
    return result


def cleanup_sent_queue(conn, *, days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = conn.execute("DELETE FROM upload_queue WHERE status IN ('sent', 'duplicate') AND updated_at < ?", (cutoff,))
    conn.commit()
    return int(cursor.rowcount or 0)


def cleanup_old_events(conn, *, days: int = 90) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = conn.execute("DELETE FROM processed_file_events WHERE created_at < ?", (cutoff,))
    conn.commit()
    return int(cursor.rowcount or 0)
