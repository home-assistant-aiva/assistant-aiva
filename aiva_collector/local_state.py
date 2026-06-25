from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CollectorConfig


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_db_path(config: CollectorConfig) -> Path:
    return config.path("state_dir") / "aiva_collector.db"


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS processed_files (
            file_id TEXT PRIMARY KEY,
            commerce_id TEXT NULL,
            collector_id TEXT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NULL,
            file_mtime TEXT NULL,
            file_sha256 TEXT NOT NULL,
            normalized_data_hash TEXT NULL,
            detected_at TEXT NOT NULL,
            processed_at TEXT NULL,
            sent_at TEXT NULL,
            status TEXT NOT NULL,
            rows_total INTEGER DEFAULT 0,
            rows_valid INTEGER DEFAULT 0,
            rows_invalid INTEGER DEFAULT 0,
            idempotency_key TEXT NULL,
            backend_summary_id TEXT NULL,
            backend_response_code INTEGER NULL,
            backend_response_json TEXT NULL,
            error_message TEXT NULL,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_files_sha256 ON processed_files(file_sha256);
        CREATE INDEX IF NOT EXISTS idx_processed_files_normalized_hash ON processed_files(normalized_data_hash);
        CREATE INDEX IF NOT EXISTS idx_processed_files_status ON processed_files(status);
        CREATE INDEX IF NOT EXISTS idx_processed_files_name ON processed_files(file_name);
        CREATE INDEX IF NOT EXISTS idx_processed_files_commerce_collector ON processed_files(commerce_id, collector_id);

        CREATE TABLE IF NOT EXISTS processed_file_events (
            event_id TEXT PRIMARY KEY,
            file_id TEXT NULL,
            event_type TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            context_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS upload_queue (
            queue_id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json_path TEXT NULL,
            status TEXT NOT NULL,
            retry_count INTEGER DEFAULT 0,
            next_retry_at TEXT NULL,
            last_error TEXT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_queue_file ON upload_queue(file_id);
        CREATE INDEX IF NOT EXISTS idx_upload_queue_status ON upload_queue(status);
        """
    )
    conn.commit()


def _safe_response_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        safe = {
            str(k): v
            for k, v in value.items()
            if str(k).lower() not in {"token", "collector_token", "authorization", "password", "secret"}
        }
    else:
        safe = value
    return json.dumps(safe, ensure_ascii=True, sort_keys=True)[:2000]


def get_by_sha256(conn: sqlite3.Connection, file_sha256: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM processed_files WHERE file_sha256 = ?", (file_sha256,)).fetchone()
    return dict(row) if row else None


def get_file(conn: sqlite3.Connection, file_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM processed_files WHERE file_id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def upsert_detected_file(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    commerce_id: str | None,
    collector_id: str | None,
    path: Path,
    file_sha256: str,
    status: str = "detected",
) -> None:
    now = utc_now()
    stat = path.stat()
    conn.execute(
        """
        INSERT INTO processed_files (
            file_id, commerce_id, collector_id, file_path, file_name, file_size, file_mtime,
            file_sha256, detected_at, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            file_path=excluded.file_path,
            file_name=excluded.file_name,
            file_size=excluded.file_size,
            file_mtime=excluded.file_mtime,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            file_id,
            commerce_id,
            collector_id,
            str(path),
            path.name,
            stat.st_size,
            datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            file_sha256,
            now,
            status,
            now,
            now,
        ),
    )
    conn.commit()


def update_file_state(conn: sqlite3.Connection, file_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    if "backend_response_json" in fields:
        fields["backend_response_json"] = _safe_response_json(fields["backend_response_json"])
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [file_id]
    conn.execute(f"UPDATE processed_files SET {assignments} WHERE file_id = ?", values)
    conn.commit()


def add_event(
    conn: sqlite3.Connection,
    *,
    file_id: str | None,
    event_type: str,
    level: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO processed_file_events (event_id, file_id, event_type, level, message, context_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            file_id,
            event_type,
            level,
            message[:500],
            json.dumps(context or {}, ensure_ascii=True, sort_keys=True)[:2000],
            utc_now(),
        ),
    )
    conn.commit()


def upsert_upload_queue(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    idempotency_key: str,
    payload_hash: str,
    payload_json_path: str | None = None,
    last_error: str | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO upload_queue (
            queue_id, file_id, idempotency_key, payload_hash, payload_json_path, status,
            retry_count, last_error, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            idempotency_key=excluded.idempotency_key,
            payload_hash=excluded.payload_hash,
            payload_json_path=excluded.payload_json_path,
            status='pending',
            last_error=excluded.last_error,
            updated_at=excluded.updated_at
        """,
        (uuid.uuid4().hex, file_id, idempotency_key, payload_hash, payload_json_path, (last_error or "")[:500], now, now),
    )
    conn.commit()


def list_due_queue_items(conn: sqlite3.Connection, *, now: str | None = None, force: bool = False) -> list[dict[str, Any]]:
    timestamp = now or utc_now()
    if force:
        rows = conn.execute(
            """
            SELECT * FROM upload_queue
            WHERE status IN ('pending', 'retrying', 'processing')
            ORDER BY created_at ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM upload_queue
            WHERE status IN ('pending', 'retrying')
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY COALESCE(next_retry_at, created_at) ASC
            """,
            (timestamp,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_queue_item(conn: sqlite3.Connection, file_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [file_id]
    conn.execute(f"UPDATE upload_queue SET {assignments} WHERE file_id = ?", values)
    conn.commit()


def queue_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = queue_counts(conn)
    next_row = conn.execute(
        """
        SELECT next_retry_at FROM upload_queue
        WHERE status = 'retrying' AND next_retry_at IS NOT NULL
        ORDER BY next_retry_at ASC LIMIT 1
        """
    ).fetchone()
    last_error_row = conn.execute(
        """
        SELECT last_error, updated_at FROM upload_queue
        WHERE last_error IS NOT NULL AND last_error != ''
        ORDER BY updated_at DESC LIMIT 1
        """
    ).fetchone()
    return {
        "counts": counts,
        "next_retry_at": str(next_row["next_retry_at"]) if next_row else None,
        "last_error": str(last_error_row["last_error"]) if last_error_row else None,
        "last_error_at": str(last_error_row["updated_at"]) if last_error_row else None,
    }


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM processed_files GROUP BY status").fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM upload_queue GROUP BY status").fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}
