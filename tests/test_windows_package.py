import importlib.util
import json
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


REQUIRED_IN_ZIP = {
    "aiva_collector/__init__.py",
    "aiva_collector/cli.py",
    "windows/README_WINDOWS.md",
    "windows/config.windows.example.json",
    "windows/check_python.bat",
    "windows/collect_diagnostics.bat",
    "windows/install_manual.bat",
    "windows/install_dependencies.bat",
    "windows/run_validate.bat",
    "windows/run_dry.bat",
    "windows/run_discovery_dry.bat",
    "windows/run_discovery_report.bat",
    "windows/diagnose_config.bat",
    "windows/run_send.bat",
    "windows/run_status.bat",
    "windows/run_queue_status.bat",
    "windows/run_retry_pending.bat",
    "windows/set_token_example.bat",
    "windows/README_SUPPORT.md",
    "docs/aiva_collector_clean_install_test.md",
    "docs/aiva_collector_first_client_data_request.md",
    "docs/aiva_collector_offline_queue.md",
    "docs/aiva_collector_windows_manual.md",
    "docs/aiva_collector_windows_package.md",
    "docs/aiva_collector_windows_pilot_checklist.md",
    "docs/aiva_collector_windows_pilot_results_template.md",
    "README.md",
    "pyproject.toml",
    "configs/example_config.json",
    "samples/input/ventas_demo.csv",
    "samples/output/.gitkeep",
    "samples/processed/.gitkeep",
    "samples/error/.gitkeep",
    "logs/.gitkeep",
    "state/.gitkeep",
}


def _zip_names(path):
    with zipfile.ZipFile(path) as archive:
        return set(name for name in archive.namelist() if not name.endswith("/"))


def _zip_text(path, name):
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def test_build_creates_zip_manifest_and_required_files(tmp_path):
    zip_path, manifest_path, manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    names = _zip_names(zip_path)

    assert zip_path.exists()
    assert manifest_path.exists()
    assert manifest["package_name"] == "aiva-collector-windows-manual"
    assert manifest["version"] == "0.2.6rc6"
    assert manifest["safety_checks_passed"] is True
    assert manifest["files_count"] == len(names)
    assert REQUIRED_IN_ZIP <= names

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored["sha256"] == verify_windows_package.sha256(zip_path)


def test_zip_excludes_runtime_dev_and_local_files(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    names = _zip_names(zip_path)

    forbidden_names = {
        "config.local.json",
        ".env",
        "state/collector_state.json",
        "logs/aiva_collector.log",
        "samples/output/last_summary.json",
    }
    assert names.isdisjoint(forbidden_names)
    assert all(".venv/" not in name for name in names)
    assert all("__pycache__/" not in name for name in names)
    assert all(".pytest_cache/" not in name for name in names)
    assert all(".mypy_cache/" not in name for name in names)
    assert all(not name.startswith("tests/") for name in names)
    assert all(not name.startswith("dist/") for name in names)
    assert all(not name.endswith(".egg-info/PKG-INFO") for name in names)
    assert all(not name.startswith("samples/processed/") or name.endswith(".gitkeep") for name in names)
    assert all(not name.startswith("samples/error/") or name.endswith(".gitkeep") for name in names)


def test_zip_text_files_do_not_contain_real_secret_patterns(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    result = verify_windows_package.verify_package(zip_path)
    assert result["manifest_checked"] is True


def test_run_send_requires_enviar_and_install_manual_preserves_config(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)

    run_send = _zip_text(zip_path, "windows/run_send.bat")
    token_check = run_send.index('if "%AIVA_COLLECTOR_TOKEN%"==""')
    prompt = run_send.index("Escribi ENVIAR")
    confirm_check = run_send.index('if /I not "%CONFIRM%"=="ENVIAR"')
    send = run_send.index("--send")
    assert token_check < prompt < confirm_check < send

    install_manual = _zip_text(zip_path, "windows/install_manual.bat")
    assert 'if not exist "%AIVA_ROOT%\\config.local.json"' in install_manual
    assert "Config existente detectada. No se pisa" in install_manual


def test_windows_example_config_has_no_token(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    config = json.loads(_zip_text(zip_path, "windows/config.windows.example.json"))
    assert "collector_token" not in config
    assert config["collector_token_env"] == "AIVA_COLLECTOR_TOKEN"


def test_verify_package_fails_for_forbidden_file(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as archive:
        for name in REQUIRED_IN_ZIP:
            if name.endswith(".json"):
                archive.writestr(name, "{}")
            else:
                archive.writestr(name, "placeholder")
        archive.writestr(".env", "SAFE_PLACEHOLDER=1")

    assert verify_windows_package.main([str(bad_zip)]) == 1


def test_verify_package_fails_for_secret_pattern(tmp_path):
    zip_path, _manifest_path, _manifest = build_windows_package.build_package(Path.cwd(), tmp_path)
    bad_zip = tmp_path / "bad-secret.zip"
    with zipfile.ZipFile(zip_path) as source, zipfile.ZipFile(bad_zip, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        target.writestr("windows/secret.txt", "OPENAI_API_KEY=sk-fakefakefakefake")

    assert verify_windows_package.main([str(bad_zip)]) == 1
