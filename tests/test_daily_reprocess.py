import hashlib
import json
from datetime import date
from pathlib import Path

from aiva_collector.cli import main
from aiva_collector.config import CollectorConfig, load_config
from aiva_collector.errors import BackendError
from aiva_collector.local_state import connect
from aiva_collector.summarizer import build_summary


PARTIAL_BACKEND_MAPPING = {
    "fecha": "Fecha",
    "producto_nombre": "Producto",
    "cantidad_vendida": "Cantidad",
    "precio_venta": "Precio venta",
}


def make_config(tmp_path, commerce="commerce-one"):
    data = json.loads(Path("configs/example_config.json").read_text())
    data.update({
        "backend_url": "http://backend.test:8080",
        "commerce_id": commerce,
        "collector_id": "collector-one",
        "input_dir": str(tmp_path / "source"),
        "processed_dir": str(tmp_path / "processed"),
        "error_dir": str(tmp_path / "error"),
        "output_dir": str(tmp_path / "output"),
        "state_dir": str(tmp_path / "state"),
        "log_file": str(tmp_path / "collector.log"),
        "source_read_only": True,
        "move_processed_files": False,
        "move_error_files": False,
        "keep_original_files": True,
        "stable_file_interval_seconds": 0,
        "source_schema_version": "1.0.0",
    })
    (tmp_path / "source").mkdir()
    path = tmp_path / "config.windows.json"
    path.write_text(json.dumps(data))
    return path


def make_file(folder):
    path = folder / "synthetic.csv"
    path.write_text(
        "Fecha,Código,Producto,Categoría,Cantidad,Precio venta,Costo,Stock,Descuento\n"
        "2026-09-28,SYN-A,Sintético A,Demo,2,10,4,98,0\n"
        "2026-09-28,SYN-B,Sintético B,Demo,0,20,8,100,0\n",
        encoding="utf-8",
    )
    return path


def fake_backend(monkeypatch, send):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "synthetic-token")
    monkeypatch.setattr("aiva_collector.cli._backend_mapping", lambda config: PARTIAL_BACKEND_MAPPING)
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_status", lambda self, status, message=None: {})
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_mapping_candidate", lambda self, payload: {"candidate": {"id": "candidate"}})
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.send_summary", lambda self, payload: send(payload))


def reprocess_args(config_path, source, sha, commerce="commerce-one"):
    return [
        "reprocess-sent-v2", "--config", str(config_path), "--file", str(source),
        "--expected-sha256", sha, "--expected-commerce-id", commerce,
        "--expected-collector-id", "collector-one", "--expected-source-id", "synthetic-source",
        "--expected-v1-summary-id", "summary-v1",
    ]


def initial_v1(tmp_path, monkeypatch, send):
    config_path = make_config(tmp_path)
    source = make_file(tmp_path / "source")
    fake_backend(monkeypatch, send)
    assert main(["run-auto", "--config", str(config_path)]) == 0
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    data = json.loads(config_path.read_text())
    data.update({
        "source_schema_version": "2.0.0", "daily_source_id": "synthetic-source",
        "daily_snapshot_complete": True, "daily_complete_file_sha256": sha,
        "business_timezone": "America/Argentina/Buenos_Aires", "price_semantics": "final_net",
    })
    config_path.write_text(json.dumps(data))
    return config_path, source, sha


def test_v1_to_v2_keeps_history_and_is_idempotent(tmp_path, monkeypatch):
    sent = []
    def send(payload):
        sent.append(payload)
        return {"summary_id": "summary-v1" if len(sent) == 1 else "summary-v2", "_http_status_code": 201}
    config_path, source, sha = initial_v1(tmp_path, monkeypatch, send)
    assert sent[0].get("source_schema_version", "1.0.0") == "1.0.0"
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 1
    args = reprocess_args(config_path, source, sha)
    assert main(args) == 0
    assert len(sent) == 2
    assert sent[1]["source_schema_version"] == "2.0.0"
    assert sent[1]["daily_snapshot"]["completeness_declared"] is True
    assert sent[1]["daily_snapshot"]["source_id"] == "synthetic-source"
    assert main(args) == 0
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 2
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    try:
        rows = conn.execute("SELECT source_schema_version,status,backend_summary_id FROM processed_files ORDER BY created_at").fetchall()
        assert {tuple(r) for r in rows} == {("1.0.0", "sent", "summary-v1"), ("2.0.0", "sent", "summary-v2")}
        assert conn.execute("SELECT COUNT(*) FROM processed_file_events WHERE event_type='v1_to_v2_reprocess_requested'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM upload_queue").fetchone()[0] == 0
    finally:
        conn.close()


def test_reprocess_rejects_wrong_identity_digest_and_old_failure(tmp_path, monkeypatch):
    sent = []
    def send(payload):
        sent.append(payload)
        return {"summary_id": "summary-v1", "_http_status_code": 201}
    config_path, source, sha = initial_v1(tmp_path, monkeypatch, send)
    assert main(reprocess_args(config_path, source, sha, commerce="another-commerce")) == 2
    assert main(reprocess_args(config_path, source, "0" * 64)) == 2
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    conn.execute("UPDATE processed_files SET status='error'")
    conn.commit()
    conn.close()
    assert main(reprocess_args(config_path, source, sha)) == 2
    assert len(sent) == 1


def test_reprocess_temporary_failure_uses_existing_queue(tmp_path, monkeypatch):
    sent = []
    def send(payload):
        sent.append(payload)
        if len(sent) == 2:
            raise BackendError("temporary", status_code=503)
        return {"summary_id": "summary-v1" if len(sent) == 1 else "summary-v2", "_http_status_code": 201}
    config_path, source, sha = initial_v1(tmp_path, monkeypatch, send)
    args = reprocess_args(config_path, source, sha)
    assert main(args) == 0
    assert main(args) == 0
    assert len(sent) == 2
    assert main(["retry-pending", "--config", str(config_path)]) == 0
    assert len(sent) == 3
    assert sent[1]["daily_snapshot"] == sent[2]["daily_snapshot"]
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    try:
        assert conn.execute("SELECT status FROM upload_queue").fetchone()[0] == "sent"
        assert conn.execute("SELECT COUNT(*) FROM processed_files WHERE status='sent'").fetchone()[0] == 2
    finally:
        conn.close()


def test_configure_complete_synthetic_source_scopes_digest(tmp_path):
    config_path = make_config(tmp_path)
    source = make_file(tmp_path / "source")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    generator = tmp_path / "source" / "generator.py"
    generator.write_text("# closed synthetic fixture\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "synthetic": True, "complete_by_construction": True, "sha256": sha,
        "generator": "generator.py", "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "source_id": "synthetic-source", "timezone": "America/Argentina/Buenos_Aires",
        "price_semantics": "final_net", "period_start": "2026-09-28",
        "period_end": "2026-09-28", "product_codes": ["SYN-A", "SYN-B"],
    }))
    assert main([
        "configure-daily-source", "--config", str(config_path), "--file", str(source),
        "--manifest", str(manifest), "--expected-sha256", sha,
        "--expected-commerce-id", "commerce-one", "--expected-collector-id", "collector-one",
        "--source-id", "synthetic-source", "--timezone", "America/Argentina/Buenos_Aires",
    ]) == 0
    c = load_config(config_path)
    assert c.raw["daily_complete_file_sha256"] == sha
    assert len(list((tmp_path / "backups").glob("config-before-daily-*.json"))) == 1
    rows = [{
        "fecha": date(2026, 9, 28), "producto_codigo": "SYN-A", "producto_nombre": "Sintético A",
        "categoria": "Demo", "cantidad_vendida": 2, "precio_venta": 10,
        "costo_unitario": 4, "stock_actual": 98, "_daily_decimal": {"descuento": "0"},
    }]
    matching = CollectorConfig({**c.raw, "_active_file_sha256": sha}, c.config_path)
    other = CollectorConfig({**c.raw, "_active_file_sha256": "0" * 64}, c.config_path)
    assert build_summary(rows, matching, 1, 1, 0)["daily_snapshot"]["completeness_declared"] is True
    assert build_summary(rows, other, 1, 1, 0)["daily_snapshot"]["completeness_declared"] is False


def test_reprocess_isolated_from_other_commerce_with_same_digest(tmp_path, monkeypatch):
    from aiva_collector.local_state import upsert_detected_file, update_file_state

    sent = []
    def send(payload):
        sent.append(payload)
        return {"summary_id": "summary-v1" if len(sent) == 1 else "summary-v2", "_http_status_code": 201}
    config_path, source, sha = initial_v1(tmp_path, monkeypatch, send)
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    try:
        upsert_detected_file(
            conn, file_id="other-commerce-file", commerce_id="other-commerce",
            collector_id="collector-one", backend_url="http://backend.test:8080",
            path=source, file_sha256=sha, source_schema_version="1.0.0",
        )
        update_file_state(conn, "other-commerce-file", status="sent", backend_summary_id="other-summary")
    finally:
        conn.close()
    assert main(reprocess_args(config_path, source, sha)) == 0
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    try:
        other = conn.execute(
            "SELECT status,source_schema_version,backend_summary_id FROM processed_files WHERE file_id='other-commerce-file'"
        ).fetchone()
        assert tuple(other) == ("sent", "1.0.0", "other-summary")
        assert conn.execute(
            "SELECT COUNT(*) FROM processed_files WHERE commerce_id='other-commerce'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
    assert len(sent) == 2


def test_rc6_state_index_upgrades_without_losing_sent_v1(tmp_path):
    db = tmp_path / "state" / "aiva_collector.db"
    source = make_file(tmp_path)
    # Build an RC6-shaped database from a fresh schema without touching product state.
    conn = connect(db)
    try:
        conn.execute("DROP INDEX idx_processed_files_context_sha256_schema")
        conn.execute(
            """CREATE UNIQUE INDEX idx_processed_files_context_sha256 ON processed_files(
            COALESCE(commerce_id,''),COALESCE(collector_id,''),COALESCE(backend_url,''),file_sha256)"""
        )
        from aiva_collector.local_state import upsert_detected_file, update_file_state
        upsert_detected_file(
            conn, file_id="rc6-v1", commerce_id="commerce-one", collector_id="collector-one",
            backend_url="http://backend.test:8080", path=source,
            file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        update_file_state(conn, "rc6-v1", status="sent", source_schema_version="1.0.0")
    finally:
        conn.close()
    upgraded = connect(db)
    try:
        assert upgraded.execute("SELECT status FROM processed_files WHERE file_id='rc6-v1'").fetchone()[0] == "sent"
        indexes = {r[1] for r in upgraded.execute("PRAGMA index_list(processed_files)")}
        assert "idx_processed_files_context_sha256" not in indexes
        assert "idx_processed_files_context_sha256_schema" in indexes
        assert upgraded.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        upgraded.close()
