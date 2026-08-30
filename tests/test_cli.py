import json
from pathlib import Path

import pytest

from aiva_collector.cli import (
    DEFAULT_BACKEND_URL,
    DEFAULT_COLLECTOR_VERSION,
    _filter_unchanged_read_only_files,
    _single_run_lock,
    build_parser,
    main,
    safe_display_path,
)
from aiva_collector.config import CollectorConfig


def test_cli_reports_rc2_version(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.2.7rc2"


def test_cli_run_once_dry_generates_last_summary(monkeypatch, tmp_path):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path))
    output = tmp_path / "samples" / "output" / "last_summary.json"
    if output.exists():
        output.unlink()
    code = main(["run-once", "--config", "configs/example_config.json"])
    assert code == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["metadata"]["filas_validas"] > 0


def test_cli_send_without_token_fails(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path))
    code = main(["run-once", "--config", "configs/example_config.json", "--send"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Falta token" in captured.err


def test_cli_send_alias_without_token_fails(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path))
    code = main(["send", "--config", "configs/example_config.json"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Falta token" in captured.err


def test_cli_windows_default_config(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    parser = build_parser()
    args = parser.parse_args(["validate"])
    assert args.config is None


def test_cli_exposes_activation_and_run_auto_help():
    parser = build_parser()
    with pytest.raises(SystemExit) as activate:
        parser.parse_args(["activate", "--help"])
    with pytest.raises(SystemExit) as run_auto:
        parser.parse_args(["run-auto", "--help"])
    assert activate.value.code == 0
    assert run_auto.value.code == 0


def test_cli_exposes_queue_commands_help():
    parser = build_parser()
    with pytest.raises(SystemExit) as queue_status:
        parser.parse_args(["queue-status", "--help"])
    with pytest.raises(SystemExit) as retry_pending:
        parser.parse_args(["retry-pending", "--help"])
    assert queue_status.value.code == 0
    assert retry_pending.value.code == 0


def test_cli_exposes_discover_and_diagnose_help():
    parser = build_parser()
    with pytest.raises(SystemExit) as discover:
        parser.parse_args(["discover", "--help"])
    with pytest.raises(SystemExit) as diagnose:
        parser.parse_args(["diagnose-config", "--help"])
    assert discover.value.code == 0
    assert diagnose.value.code == 0


def test_run_auto_without_files_exits_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "token-test")
    config_path = tmp_path / "config.auto.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "input_dir": str(tmp_path / "input"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
            "move_processed_files": True,
        }
    )
    (tmp_path / "input").mkdir()
    config_path.write_text(json.dumps(data), encoding="utf-8")

    code = main(["run-auto", "--config", str(config_path)])

    assert code == 0
    assert "Sin archivos" in capsys.readouterr().out


def test_run_auto_lock_prevents_overlapping_execution(tmp_path):
    config = CollectorConfig(raw={"state_dir": str(tmp_path / "state")}, config_path=tmp_path / "config.json")

    with _single_run_lock(config) as first:
        assert first is True
        with _single_run_lock(config) as second:
            assert second is False

    with _single_run_lock(config) as third:
        assert third is True


def test_read_only_source_skips_unchanged_sent_file_but_detects_change(tmp_path):
    from aiva_collector.local_state import connect, update_file_state, upsert_detected_file

    source = tmp_path / "ventas.csv"
    source.write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    config = CollectorConfig(
        raw={
            "state_dir": str(tmp_path / "state"),
            "source_read_only": True,
            "backend_url": "http://backend",
            "commerce_id": "commerce-1",
            "collector_id": "collector-1",
        },
        config_path=tmp_path / "config.json",
    )
    conn = connect(tmp_path / "state" / "collector.db")
    try:
        upsert_detected_file(
            conn,
            file_id="file-1",
            commerce_id="commerce-1",
            collector_id="collector-1",
            backend_url="http://backend",
            path=source,
            file_sha256="sha-1",
        )
        update_file_state(conn, "file-1", status="sent")

        assert _filter_unchanged_read_only_files(config, conn, [source]) == []

        source.write_text("producto,cantidad\nA,222\n", encoding="utf-8")
        assert _filter_unchanged_read_only_files(config, conn, [source]) == [source]
    finally:
        conn.close()


def test_queue_status_outputs_counts_without_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "token-test")
    config_path = tmp_path / "config.queue.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "input_dir": str(tmp_path / "input"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
        }
    )
    (tmp_path / "input").mkdir()
    config_path.write_text(json.dumps(data), encoding="utf-8")

    code = main(["queue-status", "--config", str(config_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "pendientes:" in out
    assert "token-test" not in out


def test_retry_pending_attempts_send_without_printing_token(tmp_path, monkeypatch, capsys):
    from aiva_collector.config import load_config
    from aiva_collector.local_state import connect, local_db_path, upsert_detected_file, update_file_state
    from aiva_collector.offline_queue import enqueue_payload

    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "token-test")
    config_path = tmp_path / "config.retry.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "backend_url": "http://backend",
            "commerce_id": "commerce-test",
            "collector_id": "collector-test",
            "input_dir": str(tmp_path / "input"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
        }
    )
    source = tmp_path / "input" / "ventas.csv"
    source.parent.mkdir()
    source.write_text("x", encoding="utf-8")
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config = load_config(config_path)
    conn = connect(local_db_path(config))
    try:
        upsert_detected_file(conn, file_id="file-1", commerce_id="commerce-test", collector_id="collector-test", path=source, file_sha256="sha")
        update_file_state(conn, "file-1", status="pending_send")
        enqueue_payload(
            conn,
            config,
            file_id="file-1",
            payload={
                "commerce_id": "commerce-test",
                "collector_id": "collector-test",
                "periodo": "weekly",
                "fecha_inicio": "2026-06-01",
                "fecha_fin": "2026-06-01",
                "productos_resumidos": [],
                "resumen_financiero": {},
                "metadata": {"source_file": {"normalized_data_hash": "hash"}},
            },
        )
    finally:
        conn.close()

    monkeypatch.setattr(
        "aiva_collector.offline_queue.CollectorClient.send_summary",
        lambda self, payload: {"summary_id": "s1", "_http_status_code": 200},
    )

    code = main(["retry-pending", "--config", str(config_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "enviados=1" in out
    assert "token-test" not in out


def test_move_processed_false_keeps_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path))
    source = Path("samples/input/ventas_demo.csv")
    assert source.exists()
    code = main(["run-once", "--config", "configs/example_config.json"])
    assert code == 0
    assert source.exists()


def test_safe_display_path_inside_project():
    path = Path.cwd() / "samples" / "output" / "last_summary.json"
    assert safe_display_path(path) == "samples/output/last_summary.json"


def test_safe_display_path_outside_project(tmp_path):
    path = tmp_path / "output" / "last_summary.json"
    assert safe_display_path(path) == str(path)


def test_run_once_dry_with_output_outside_project_does_not_traceback(tmp_path, monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config_path = tmp_path / "config.clean.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "input_dir": str((Path.cwd() / "samples" / "input").resolve()),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
        }
    )
    config_path.write_text(json.dumps(data), encoding="utf-8")

    code = main(["run-once", "--config", str(config_path)])

    assert code == 0
    summary_path = tmp_path / "output" / "last_summary.json"
    state_path = tmp_path / "state" / "collector_state.json"
    assert summary_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_summary_file"] == str(summary_path)


def test_safe_display_path_windows_manual_output_does_not_raise():
    path = Path("C:\\AIVA_Comercio\\output\\last_summary.json")
    base = Path("C:\\AIVA_Comercio\\collector")
    assert safe_display_path(path, base) == "C:\\AIVA_Comercio\\output\\last_summary.json"


def test_activate_empty_backend_url_uses_default(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr("builtins.input", lambda prompt: "" if "Backend URL" in prompt else "AIVA-8F3K-91QZ")
    monkeypatch.setattr("aiva_collector.cli.stable_machine_id", lambda: "machine-test")
    monkeypatch.setattr("aiva_collector.cli.socket.gethostname", lambda: "host-test")

    def fake_activate(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "commerce_id": "commerce-1",
            "collector_id": "collector-1",
            "collector_token": "aiva_col_secret",
            "collector_version": "0.2.1",
            "config_defaults": {
                "input_dir": str(tmp_path / "input"),
                "processed_dir": str(tmp_path / "processed"),
                "error_dir": str(tmp_path / "error"),
                "output_dir": str(tmp_path / "output"),
                "state_dir": str(tmp_path / "state"),
                "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
                "column_mapping": {
                    "producto_nombre": "producto",
                    "cantidad_vendida": "cantidad",
                    "precio_venta": "precio",
                },
            },
        }

    monkeypatch.setattr("aiva_collector.cli.activate_collector", fake_activate)
    monkeypatch.setattr("aiva_collector.cli.save_token", lambda *args, **kwargs: None)
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.service_status", lambda self: {})
    monkeypatch.setattr("aiva_collector.cli._run_activation_discovery", lambda config: None)

    code = main(["activate", "--config", str(tmp_path / "config.json")])

    assert code == 0
    assert captured["kwargs"]["backend_url"] == DEFAULT_BACKEND_URL
    assert captured["kwargs"]["collector_version"] == DEFAULT_COLLECTOR_VERSION


def test_activate_runs_initial_discovery(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("aiva_collector.cli.stable_machine_id", lambda: "machine-test")
    monkeypatch.setattr("aiva_collector.cli.socket.gethostname", lambda: "host-test")
    monkeypatch.setattr(
        "aiva_collector.cli.activate_collector",
        lambda **kwargs: {
            "commerce_id": "commerce-1",
            "collector_id": "collector-1",
            "collector_token": "aiva_col_secret",
            "collector_version": "0.2.1",
            "config_defaults": {
                "input_dir": str(tmp_path / "input"),
                "processed_dir": str(tmp_path / "processed"),
                "error_dir": str(tmp_path / "error"),
                "output_dir": str(tmp_path / "output"),
                "state_dir": str(tmp_path / "state"),
                "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
                "column_mapping": {"producto_nombre": "producto", "cantidad_vendida": "cantidad", "precio_venta": "precio"},
            },
        },
    )
    monkeypatch.setattr("aiva_collector.cli.save_token", lambda *args, **kwargs: None)
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.service_status", lambda self: {})
    monkeypatch.setattr("aiva_collector.cli._run_activation_discovery", lambda config: calls.append(config.collector_id))

    assert main(["activate", "--backend-url", "http://backend", "--code", "AIVA-8F3K-91QZ", "--config", str(tmp_path / "config.json")]) == 0
    assert calls == ["collector-1"]


def test_selected_input_source_is_reported_as_explicit_active_candidate(monkeypatch, tmp_path):
    from aiva_collector.cli import _report_selected_input_source
    from aiva_collector.config import CollectorConfig

    payloads = []
    config = CollectorConfig(
        raw={
            "backend_url": "http://backend",
            "commerce_id": "commerce-1",
            "collector_id": "collector-1",
            "collector_token": "aiva_col_secret",
            "input_dir": str(tmp_path / "Ventas"),
        },
        config_path=tmp_path / "config.json",
    )
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_data_source_discovery", lambda self, payload: payloads.append(payload) or {"ok": True})

    _report_selected_input_source(config)

    assert payloads[0]["selected_explicit"] is True
    assert payloads[0]["detected_path"] == str(tmp_path / "Ventas")


def test_activate_detects_code_pasted_in_backend_url(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "aiva_col_wrong_field" if "Backend URL" in prompt else "AIVA-8F3K-91QZ")

    code = main(["activate"])

    assert code == 2
    assert "Parece que pegaste el código en el campo URL" in capsys.readouterr().err


def test_activate_rejects_backend_url_without_scheme(capsys):
    code = main(["activate", "--backend-url", "187.77.44.118:8080", "--code", "AIVA-8F3K-91QZ"])

    assert code == 2
    assert "Debe empezar con http:// o https://" in capsys.readouterr().err
