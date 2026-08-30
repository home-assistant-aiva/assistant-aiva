import json
from pathlib import Path

from aiva_collector.desktop_app import self_check
from aiva_collector.desktop_service import (
    DashboardSnapshot,
    activate_installation,
    configure_source_folder,
    load_dashboard_snapshot,
    synchronize_now,
)


def _config_payload(tmp_path: Path, *, input_dir: Path, token: str | None = "test-token") -> dict:
    payload = {
        "collector_version": "0.2.7rc1",
        "backend_url": "https://aiva.example",
        "commerce_id": "commerce-1234567890",
        "collector_id": "collector-1234567890",
        "collector_token_env": "AIVA_COLLECTOR_TOKEN",
        "input_dir": str(input_dir),
        "processed_dir": str(tmp_path / "processed"),
        "error_dir": str(tmp_path / "error"),
        "output_dir": str(tmp_path / "output"),
        "state_dir": str(tmp_path / "state"),
        "log_file": str(tmp_path / "logs" / "collector.log"),
        "column_mapping": {},
    }
    if token:
        payload["collector_token"] = token
    return payload


def test_desktop_self_check_does_not_open_window():
    assert self_check() == 0


def test_dashboard_explains_when_activation_is_missing(tmp_path, monkeypatch):
    standard = tmp_path / "config.windows.json"
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(standard))
    monkeypatch.setenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS", str(tmp_path / "missing"))

    snapshot = load_dashboard_snapshot()

    assert snapshot.state == "setup"
    assert snapshot.token_configured is False
    assert "conectar" in snapshot.title.lower()


def test_dashboard_reads_source_and_last_sync_without_network(tmp_path, monkeypatch):
    input_dir = tmp_path / "ventas"
    input_dir.mkdir()
    (input_dir / "ventas.csv").write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "last_auto_run.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-08-30T12:00:00+00:00",
                "result": "ok",
                "files_processed": 1,
                "summaries_sent": 1,
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.windows.json"
    config_path.write_text(json.dumps(_config_payload(tmp_path, input_dir=input_dir)), encoding="utf-8")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))

    snapshot = load_dashboard_snapshot()

    assert snapshot.state == "connected"
    assert snapshot.source_exists is True
    assert snapshot.source_files == 1
    assert snapshot.files_processed == 1
    assert snapshot.summaries_sent == 1
    assert snapshot.commerce_id == "…34567890"


def test_dashboard_marks_plain_http_as_test_mode(tmp_path, monkeypatch):
    input_dir = tmp_path / "ventas"
    input_dir.mkdir()
    config = _config_payload(tmp_path, input_dir=input_dir)
    config["backend_url"] = "http://187.77.44.118:8080"
    config_path = tmp_path / "config.windows.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))

    snapshot = load_dashboard_snapshot()

    assert snapshot.state == "attention"
    assert "modo de prueba" in snapshot.title.lower()
    assert "HTTPS" in snapshot.detail


def test_configure_source_preserves_config_and_creates_backup(tmp_path, monkeypatch):
    old_source = tmp_path / "old"
    new_source = tmp_path / "new"
    old_source.mkdir()
    new_source.mkdir()
    config_path = tmp_path / "config.windows.json"
    config_path.write_text(json.dumps(_config_payload(tmp_path, input_dir=old_source)), encoding="utf-8")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path / "programdata"))
    monkeypatch.setattr("aiva_collector.desktop_service._report_selected_input_source", lambda config: None)

    result = configure_source_folder(new_source)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert result.ok is True
    assert saved["input_dir"] == str(new_source.resolve())
    assert saved["source_mode"] == "watched_folder"
    assert saved["source_read_only"] is True
    assert saved["move_processed_files"] is False
    assert saved["move_error_files"] is False
    assert saved["keep_original_files"] is True
    assert saved["commerce_id"] == "commerce-1234567890"
    assert list((tmp_path / "programdata" / "backups").glob("config-before-source-*.json"))


def test_activation_writes_config_and_keeps_token_out_of_json(tmp_path, monkeypatch):
    config_path = tmp_path / "config.windows.json"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setattr("aiva_collector.desktop_service.stable_machine_id", lambda: "machine-1")
    monkeypatch.setattr(
        "aiva_collector.desktop_service.activate_collector",
        lambda **kwargs: {
            "commerce_id": "commerce-1",
            "collector_id": "collector-1",
            "collector_token": "secret-value",
            "collector_version": "0.1.0",
            "config_defaults": {
                "input_dir": str(tmp_path / "input"),
                "processed_dir": str(tmp_path / "processed"),
                "error_dir": str(tmp_path / "error"),
                "output_dir": str(tmp_path / "output"),
                "state_dir": str(state_dir),
                "log_file": str(tmp_path / "logs" / "collector.log"),
                "column_mapping": {},
            },
        },
    )
    monkeypatch.setattr("aiva_collector.desktop_service.CollectorClient.service_status", lambda self: {"ok": True})

    result = activate_installation("AIVA-CODE", "https://aiva.example")

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert result.ok is True
    assert saved["commerce_id"] == "commerce-1"
    assert saved["collector_version"] == "0.2.7rc2"
    assert "collector_token" not in saved
    assert (state_dir / "collector.token").exists()
    assert "secret-value" not in config_path.read_text(encoding="utf-8")


def test_synchronize_now_shows_pending_send_cause(monkeypatch):
    snapshot = DashboardSnapshot(
        state="attention", title="Pendiente", detail="Pendiente", version="0.2.7rc2",
        config_path=None, commerce_id=None, collector_id=None, input_dir=None,
        source_exists=True, source_files=1, token_configured=True,
        scheduled_task_installed=True, last_run_at=None, last_result="error",
        files_found=1, files_eligible=1, files_skipped=0, files_processed=1,
        summaries_sent=0, duplicates=0, rejected=0, needs_review=0,
        queue_pending=1, last_error=None,
    )
    runtime = type("Runtime", (), {"selected_path": Path("config.windows.json")})()
    monkeypatch.setattr("aiva_collector.desktop_service.resolve_runtime_config", lambda: runtime)
    monkeypatch.setattr("aiva_collector.desktop_service.cmd_run_auto", lambda args: 2)
    monkeypatch.setattr("aiva_collector.desktop_service.load_dashboard_snapshot", lambda: snapshot)

    result = synchronize_now()

    assert result.ok is False
    assert result.title == "Archivo pendiente de envío"
    assert "volverá a intentar" in result.message
