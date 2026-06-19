import json
from pathlib import Path

from aiva_collector.cli import main


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


def test_move_processed_false_keeps_file():
    source = Path("samples/input/ventas_demo.csv")
    assert source.exists()
    code = main(["run-once", "--config", "configs/example_config.json"])
    assert code == 0
    assert source.exists()
