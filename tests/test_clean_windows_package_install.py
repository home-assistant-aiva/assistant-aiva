import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "test_clean_windows_package_install",
    Path("scripts/test_clean_windows_package_install.py"),
)
clean_install = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(clean_install)


def _minimal_config():
    return {
        "collector_version": "0.1.0",
        "backend_url": "http://127.0.0.1:8080",
        "commerce_id": "commerce_demo",
        "collector_id": "collector_demo",
        "collector_token_env": "AIVA_COLLECTOR_TOKEN",
        "input_dir": "samples/input",
        "processed_dir": "samples/processed",
        "error_dir": "samples/error",
        "output_dir": "samples/output",
        "state_dir": "state",
        "log_file": "logs/aiva_collector.log",
        "periodo": "weekly",
        "date_format": "%Y-%m-%d",
        "encoding": "utf-8",
        "delimiter": ",",
        "max_products_per_summary": 1000,
        "move_processed_files": False,
        "column_mapping": {
            "fecha": "fecha",
            "producto_codigo": "producto_codigo",
            "producto_nombre": "producto_nombre",
            "categoria": "categoria",
            "cantidad_vendida": "cantidad_vendida",
            "precio_venta": "precio_venta",
            "costo_unitario": "costo_unitario",
            "stock_actual": "stock_actual",
        },
    }


def _write_minimal_install(root: Path) -> None:
    (root / "aiva_collector").mkdir(parents=True)
    (root / "windows").mkdir()
    (root / "docs").mkdir()
    (root / "configs").mkdir()
    (root / "samples" / "input").mkdir(parents=True)
    (root / "samples" / "output").mkdir(parents=True)
    (root / "samples" / "processed").mkdir(parents=True)
    (root / "samples" / "error").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "state").mkdir()
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "configs" / "example_config.json").write_text(json.dumps(_minimal_config()), encoding="utf-8")
    (root / "samples" / "input" / "ventas_demo.csv").write_text(
        "fecha,producto_nombre,cantidad_vendida,precio_venta\n2026-06-01,Demo,1,10\n",
        encoding="utf-8",
    )


def _make_minimal_zip(path: Path, extra_files: dict[str, str] | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        files = {
            "aiva_collector/__init__.py": "__version__ = '0.1.0'\n",
            "windows/README_WINDOWS.md": "windows\n",
            "docs/aiva_collector_windows_package.md": "docs\n",
            "README.md": "readme\n",
            "pyproject.toml": "[project]\nname='demo'\n",
            "configs/example_config.json": json.dumps(_minimal_config()),
            "samples/input/ventas_demo.csv": "fecha,producto_nombre,cantidad_vendida,precio_venta\n2026-06-01,Demo,1,10\n",
            "samples/output/.gitkeep": "",
            "samples/processed/.gitkeep": "",
            "samples/error/.gitkeep": "",
            "logs/.gitkeep": "",
            "state/.gitkeep": "",
        }
        files.update(extra_files or {})
        for name, content in files.items():
            archive.writestr(name, content)


def test_detects_missing_structure(tmp_path):
    _write_minimal_install(tmp_path)
    (tmp_path / "README.md").unlink()
    with pytest.raises(clean_install.CleanInstallError, match="Falta estructura"):
        clean_install.validate_structure(tmp_path)


def test_fails_if_zip_contains_config_local(tmp_path):
    _write_minimal_install(tmp_path)
    (tmp_path / "config.local.json").write_text("{}", encoding="utf-8")
    with pytest.raises(clean_install.CleanInstallError, match="config.local.json"):
        clean_install.validate_forbidden_files(tmp_path)


def test_fails_if_zip_contains_env(tmp_path):
    _write_minimal_install(tmp_path)
    (tmp_path / ".env").write_text("SAFE=1", encoding="utf-8")
    with pytest.raises(clean_install.CleanInstallError, match=".env"):
        clean_install.validate_forbidden_files(tmp_path)


def test_fails_if_zip_contains_fake_secret(tmp_path):
    _write_minimal_install(tmp_path)
    (tmp_path / "docs" / "bad.txt").write_text("OPENAI_API_KEY=sk-fakefakefakefake", encoding="utf-8")
    with pytest.raises(clean_install.CleanInstallError, match="OPENAI_API_KEY"):
        clean_install.validate_no_secrets_in_package(tmp_path)


def test_generates_temp_config_without_token(tmp_path):
    _write_minimal_install(tmp_path)
    config_path = clean_install.create_clean_config(tmp_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    rendered = json.dumps(data)
    assert "collector_token" not in data
    assert data["collector_token_env"] == "AIVA_COLLECTOR_TOKEN"
    assert str(tmp_path) in data["input_dir"]
    assert "PEGAR_TOKEN_AQUI" not in rendered


def test_detects_runtime_reference_to_opt_collector(tmp_path):
    _write_minimal_install(tmp_path)
    (tmp_path / clean_install.RUNTIME_CONFIG_NAME).write_text(
        json.dumps({"input_dir": "/opt/aiva-collector/samples/input"}),
        encoding="utf-8",
    )
    with pytest.raises(clean_install.CleanInstallError, match="/opt/aiva-collector"):
        clean_install.validate_runtime_isolation(tmp_path)


def test_keep_temp_preserves_temp_dir(monkeypatch, tmp_path):
    zip_path = tmp_path / "package.zip"
    _make_minimal_zip(zip_path)
    monkeypatch.setattr(clean_install.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(clean_install.time, "time", lambda: 123)
    monkeypatch.setattr(clean_install, "create_venv_and_install", lambda install_dir: Path(sys.executable))
    monkeypatch.setattr(
        clean_install,
        "run_cli_dry_install",
        lambda install_dir, python_bin, config_path: (
            subprocess.CompletedProcess(["validate"], 0, stdout="Config valida\n", stderr=""),
            subprocess.CompletedProcess(["run-once"], 0, stdout="Dry-run: no se envio nada al backend.\n", stderr=""),
        ),
    )
    monkeypatch.setattr(clean_install, "validate_summary", lambda install_dir: (install_dir / "samples/output/last_summary.json", 1))

    result = clean_install.run_clean_install(zip_path, keep_temp=True)

    assert result["cleaned_temp"] is False
    assert Path(result["temp_install_dir"]) == tmp_path / "aiva_collector_clean_install_123"
    assert Path(result["temp_install_dir"]).exists()


def test_run_cli_dry_install_never_uses_send_or_backend(monkeypatch, tmp_path):
    calls = []

    def fake_run_checked(command, *, cwd, env, label):
        calls.append(command)
        stdout = "Dry-run: no se envio nada al backend.\n" if "run-once" in command else "Config valida\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(clean_install, "run_checked", fake_run_checked)
    clean_install.run_cli_dry_install(tmp_path, Path(sys.executable), tmp_path / clean_install.RUNTIME_CONFIG_NAME)

    rendered = " ".join(" ".join(command) for command in calls)
    assert "--send" not in rendered
    assert "run_demo_send" not in rendered
    assert "run_backend_integration_demo" not in rendered
    assert len(calls) == 2
