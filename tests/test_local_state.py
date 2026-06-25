from aiva_collector.local_state import add_event, connect, get_by_sha256, queue_counts, status_counts, update_file_state, upsert_detected_file, upsert_upload_queue


def test_local_state_creates_db_and_tracks_file(tmp_path):
    db = tmp_path / "state" / "aiva_collector.db"
    file_path = tmp_path / "ventas.csv"
    file_path.write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    conn = connect(db)
    try:
        upsert_detected_file(
            conn,
            file_id="file-1",
            commerce_id="commerce",
            collector_id="collector",
            path=file_path,
            file_sha256="sha",
        )
        update_file_state(conn, "file-1", status="sent", rows_total=1, rows_valid=1)
        add_event(conn, file_id="file-1", event_type="sent", level="info", message="ok")

        stored = get_by_sha256(conn, "sha")
        assert stored["status"] == "sent"
        assert status_counts(conn)["sent"] == 1
    finally:
        conn.close()


def test_local_state_sanitizes_backend_response_and_deduplicates_hash(tmp_path):
    db = tmp_path / "aiva_collector.db"
    file_path = tmp_path / "ventas.csv"
    file_path.write_text("x", encoding="utf-8")
    conn = connect(db)
    try:
        upsert_detected_file(conn, file_id="file-1", commerce_id=None, collector_id=None, path=file_path, file_sha256="same")
        update_file_state(conn, "file-1", backend_response_json={"summary_id": "s1", "collector_token": "secret"})

        stored = get_by_sha256(conn, "same")
        assert "secret" not in stored["backend_response_json"]
    finally:
        conn.close()


def test_upload_queue_pending_counts(tmp_path):
    conn = connect(tmp_path / "aiva_collector.db")
    try:
        upsert_upload_queue(conn, file_id="file-1", idempotency_key="idem", payload_hash="payload")
        assert queue_counts(conn)["pending"] == 1
    finally:
        conn.close()
