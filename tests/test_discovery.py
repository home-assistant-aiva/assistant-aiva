import builtins
import json
from pathlib import Path

import pytest

from aiva_collector.cli import main
from aiva_collector.config import CollectorConfig
from aiva_collector.discovery import (
    DiscoveryCandidate,
    DiscoveryConfig,
    DiscoveryReporter,
    DiscoveryScanner,
)
from aiva_collector.errors import BackendError
from aiva_collector.local_state import connect, queue_counts


def _scanner(root: Path, **kwargs) -> DiscoveryScanner:
    return DiscoveryScanner(DiscoveryConfig(include_paths=(root,), include_user_dirs=False, include_program_dirs=False, timeout_seconds=10, **kwargs))


def _config(tmp_path: Path) -> CollectorConfig:
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
            "column_mapping": {"producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"},
        },
        config_path=tmp_path / "config.json",
    )


def _write_config(tmp_path: Path, include_path: Path | None = None) -> Path:
    data = {
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
        "column_mapping": {"producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"},
    }
    if include_path:
        data["discovery"] = {"include_paths": [str(include_path)], "include_user_dirs": False, "include_program_dirs": False}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_scanner_detects_candidate_folder_with_ventas_csv(tmp_path):
    folder = tmp_path / "Reportes"
    folder.mkdir()
    (folder / "ventas.csv").write_text("no debe leerse", encoding="utf-8")

    candidates = _scanner(tmp_path).scan()

    assert any(item.source_type == "watched_folder" and item.detected_path == str(folder) for item in candidates)


def test_scanner_detects_candidate_folder_with_stock_xlsx(tmp_path):
    folder = tmp_path / "Ventas"
    folder.mkdir()
    (folder / "stock.xlsx").write_bytes(b"fake")

    candidates = _scanner(tmp_path).scan()

    assert any(item.capabilities.get("xlsx") for item in candidates if item.detected_path == str(folder))


def test_scanner_ignores_excluded_directories(tmp_path):
    folder = tmp_path / ".git" / "Reportes"
    folder.mkdir(parents=True)
    (folder / "ventas.csv").write_text("x", encoding="utf-8")

    assert _scanner(tmp_path).scan() == []


def test_scanner_respects_max_total_candidates(tmp_path):
    for index in range(5):
        folder = tmp_path / f"Reportes{index}"
        folder.mkdir()
        (folder / f"ventas{index}.csv").write_text("x", encoding="utf-8")

    candidates = _scanner(tmp_path, max_total_candidates=2).scan()

    assert len(candidates) == 2


def test_scanner_does_not_read_file_content(tmp_path, monkeypatch):
    folder = tmp_path / "Reportes"
    folder.mkdir()
    (folder / "ventas.csv").write_text("contenido sensible", encoding="utf-8")
    original_open = builtins.open

    def guarded_open(*args, **kwargs):
        if args and str(args[0]).endswith("ventas.csv"):
            raise AssertionError("Discovery no debe abrir archivos candidatos")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    assert _scanner(tmp_path).scan()


@pytest.mark.parametrize(
    ("filename", "engine"),
    [("sistema.db", "sqlite"), ("sistema.accdb", "access"), ("sistema.fdb", "firebird")],
)
def test_scanner_detects_database_files(tmp_path, filename, engine):
    folder = tmp_path / "Sistema"
    folder.mkdir()
    (folder / filename).write_bytes(b"fake")

    candidates = _scanner(tmp_path).scan()

    assert any(item.source_type == "database" and item.detected_engine == engine for item in candidates)


def test_score_high_for_aiva_comercial_entrada(tmp_path):
    folder = tmp_path / "AIVA" / "Comercial" / "Entrada"
    folder.mkdir(parents=True)
    (folder / "ventas.csv").write_text("x", encoding="utf-8")

    candidate = _scanner(tmp_path).scan()[0]

    assert candidate.confidence >= 0.8


def test_score_medium_for_documents_sales_file(tmp_path):
    folder = tmp_path / "Documents"
    folder.mkdir()
    (folder / "ventas.xlsx").write_bytes(b"fake")

    candidate = _scanner(tmp_path).scan()[0]

    assert 0.5 <= candidate.confidence <= 0.79


def test_personal_file_is_ignored(tmp_path):
    folder = tmp_path / "Reportes"
    folder.mkdir()
    (folder / "banco_personal.csv").write_text("x", encoding="utf-8")

    assert _scanner(tmp_path).scan() == []


def test_deduplication_by_path_keeps_highest_confidence(tmp_path):
    scanner = _scanner(tmp_path)
    low = DiscoveryCandidate("watched_folder", "A", 0.3, detected_path=str(tmp_path))
    high = DiscoveryCandidate("watched_folder", "B", 0.9, detected_path=str(tmp_path))

    result = scanner.deduplicate_candidates([low, high])

    assert len(result) == 1
    assert result[0].name == "B"


def test_sanitization_removes_secret_keys(tmp_path):
    scanner = _scanner(tmp_path)
    candidate = DiscoveryCandidate("watched_folder", "A", 0.5, detected_path=str(tmp_path), raw_discovery={"token": "secret", "ok": True})

    payload = scanner.to_backend_payload(scanner.sanitize_candidate(candidate), _config(tmp_path))

    assert "secret" not in json.dumps(payload)
    assert "token" not in json.dumps(payload)


def test_dry_run_cli_does_not_call_backend(tmp_path, monkeypatch):
    folder = tmp_path / "Reportes"
    folder.mkdir()
    (folder / "ventas.csv").write_text("x", encoding="utf-8")
    config_path = _write_config(tmp_path, folder)

    def fail_backend(*args, **kwargs):
        raise AssertionError("dry-run no debe llamar backend")

    monkeypatch.setattr("aiva_collector.client.CollectorClient.post_data_source_discovery", fail_backend)

    assert main(["discover", "--config", str(config_path), "--dry-run"]) == 0


def test_cli_json_outputs_stable_format(tmp_path, capsys):
    folder = tmp_path / "Reportes"
    folder.mkdir()
    (folder / "ventas.csv").write_text("x", encoding="utf-8")
    config_path = _write_config(tmp_path, folder)

    code = main(["discover", "--config", str(config_path), "--dry-run", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    assert data["ok"] is True
    assert data["items"][0]["source_type"] == "watched_folder"


class Client:
    def __init__(self, response):
        self.response = response
        self.payloads = []

    def post_data_source_discovery(self, payload):
        self.payloads.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_report_calls_backend_with_expected_payload(tmp_path):
    config = _config(tmp_path)
    client = Client({"discovery": {"discovery_id": "dsd-1"}, "_http_status_code": 200})
    scanner = _scanner(tmp_path)
    candidate = DiscoveryCandidate("watched_folder", "Reportes detectados", 0.8, detected_path=r"C:\Reportes", capabilities={"csv": True})

    result = DiscoveryReporter(config, client=client).report_discoveries([candidate], scanner)

    assert result.sent == 1
    assert client.payloads[0]["source_type"] == "watched_folder"
    assert client.payloads[0]["detected_path"] == r"C:\Reportes"


def test_backend_failure_goes_to_offline_queue(tmp_path):
    config = _config(tmp_path)
    client = Client(BackendError("backend down"))
    scanner = _scanner(tmp_path)
    candidate = DiscoveryCandidate("watched_folder", "Reportes detectados", 0.8, detected_path=r"C:\Reportes", capabilities={"csv": True})

    result = DiscoveryReporter(config, client=client).report_discoveries([candidate], scanner)
    conn = connect(tmp_path / "state" / "aiva_collector.db")
    try:
        counts = queue_counts(conn)
    finally:
        conn.close()

    assert result.queued == 1
    assert counts["pending"] == 1


def test_service_discovery_on_non_windows_does_not_fail(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")

    assert DiscoveryScanner(DiscoveryConfig(include_user_dirs=False, include_program_dirs=False)).scan_database_services() == []
