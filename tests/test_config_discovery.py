import json
import os
from pathlib import Path

from aiva_collector.cli import main
from aiva_collector.config_discovery import (
    migrate_config_to_standard_location,
    resolve_runtime_config,
    score_config_candidate,
    select_best_config_candidate,
)


def _write_config(path: Path, **overrides) -> Path:
    data = {
        "backend_url": "http://backend",
        "commerce_id": "commerce",
        "collector_id": "collector",
        "collector_token": "secret-token",
        "input_dir": str(path.parent / "input"),
        "processed_dir": str(path.parent / "processed"),
        "error_dir": str(path.parent / "error"),
        "output_dir": str(path.parent / "output"),
        "state_dir": str(path.parent / "state"),
        "log_file": str(path.parent / "logs" / "aiva.log"),
    }
    data.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_detects_config_next_to_exe(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path / "exe" / "config.windows.json")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(tmp_path / "standard" / "config.windows.json"))

    result = resolve_runtime_config(search_dirs=[config_path.parent])

    assert result.config.commerce_id == "commerce"
    assert result.config.token == "secret-token"


def test_detects_programdata_and_aiva_comercio_variants(tmp_path, monkeypatch):
    programdata = _write_config(tmp_path / "ProgramData" / "AIVA Collector" / "config.windows.json", commerce_id="programdata")
    comercio_copy = _write_config(tmp_path / "AIVA_Comercio_2.5 - copia" / "config.local.json", commerce_id="copy")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(programdata))

    result = resolve_runtime_config(search_dirs=[programdata.parent, comercio_copy.parent])

    assert result.selected_path == programdata
    assert result.config.commerce_id == "programdata"


def test_ignores_example_template_and_selects_recent_valid(tmp_path):
    example = _write_config(tmp_path / "config.windows.example.json", commerce_id="REEMPLAZAR_COMMERCE_ID")
    old = _write_config(tmp_path / "old" / "config.local.json", commerce_id="old")
    new = _write_config(tmp_path / "AIVA_Comercio" / "config.local.json", commerce_id="new")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))

    best = select_best_config_candidate([example, old, new])

    assert best is not None
    assert best.path == new
    assert score_config_candidate(example).score < score_config_candidate(new).score


def test_migrates_config_to_standard_and_backs_up_invalid_existing(tmp_path):
    source = _write_config(tmp_path / "AIVA_Comercio" / "config.local.json")
    standard = tmp_path / "ProgramData" / "AIVA Collector" / "config.windows.json"
    standard.parent.mkdir(parents=True)
    standard.write_text('{"backend_url": ""}', encoding="utf-8")

    selected, backup, migrated = migrate_config_to_standard_location(source, standard_path=standard)

    assert selected == standard
    assert migrated is True
    assert backup is not None and backup.exists()
    assert source.exists()
    data = json.loads(standard.read_text(encoding="utf-8"))
    assert data["backend_url"] == "http://backend"
    assert data["commerce_id"] == "commerce"
    assert data["collector_id"] == "collector"
    assert data["collector_token"] == "secret-token"


def test_diagnose_config_does_not_print_token(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path / "AIVA_Comercio" / "config.local.json")
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(tmp_path / "standard" / "config.windows.json"))
    monkeypatch.setenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS", str(config_path.parent))

    code = main(["diagnose-config"])
    out = capsys.readouterr().out

    assert code == 0
    assert "secret-token" not in out
    assert '"selected_token_configured": true' in out


def test_discover_report_uses_token_from_config(tmp_path, monkeypatch):
    folder = tmp_path / "Sistema" / "Reportes"
    folder.mkdir(parents=True)
    (folder / "ventas.csv").write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path / "AIVA_Comercio" / "config.local.json",
        discovery={"include_paths": [str(tmp_path)], "include_user_dirs": False, "include_database_services": False},
    )
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(tmp_path / "standard" / "config.windows.json"))
    monkeypatch.setenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS", str(config_path.parent))
    calls = []

    def fake_post(self, payload):
        calls.append((self.config.token, payload))
        return {"_http_status_code": 201}

    monkeypatch.setattr("aiva_collector.client.CollectorClient.post_data_source_discovery", fake_post)

    assert main(["discover", "--report"]) == 0
    assert calls and calls[0][0] == "secret-token"


def test_discover_report_fails_clear_without_token(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "Sistema" / "Reportes"
    folder.mkdir(parents=True)
    (folder / "ventas.csv").write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path / "AIVA_Comercio" / "config.local.json",
        collector_token="",
        discovery={"include_paths": [str(tmp_path)], "include_user_dirs": False, "include_database_services": False},
    )
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(tmp_path / "standard" / "config.windows.json"))
    monkeypatch.setenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS", str(config_path.parent))

    code = main(["discover", "--report"])
    err = capsys.readouterr().err

    assert code == 2
    assert "No se encontró token del Collector" in err
    assert "No se envió nada" in err


def test_discover_dry_run_works_without_token(tmp_path, monkeypatch):
    folder = tmp_path / "Sistema" / "Reportes"
    folder.mkdir(parents=True)
    (folder / "ventas.csv").write_text("producto,cantidad\nA,1\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path / "AIVA_Comercio" / "config.local.json",
        collector_token="",
        discovery={"include_paths": [str(tmp_path)], "include_user_dirs": False, "include_database_services": False},
    )
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(tmp_path / "standard" / "config.windows.json"))
    monkeypatch.setenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS", str(config_path.parent))

    assert main(["discover", "--dry-run"]) == 0
