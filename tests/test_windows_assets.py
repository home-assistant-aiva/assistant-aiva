import json
from pathlib import Path

import pytest

from aiva_collector.config import CollectorConfig, ConfigError, load_config


WINDOWS_DIR = Path("windows")
WINDOWS_CONFIG = WINDOWS_DIR / "config.windows.example.json"
BAT_FILES = [
    WINDOWS_DIR / "check_python.bat",
    WINDOWS_DIR / "collect_diagnostics.bat",
    WINDOWS_DIR / "install_manual.bat",
    WINDOWS_DIR / "install_dependencies.bat",
    WINDOWS_DIR / "run_validate.bat",
    WINDOWS_DIR / "run_dry.bat",
    WINDOWS_DIR / "run_discovery_dry.bat",
    WINDOWS_DIR / "run_discovery_report.bat",
    WINDOWS_DIR / "diagnose_config.bat",
    WINDOWS_DIR / "run_send.bat",
    WINDOWS_DIR / "run_status.bat",
    WINDOWS_DIR / "run_queue_status.bat",
    WINDOWS_DIR / "run_retry_pending.bat",
    WINDOWS_DIR / "set_token_example.bat",
]


def test_windows_config_parses_and_does_not_contain_token(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config = load_config(WINDOWS_CONFIG)
    rendered = WINDOWS_CONFIG.read_text(encoding="utf-8")
    data = json.loads(rendered)
    assert config.commerce_id == "REEMPLAZAR_COMMERCE_ID"
    assert config.collector_id == "REEMPLAZAR_COLLECTOR_ID"
    assert config.collector_token_env == "AIVA_COLLECTOR_TOKEN"
    assert config.token is None
    assert "collector_token" not in data
    assert "PEGAR_TOKEN_AQUI" not in rendered


def test_windows_paths_are_not_prefixed_on_linux():
    config = load_config(WINDOWS_CONFIG)
    assert str(config.path("input_dir")) == "C:\\AIVA_Comercio\\entrada"
    assert str(config.path("log_file")) == "C:\\AIVA_Comercio\\logs\\aiva_collector.log"


def test_windows_paths_with_spaces_are_not_deformed():
    config = CollectorConfig(
        raw={
            "commerce_id": "commerce",
            "collector_id": "collector",
            "collector_token_env": "AIVA_COLLECTOR_TOKEN",
            "input_dir": "C:\\AIVA Comercio\\entrada",
            "column_mapping": {
                "producto_nombre": "Producto",
                "cantidad_vendida": "Cant.",
                "precio_venta": "Precio",
            },
        },
        config_path=Path("config.json"),
    )
    assert str(config.path("input_dir")) == "C:\\AIVA Comercio\\entrada"


def test_linux_relative_and_absolute_paths_still_work(tmp_path):
    relative = CollectorConfig(
        raw={
            "commerce_id": "commerce",
            "collector_id": "collector",
            "input_dir": "samples/input",
            "column_mapping": {
                "producto_nombre": "producto_nombre",
                "cantidad_vendida": "cantidad_vendida",
                "precio_venta": "precio_venta",
            },
        },
        config_path=Path("config.json"),
    )
    absolute = CollectorConfig(
        raw={
            "commerce_id": "commerce",
            "collector_id": "collector",
            "input_dir": str(tmp_path),
            "column_mapping": {
                "producto_nombre": "producto_nombre",
                "cantidad_vendida": "cantidad_vendida",
                "precio_venta": "precio_venta",
            },
        },
        config_path=Path("config.json"),
    )
    assert relative.path("input_dir").parts[-2:] == ("samples", "input")
    assert absolute.path("input_dir") == tmp_path


def test_dry_run_allows_missing_token_but_send_requires_token(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config = load_config(WINDOWS_CONFIG)
    assert config.token is None
    with pytest.raises(ConfigError, match="Falta token"):
        config.require_send_ready()


def test_windows_bats_do_not_contain_real_tokens():
    forbidden = [
        "collector_token=",
        "AIVA_INTERNAL_SECRET",
        "Bearer ",
        "commerce_8001a29d8ef7",
        "commerce_e551bd02d6dc",
    ]
    for path in BAT_FILES:
        content = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in content


def test_run_send_requires_token_and_confirmation_before_send():
    content = (WINDOWS_DIR / "run_send.bat").read_text(encoding="utf-8")
    token_check = content.index('if "%AIVA_COLLECTOR_TOKEN%"==""')
    prompt = content.index("Escribi ENVIAR")
    confirm_check = content.index('if /I not "%CONFIRM%"=="ENVIAR"')
    send = content.index("--send")
    assert token_check < prompt < confirm_check < send
    assert "Falta AIVA_COLLECTOR_TOKEN. No se envio nada." in content


def test_run_discovery_report_lets_exe_resolve_token_from_config():
    content = (WINDOWS_DIR / "run_discovery_report.bat").read_text(encoding="utf-8")
    assert "AIVA_COLLECTOR_TOKEN" not in content
    assert "discover --report" in content


def test_non_send_bats_do_not_execute_send():
    for name in (
        "run_validate.bat",
        "run_dry.bat",
        "run_discovery_dry.bat",
        "diagnose_config.bat",
        "run_status.bat",
        "run_queue_status.bat",
        "run_retry_pending.bat",
        "install_manual.bat",
        "install_dependencies.bat",
        "collect_diagnostics.bat",
    ):
        content = (WINDOWS_DIR / name).read_text(encoding="utf-8")
        assert "--send" not in content


def test_install_manual_does_not_overwrite_existing_config():
    content = (WINDOWS_DIR / "install_manual.bat").read_text(encoding="utf-8")
    assert 'if not exist "%AIVA_ROOT%\\config.local.json"' in content
    assert "Config existente detectada. No se pisa" in content


def test_windows_docs_exist_and_warn_against_token_sharing():
    for path in (WINDOWS_DIR / "README_WINDOWS.md", Path("docs/aiva_collector_windows_manual.md")):
        content = path.read_text(encoding="utf-8")
        assert "Nunca pedir" in content
        assert "No guarda" not in content or "token" in content
