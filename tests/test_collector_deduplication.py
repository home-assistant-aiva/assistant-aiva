import json
from pathlib import Path

from aiva_collector.cli import main
from aiva_collector.local_state import connect, local_db_path, queue_counts, status_counts
from aiva_collector.config import load_config
from aiva_collector.errors import BackendError


def _config(tmp_path: Path, *, move_processed: bool = True) -> Path:
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "backend_url": "http://127.0.0.1:9999",
            "commerce_id": "commerce-test",
            "collector_id": "collector-test",
            "input_dir": str(tmp_path / "input"),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "errores"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
            "move_processed_files": move_processed,
            "stable_file_interval_seconds": 0,
        }
    )
    (tmp_path / "input").mkdir()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_valid(path: Path, product: str = "Producto A") -> None:
    path.write_text(
        "fecha,producto_codigo,producto_nombre,categoria,cantidad_vendida,precio_venta,costo_unitario,stock_actual\n"
        f"2026-06-01,A,{product},Cat,2,100,60,5\n",
        encoding="utf-8",
    )


def _mock_backend(monkeypatch, sent: list[dict], *, fail: bool = False):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "token-test")
    monkeypatch.setattr("aiva_collector.cli._backend_mapping", lambda config: None)
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_status", lambda self, status, message=None: {})

    def send(self, summary):
        if fail:
            raise BackendError("backend down", status_code=None)
        sent.append(summary)
        return {"summary_id": f"summary-{len(sent)}", "_http_status_code": 201}

    monkeypatch.setattr("aiva_collector.cli.CollectorClient.send_summary", send)


def test_same_file_twice_does_not_send_again(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    source = tmp_path / "input" / "ventas.csv"
    _write_valid(source)
    sent: list[dict] = []
    _mock_backend(monkeypatch, sent)

    assert main(["run-auto", "--config", str(config_path)]) == 0
    _write_valid(source)
    assert main(["run-auto", "--config", str(config_path)]) == 0

    assert len(sent) == 1
    assert list((tmp_path / "processed" / "duplicados").glob("*.csv"))


def test_same_name_changed_content_processes_new_version(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    source = tmp_path / "input" / "ventas.csv"
    sent: list[dict] = []
    _mock_backend(monkeypatch, sent)

    _write_valid(source, "Producto A")
    assert main(["run-auto", "--config", str(config_path)]) == 0
    _write_valid(source, "Producto B")
    assert main(["run-auto", "--config", str(config_path)]) == 0

    assert len(sent) == 2


def test_dry_run_does_not_mark_sent(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    _write_valid(tmp_path / "input" / "ventas.csv")
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)

    assert main(["run-once", "--config", str(config_path)]) == 0

    config = load_config(config_path)
    assert not local_db_path(config).exists()


def test_blocking_error_does_not_send_and_moves_to_errors(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    (tmp_path / "input" / "ventas.csv").write_text("producto_nombre,cantidad_vendida,precio_venta\n,,\n", encoding="utf-8")
    sent: list[dict] = []
    _mock_backend(monkeypatch, sent)

    assert main(["run-auto", "--config", str(config_path)]) == 2

    assert sent == []
    assert list((tmp_path / "errores").glob("*.csv"))
    assert list((tmp_path / "errores").glob("*.error.txt"))


def test_backend_down_creates_pending_queue(tmp_path, monkeypatch):
    config_path = _config(tmp_path, move_processed=False)
    _write_valid(tmp_path / "input" / "ventas.csv")
    sent: list[dict] = []
    _mock_backend(monkeypatch, sent, fail=True)

    assert main(["run-auto", "--config", str(config_path)]) == 0

    config = load_config(config_path)
    conn = connect(local_db_path(config))
    try:
        assert status_counts(conn)["pending_send"] == 1
        assert queue_counts(conn)["pending"] == 1
    finally:
        conn.close()
