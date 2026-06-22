import importlib.util
from pathlib import Path


VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_windows_exe_package", Path("scripts/verify_windows_exe_package.py")
)
verify_windows_exe_package = importlib.util.module_from_spec(VERIFY_SPEC)
assert VERIFY_SPEC.loader is not None
VERIFY_SPEC.loader.exec_module(verify_windows_exe_package)


def test_pyinstaller_spec_is_safe_and_complete():
    verify_windows_exe_package.assert_spec_safe()
    entrypoint = Path("packaging/pyinstaller/aiva_collector_entrypoint.py").read_text(encoding="utf-8")
    assert "from aiva_collector.cli import main" in entrypoint


def test_inno_script_is_safe_and_preserves_existing_config():
    verify_windows_exe_package.assert_inno_safe()
    content = Path("packaging/inno/aiva_collector_setup.iss").read_text(encoding="utf-8")
    assert "onlyifdoesntexist" in content
    assert "AIVA-Collector-Setup-v0.2.1" in content


def test_installer_runtime_wrappers_are_safe():
    verify_windows_exe_package.assert_runtime_wrappers_safe()


def test_verify_without_artifacts_writes_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(verify_windows_exe_package, "MANIFEST_PATH", manifest)
    result = verify_windows_exe_package.verify(create_zip=False, require_artifacts=False)
    assert result["manifest"] == str(manifest)
    assert manifest.exists()
