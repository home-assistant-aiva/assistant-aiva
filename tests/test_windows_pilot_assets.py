import importlib.util
import zipfile
from pathlib import Path


BUILD_SPEC = importlib.util.spec_from_file_location("build_windows_package", Path("scripts/build_windows_package.py"))
build_windows_package = importlib.util.module_from_spec(BUILD_SPEC)
assert BUILD_SPEC.loader is not None
BUILD_SPEC.loader.exec_module(build_windows_package)

VERIFY_SPEC = importlib.util.spec_from_file_location("verify_windows_package", Path("scripts/verify_windows_package.py"))
verify_windows_package = importlib.util.module_from_spec(VERIFY_SPEC)
assert VERIFY_SPEC.loader is not None
VERIFY_SPEC.loader.exec_module(verify_windows_package)


CHECKLIST = Path("docs/aiva_collector_windows_pilot_checklist.md")
RESULTS = Path("docs/aiva_collector_windows_pilot_results_template.md")
DATA_REQUEST = Path("docs/aiva_collector_first_client_data_request.md")
DIAGNOSTICS = Path("windows/collect_diagnostics.bat")
SUPPORT = Path("windows/README_SUPPORT.md")

PILOT_FILES = {
    "docs/aiva_collector_windows_pilot_checklist.md",
    "docs/aiva_collector_windows_pilot_results_template.md",
    "docs/aiva_collector_first_client_data_request.md",
    "windows/collect_diagnostics.bat",
    "windows/README_SUPPORT.md",
}


def test_pilot_checklist_mentions_main_flow():
    content = CHECKLIST.read_text(encoding="utf-8")
    assert "run_validate.bat" in content
    assert "run_dry.bat" in content
    assert "run_send.bat" in content
    assert "ENVIAR" in content
    assert "no se envio nada al backend" in content


def test_results_template_contains_main_fields():
    content = RESULTS.read_text(encoding="utf-8")
    for field in (
        "Fecha de prueba",
        "Python version",
        "Tipo de archivo",
        "Columnas originales",
        "run_validate",
        "run_dry",
        "Filas leidas",
        "Filas validas",
        "Filas descartadas",
        "Productos resumidos",
        "Facturacion total",
        "Margen estimado",
        "run_send ejecutado",
        "Idempotencia observada",
        "Reporte generado",
        "Decision",
    ):
        assert field in content


def test_first_client_data_request_sets_boundaries():
    content = DATA_REQUEST.read_text(encoding="utf-8")
    assert "Exportacion de ventas" in content
    assert "CSV o Excel" in content
    assert "No hace falta clave" in content or "no necesitamos contrase" in content.lower()
    assert "AIVA no modifica" in content
    assert "Contrase" in content
    assert "Base de datos completa" in content
    assert "Que no pedir" in content


def test_collect_diagnostics_is_local_and_token_safe():
    content = DIAGNOSTICS.read_text(encoding="utf-8")
    lowered = content.lower()
    forbidden = [
        "run_send",
        "--send",
        "curl",
        "invoke-webrequest",
        "invoke-restmethod",
        "/commerce/",
        "/admin/",
        "authorization: bearer",
        "aiva_internal_secret",
        "telegram_bot_token",
        "openai_api_key",
    ]
    for value in forbidden:
        assert value not in lowered
    assert "collector_token" in content
    assert "PSObject.Properties.Remove('collector_token')" in content
    assert "Compress-Archive" in content
    assert "NoProfile" in content
    assert "no envia nada por internet" in lowered


def test_support_readme_warns_against_sensitive_sharing():
    content = SUPPORT.read_text(encoding="utf-8")
    lowered = content.lower()
    assert "nunca mandar token" in lowered
    assert "contrase" in lowered
    assert "collect_diagnostics.bat" in content
    assert "no llama al backend" in lowered


def test_zip_builder_includes_pilot_assets_and_verify_accepts(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert PILOT_FILES <= names
    result = verify_windows_package.verify_package(zip_path)
    assert result["manifest_checked"] is True
