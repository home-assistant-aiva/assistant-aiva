import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiva_collector import demo_pilot_rc7 as pilot
from aiva_collector.config import CollectorConfig


BUNDLE = Path(__file__).resolve().parents[1] / "support/demo_daily_v2_rc7/aiva-demo-daily-v2-source-20260929.zip"


def make_config(root: Path, *, old_schema="1.0.0") -> CollectorConfig:
    raw = {
        "backend_url": "http://127.0.0.1:8080", "commerce_id": pilot.COMMERCE,
        "collector_id": pilot.COLLECTOR, "collector_token": "test-placeholder-only",
        "input_dir": str(root / "entrada"), "state_dir": str(root / "estado"),
        "output_dir": str(root / "salida"), "processed_dir": str(root / "procesados"),
        "error_dir": str(root / "errores"), "log_file": str(root / "logs" / "collector.log"),
        "column_mapping": {"producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"},
        "source_schema_version": old_schema,
    }
    for key in ("input_dir", "state_dir", "output_dir", "processed_dir", "error_dir"):
        Path(raw[key]).mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    path = root / "config.windows.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return CollectorConfig(raw, path)


def init_state(config: CollectorConfig):
    con = pilot.connect(pilot.local_db_path(config))
    con.close()


def test_rc6_rejected_rc7_accepted_before_work(monkeypatch, tmp_path):
    monkeypatch.setattr(pilot, "VERSION", "0.2.7rc7")
    cli = tmp_path / "aiva-collector-cli.exe"
    cli.write_bytes(b"representative-installed-binary")
    monkeypatch.setattr(pilot, "CLI_SHA", pilot.sha256(cli))
    monkeypatch.setattr(pilot.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="aiva-collector 0.2.7rc6"))
    with pytest.raises(pilot.PilotStop, match="Versión RC7 incorrecta"):
        pilot.verify_installed_rc7(cli)
    monkeypatch.setattr(pilot.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="aiva-collector 0.2.7rc7"))
    pilot.verify_installed_rc7(cli)


def test_embedded_source_precheck_and_scope(monkeypatch, tmp_path):
    source, _ = pilot._extract_verified(BUNDLE, tmp_path)
    config = make_config(tmp_path / "Collector")
    raw = dict(config.raw)
    raw.update(input_dir=str(tmp_path), source_schema_version="2.0.0", daily_complete_file_sha256=pilot.SOURCE_SHA,
               daily_snapshot_complete=True, daily_source_id=pilot.SOURCE_ID,
               business_timezone="America/Argentina/Buenos_Aires", price_semantics="final_net")
    stale_backend_mapping = {"producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"}
    result = pilot._precheck(CollectorConfig(raw, config.config_path), source, stale_backend_mapping)
    assert result == {"schema": "2.0.0", "complete": True, "metrics": 105, "coverage_days": 35,
                      "week_revenue": "736.500000", "week_cogs": "303.000000", "week_units": "51.000000", "mapping_code": "Código"}
    raw["daily_complete_file_sha256"] = "0" * 64
    with pytest.raises(pilot.PilotStop, match="SHA previsto"):
        pilot._precheck(CollectorConfig(raw, config.config_path), source)


def test_backup_restoration_preserves_rc6_history_and_queue(monkeypatch, tmp_path):
    root = tmp_path / "AIVA" / "Collector"
    config = make_config(root)
    init_state(config)
    (root / "entrada" / "legacy.xlsx").write_bytes(b"legacy file kept")
    (root / "logs" / "collector.log").write_text("old log", encoding="utf-8")
    db = pilot.local_db_path(config)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO processed_files (file_id,file_path,file_name,file_sha256,detected_at,status,created_at,updated_at,source_schema_version) VALUES ('old','legacy.xlsx','legacy.xlsx','legacy-sha','2026-09-28','sent','2026-09-28','2026-09-28','1.0.0')")
    con.commit(); con.close()
    monkeypatch.setattr(pilot, "_task_disabled", lambda: True)
    monkeypatch.setattr(pilot, "_task_xml", lambda path: path.write_text("<Task />", encoding="utf-8"))
    backup, count = pilot.backup_and_restore(root, config)
    assert count >= 5
    assert (backup / "config.windows.json").read_bytes() == config.config_path.read_bytes()
    assert (backup / "entrada" / "legacy.xlsx").read_bytes() == b"legacy file kept"
    assert (backup / "logs" / "collector.log").read_text() == "old log"
    assert (backup / "task-AIVA-Collector-Auto.xml").read_text() == "<Task />"
    with sqlite3.connect(backup / "estado" / "aiva_collector.db") as restored:
        assert restored.execute("SELECT status,source_schema_version FROM processed_files WHERE file_id='old'").fetchone() == ("sent", "1.0.0")


def test_sent_v2_retry_is_idempotent_and_pending_blocks(monkeypatch, tmp_path):
    root = tmp_path / "Collector"
    config = make_config(root, old_schema="2.0.0")
    init_state(config)
    db = pilot.local_db_path(config)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO processed_files (file_id,commerce_id,collector_id,file_path,file_name,file_sha256,detected_at,status,created_at,updated_at,source_schema_version) VALUES ('prior',?,?,?,?,?,'2026-09-29','sent','2026-09-29','2026-09-29','2.0.0')", (pilot.COMMERCE, pilot.COLLECTOR, "source.xlsx", "source.xlsx", pilot.SOURCE_SHA))
    assert pilot._check_existing_state(config) == "already_sent"
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO upload_queue (queue_id,file_id,idempotency_key,payload_hash,status,created_at,updated_at) VALUES ('q','prior','i','h','pending','2026-09-29','2026-09-29')")
    with pytest.raises(pilot.PilotStop, match="cola pendiente"):
        pilot._check_existing_state(config)


def test_single_attempt_and_midprocess_failure_no_retry(monkeypatch, tmp_path):
    root = tmp_path / "Collector"
    config = make_config(root, old_schema="2.0.0")
    init_state(config)
    source = root / "entrada" / "synthetic.xlsx"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(pilot, "_task_disabled", lambda: True)
    monkeypatch.setattr(pilot, "_backend_mapping", lambda _: None)
    calls = []
    def failing_process(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("network interrupted")
    monkeypatch.setattr(pilot, "_process_reliable_file", failing_process)
    monkeypatch.setattr(pilot, "CollectorClient", lambda _: object())
    with pytest.raises(RuntimeError, match="network interrupted"):
        pilot._send_once(config, source)
    assert len(calls) == 1
    assert not (root / "estado" / "aiva_collector.lock").exists()


def test_rc6_style_config_upgrades_to_rc7_daily_without_losing_v1(monkeypatch, tmp_path):
    root = tmp_path / "Collector"
    config = make_config(root, old_schema="1.0.0")
    init_state(config)
    original = root / "entrada" / "old-rc6.xlsx"
    original.write_bytes(b"legacy source remains")
    db = pilot.local_db_path(config)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO processed_files (file_id,commerce_id,collector_id,file_path,file_name,file_sha256,detected_at,status,created_at,updated_at,source_schema_version) VALUES ('v1',?,?,?,?,?,'2026-09-28','sent','2026-09-28','2026-09-28','1.0.0')", (pilot.COMMERCE, pilot.COLLECTOR, str(original), original.name, "rc6-old-sha"))
    stage = root / "pilot_rc7_daily_v2"
    stage.mkdir()
    source, manifest = pilot._extract_verified(BUNDLE, stage)
    args = SimpleNamespace(config=str(config.config_path), file=str(source), manifest=str(manifest), expected_sha256=pilot.SOURCE_SHA,
        expected_commerce_id=pilot.COMMERCE, expected_collector_id=pilot.COLLECTOR, source_id=pilot.SOURCE_ID, timezone="America/Argentina/Buenos_Aires")
    assert pilot.cmd_configure_daily_source(args) == 0
    current = pilot.load_config(config.config_path)
    assert current.raw["source_schema_version"] == "2.0.0"
    assert current.raw["daily_complete_file_sha256"] == pilot.SOURCE_SHA
    assert current.raw["column_mapping"]["producto_codigo"] == "Código"
    assert original.read_bytes() == b"legacy source remains"
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT status,source_schema_version FROM processed_files WHERE file_id='v1'").fetchone() == ("sent", "1.0.0")
    monkeypatch.setattr(pilot, "_backend_mapping", lambda _: None)
    assert pilot._precheck(current, source)["schema"] == "2.0.0"


def test_unmigrated_rc6_sqlite_can_be_inspected_read_only(tmp_path):
    config = make_config(tmp_path / "Collector", old_schema="1.0.0")
    init_state(config)
    db = pilot.local_db_path(config)
    with sqlite3.connect(db) as con:
        con.execute("DROP INDEX IF EXISTS idx_processed_files_context_source_sha256_schema")
        con.execute("ALTER TABLE processed_files DROP COLUMN source_schema_version")
    assert pilot._check_existing_state(config) == "new"
    with sqlite3.connect(db) as con:
        assert "source_schema_version" not in {r[1] for r in con.execute("PRAGMA table_info(processed_files)")}


def test_real_mid_send_failure_is_queued_once_and_rerun_stops(monkeypatch, tmp_path):
    from aiva_collector.errors import BackendError
    root = tmp_path / "Collector"
    config = make_config(root, old_schema="1.0.0")
    init_state(config)
    stage = root / "pilot_rc7_daily_v2"
    stage.mkdir()
    source, manifest = pilot._extract_verified(BUNDLE, stage)
    args = SimpleNamespace(config=str(config.config_path), file=str(source), manifest=str(manifest), expected_sha256=pilot.SOURCE_SHA,
        expected_commerce_id=pilot.COMMERCE, expected_collector_id=pilot.COLLECTOR, source_id=pilot.SOURCE_ID, timezone="America/Argentina/Buenos_Aires")
    pilot.cmd_configure_daily_source(args)
    configured = pilot.load_config(config.config_path)
    calls = []
    class InterruptedClient:
        def post_mapping_candidate(self, payload):
            return {"candidate": {"id": "candidate-fixture"}}
        def post_status(self, status):
            return {}
        def send_summary(self, payload):
            calls.append(payload)
            raise BackendError("connection lost after attempt")
    monkeypatch.setattr(pilot, "CollectorClient", lambda _: InterruptedClient())
    monkeypatch.setattr(pilot, "_task_disabled", lambda: True)
    result, _ = pilot._send_once(configured, source)
    assert result == "pending_send"
    assert len(calls) == 1
    assert calls[0]["source_schema_version"] == "2.0.0"
    with pytest.raises(pilot.PilotStop, match="cola pendiente"):
        pilot._check_existing_state(configured)
    assert len(calls) == 1
    assert source.is_file()


def test_successful_once_then_reopen_never_posts_again(monkeypatch, tmp_path):
    root = tmp_path / "Collector"
    config = make_config(root, old_schema="1.0.0")
    init_state(config)
    stage = root / "pilot_rc7_daily_v2"
    stage.mkdir()
    source, manifest = pilot._extract_verified(BUNDLE, stage)
    pilot.cmd_configure_daily_source(SimpleNamespace(config=str(config.config_path), file=str(source), manifest=str(manifest),
        expected_sha256=pilot.SOURCE_SHA, expected_commerce_id=pilot.COMMERCE, expected_collector_id=pilot.COLLECTOR,
        source_id=pilot.SOURCE_ID, timezone="America/Argentina/Buenos_Aires"))
    configured = pilot.load_config(config.config_path)
    calls = []
    class AcceptedClient:
        def post_mapping_candidate(self, payload):
            return {"candidate": {"id": "candidate-fixture"}}
        def post_status(self, status):
            return {}
        def send_summary(self, payload):
            calls.append(payload)
            return {"summary_id": "summary-demo-fixture", "_http_status_code": 201}
    monkeypatch.setattr(pilot, "CollectorClient", lambda _: AcceptedClient())
    monkeypatch.setattr(pilot, "_task_disabled", lambda: True)
    result, _ = pilot._send_once(configured, source)
    assert result == "sent"
    assert len(calls) == 1
    assert pilot._check_existing_state(configured) == "already_sent"
    with sqlite3.connect(pilot.local_db_path(configured)) as con:
        assert con.execute("SELECT status,source_schema_version,backend_summary_id FROM processed_files WHERE file_sha256=?", (pilot.SOURCE_SHA,)).fetchone() == ("sent", "2.0.0", "summary-demo-fixture")
