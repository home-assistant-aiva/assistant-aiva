import json
from pathlib import Path

from aiva_collector.config import CollectorConfig
from aiva_collector.errors import BackendError
from aiva_collector.local_state import connect, get_file, queue_counts, upsert_detected_file, update_file_state, upsert_upload_queue
from aiva_collector.offline_queue import cleanup_sent_queue, enqueue_payload, next_retry_at, process_queue, retry_delay
from aiva_collector.summarizer import idempotency_key


def _config(tmp_path: Path, *, max_retries: int = 10) -> CollectorConfig:
    return CollectorConfig(
        raw={
            "backend_url": "http://backend",
            "commerce_id": "commerce-test",
            "collector_id": "collector-test",
            "collector_token_env": "AIVA_COLLECTOR_TOKEN",
            "input_dir": str(tmp_path / "input"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva.log"),
            "move_processed_files": True,
            "offline_queue_max_retry_count": max_retries,
            "column_mapping": {
                "producto_nombre": "producto_nombre",
                "cantidad_vendida": "cantidad_vendida",
                "precio_venta": "precio_venta",
            },
        },
        config_path=tmp_path / "config.json",
    )


def _payload() -> dict:
    return {
        "commerce_id": "commerce-test",
        "collector_id": "collector-test",
        "periodo": "weekly",
        "fecha_inicio": "2026-06-01",
        "fecha_fin": "2026-06-01",
        "productos_resumidos": [{"producto_nombre": "A", "cantidad_vendida": 1, "facturacion_total": 10}],
        "resumen_financiero": {"facturacion_total": 10},
        "metadata": {
            "source_file": {
                "file_id": "file-1",
                "file_name": "ventas.csv",
                "file_sha256": "sha",
                "normalized_data_hash": "normalized-hash",
                "rows_total": 1,
                "rows_valid": 1,
                "rows_invalid": 0,
            },
            "validation": {"warnings": ["w"], "blocking_errors": []},
        },
        "collector_version": "0.2.5",
    }


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send_summary(self, payload):
        self.sent.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _insert_file(conn, tmp_path: Path) -> Path:
    source = tmp_path / "input" / "ventas.csv"
    source.parent.mkdir()
    source.write_text("x", encoding="utf-8")
    upsert_detected_file(conn, file_id="file-1", commerce_id="commerce-test", collector_id="collector-test", path=source, file_sha256="sha")
    update_file_state(conn, "file-1", status="pending_send")
    return source


def test_enqueue_payload_creates_pending_item_and_payload_file(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        result = enqueue_payload(conn, config, file_id="file-1", payload=_payload(), last_error="backend down")
        payload_path = Path(result["payload_json_path"])
        assert queue_counts(conn)["pending"] == 1
        assert payload_path.exists()
        assert json.loads(payload_path.read_text(encoding="utf-8"))["metadata"]["source_file"]["file_sha256"] == "sha"
    finally:
        conn.close()


def test_process_queue_sends_pending_and_marks_sent(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        source = _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=_payload())
        result = process_queue(conn, config, client=Client([{"summary_id": "s1", "_http_status_code": 201}]), force=True)
        assert result.sent == 1
        assert queue_counts(conn)["sent"] == 1
        assert get_file(conn, "file-1")["status"] == "sent"
        assert not source.exists()
        assert list((tmp_path / "processed").glob("*.csv"))
    finally:
        conn.close()


def test_process_queue_preserves_idempotency_key(tmp_path):
    config = _config(tmp_path)
    payload = _payload()
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=payload)
        expected = idempotency_key(payload)
        process_queue(conn, config, client=Client([{"summary_id": "s1", "_http_status_code": 200}]), force=True)
        row = conn.execute("SELECT idempotency_key FROM upload_queue WHERE file_id = 'file-1'").fetchone()
        assert row["idempotency_key"] == expected
    finally:
        conn.close()


def test_backend_down_goes_retrying_and_sets_next_retry_at(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=_payload())
        result = process_queue(conn, config, client=Client([BackendError("backend down")]), force=True)
        row = conn.execute("SELECT status, retry_count, next_retry_at FROM upload_queue WHERE file_id = 'file-1'").fetchone()
        assert result.retrying == 1
        assert row["status"] == "retrying"
        assert row["retry_count"] == 1
        assert row["next_retry_at"]
    finally:
        conn.close()


def test_backoff_increases_with_retry_count():
    assert retry_delay(0).total_seconds() == 5 * 60
    assert retry_delay(1).total_seconds() == 15 * 60
    assert retry_delay(2).total_seconds() == 30 * 60
    assert retry_delay(3).total_seconds() == 60 * 60
    assert retry_delay(4).total_seconds() == 6 * 60 * 60
    assert next_retry_at(0)


def test_max_retries_moves_to_error(tmp_path):
    config = _config(tmp_path, max_retries=0)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=_payload())
        result = process_queue(conn, config, client=Client([BackendError("backend down")]), force=True)
        assert result.errors == 1
        assert queue_counts(conn)["error"] == 1
    finally:
        conn.close()


def test_duplicate_response_does_not_retry_forever(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=_payload())
        result = process_queue(conn, config, client=Client([BackendError("duplicate_summary", status_code=409)]), force=True)
        assert result.duplicate == 1
        assert queue_counts(conn)["duplicate"] == 1
    finally:
        conn.close()


def test_payload_and_db_do_not_store_token(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        result = enqueue_payload(conn, config, file_id="file-1", payload=_payload(), last_error="a safe error")
        db_text = (tmp_path / "state" / "aiva.db").read_bytes()
        payload_text = Path(result["payload_json_path"]).read_text(encoding="utf-8")
        assert b"token-test" not in db_text
        assert "token-test" not in payload_text
    finally:
        conn.close()


def test_corrupt_payload_goes_error(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        payload_path = tmp_path / "state" / "queue" / "bad.json"
        payload_path.parent.mkdir(parents=True)
        payload_path.write_text("{bad", encoding="utf-8")
        upsert_upload_queue(conn, file_id="file-1", idempotency_key="idem", payload_hash="hash", payload_json_path=str(payload_path))
        result = process_queue(conn, config, client=Client([]), force=True)
        assert result.errors == 1
        assert queue_counts(conn)["error"] == 1
    finally:
        conn.close()


def test_cleanup_does_not_delete_pending(tmp_path):
    config = _config(tmp_path)
    conn = connect(tmp_path / "state" / "aiva.db")
    try:
        _insert_file(conn, tmp_path)
        enqueue_payload(conn, config, file_id="file-1", payload=_payload())
        assert cleanup_sent_queue(conn, days=0) == 0
        assert queue_counts(conn)["pending"] == 1
    finally:
        conn.close()
