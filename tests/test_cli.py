import json
from pathlib import Path

import pytest

from aiva_collector.cli import (
    DEFAULT_BACKEND_URL,
    DEFAULT_COLLECTOR_VERSION,
    _single_run_lock,
    build_parser,
    interactive_menu,
    main,
    safe_display_path,
)
from aiva_collector.config import CollectorConfig


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


def test_cli_exposes_source_configuration_help():
    parser = build_parser()
    with pytest.raises(SystemExit) as configure:
        parser.parse_args(["configure-source", "--help"])
    assert configure.value.code == 0


def test_cli_without_args_opens_interactive_menu(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "0")

    code = main([])
    out = capsys.readouterr().out

    assert code == 0
    assert f"AIVA Collector {DEFAULT_COLLECTOR_VERSION}" in out
    assert "1. Procesar ahora" in out
    assert "Cerrando AIVA Collector." in out


def test_interactive_menu_processes_now_and_keeps_result_visible(monkeypatch, capsys):
    import aiva_collector.cli as cli

    commands = []
    answers = iter(["1", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "main", lambda command: commands.append(command) or 0)

    code = interactive_menu()
    out = capsys.readouterr().out

    assert code == 0
    assert commands == [["run-auto"]]
    assert "Procesar ahora" in out


def test_interactive_menu_opens_source_configuration(monkeypatch):
    import aiva_collector.cli as cli

    commands = []
    answers = iter(["2", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "main", lambda command: commands.append(command) or 0)

    assert interactive_menu() == 0
    assert commands == [["configure-source"]]


def test_interactive_menu_requires_confirmation_before_reporting(monkeypatch, capsys):
    import aiva_collector.cli as cli

    commands = []
    answers = iter(["8", "NO", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "main", lambda command: commands.append(command) or 0)

    assert interactive_menu() == 0
    assert commands == []
    assert "Operacion cancelada. No se envio nada." in capsys.readouterr().out


def test_configure_external_source_is_read_only_and_preserves_identity(tmp_path, capsys):
    source = tmp_path / "Ventas"
    source.mkdir()
    (source / "ventas.csv").write_text("producto,cantidad\nMate,1\n", encoding="utf-8")
    config_path = tmp_path / "config.local.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "commerce_id": "commerce-real",
            "collector_id": "collector-real",
            "collector_token": "token-no-mostrar",
            "state_dir": str(tmp_path / "state"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "log_file": str(tmp_path / "logs" / "collector.log"),
        }
    )
    config_path.write_text(json.dumps(data), encoding="utf-8")

    assert main(["configure-source", "--config", str(config_path), "--path", str(source)]) == 0

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["commerce_id"] == "commerce-real"
    assert updated["collector_id"] == "collector-real"
    assert updated["collector_token"] == "token-no-mostrar"
    assert updated["input_dir"] == str(source)
    assert updated["source_mode"] == "external_read_only"
    assert updated["move_processed_files"] is False
    assert updated["move_error_files"] is False
    assert updated["keep_original_files"] is True
    assert "token-no-mostrar" not in capsys.readouterr().out
    assert list((tmp_path / "backups").glob("config.source.*.json"))


def test_configure_default_source_creates_managed_input(tmp_path, monkeypatch):
    config_path = tmp_path / "config.local.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "commerce_id": "commerce",
            "collector_id": "collector",
            "input_dir": str(tmp_path / "old"),
            "state_dir": str(tmp_path / "state"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "log_file": str(tmp_path / "logs" / "collector.log"),
        }
    )
    config_path.write_text(json.dumps(data), encoding="utf-8")

    assert main(["configure-source", "--config", str(config_path), "--use-default"]) == 0

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["input_dir"] == str(tmp_path / "entrada")
    assert Path(updated["input_dir"]).is_dir()
    assert updated["source_mode"] == "aiva_managed"
    assert updated["move_processed_files"] is True
    assert updated["move_error_files"] is True
    assert updated["keep_original_files"] is False


def test_show_current_source_does_not_send_or_change_config(tmp_path, capsys):
    source = tmp_path / "Ventas"
    source.mkdir()
    config_path = tmp_path / "config.local.json"
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update({"input_dir": str(source), "source_mode": "external_read_only"})
    config_path.write_text(json.dumps(data), encoding="utf-8")
    before = config_path.read_bytes()

    assert main(["configure-source", "--config", str(config_path), "--show-current"]) == 0

    out = capsys.readouterr().out
    assert "Carpeta externa en modo solo lectura" in out
    assert str(source) in out
    assert config_path.read_bytes() == before


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

    code = main(["activate", "--config", str(tmp_path / "config.json")])

    assert code == 0
    assert captured["kwargs"]["backend_url"] == DEFAULT_BACKEND_URL
    assert captured["kwargs"]["collector_version"] == DEFAULT_COLLECTOR_VERSION


def test_activate_detects_code_pasted_in_backend_url(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "aiva_col_wrong_field" if "Backend URL" in prompt else "AIVA-8F3K-91QZ")

    code = main(["activate"])

    assert code == 2
    assert "Parece que pegaste el código en el campo URL" in capsys.readouterr().err


def test_activate_rejects_backend_url_without_scheme(capsys):
    code = main(["activate", "--backend-url", "187.77.44.118:8080", "--code", "AIVA-8F3K-91QZ"])

    assert code == 2
    assert "Debe empezar con http:// o https://" in capsys.readouterr().err
