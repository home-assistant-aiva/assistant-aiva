import json
from pathlib import Path

from aiva_collector.cli import build_parser, main, safe_display_path


def test_cli_run_once_dry_generates_last_summary(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    output = Path("samples/output/last_summary.json")
    if output.exists():
        output.unlink()
    code = main(["run-once", "--config", "configs/example_config.json"])
    assert code == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["metadata"]["filas_validas"] > 0


def test_cli_send_without_token_fails(monkeypatch, capsys):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    code = main(["run-once", "--config", "configs/example_config.json", "--send"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Falta token" in captured.err


def test_cli_send_alias_without_token_fails(monkeypatch, capsys):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    code = main(["send", "--config", "configs/example_config.json"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Falta token" in captured.err


def test_cli_windows_default_config(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    parser = build_parser()
    args = parser.parse_args(["validate"])
    assert args.config == "C:\\AIVA_Comercio\\config.local.json"


def test_move_processed_false_keeps_file():
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
