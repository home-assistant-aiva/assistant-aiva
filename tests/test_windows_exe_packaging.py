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
    cli_entrypoint = Path("packaging/pyinstaller/aiva_collector_cli_entrypoint.py").read_text(encoding="utf-8")
    background_entrypoint = Path("packaging/pyinstaller/aiva_collector_background_entrypoint.py").read_text(encoding="utf-8")
    assert "from aiva_collector.desktop_app import main" in entrypoint
    assert "desktop-startup.log" in entrypoint
    assert "from aiva_collector.cli import main" in cli_entrypoint
    assert "redirect_stdout" in background_entrypoint


def test_inno_script_is_safe_and_preserves_existing_config():
    verify_windows_exe_package.assert_inno_safe()
    content = Path("packaging/inno/aiva_collector_setup.iss").read_text(encoding="utf-8")
    assert "onlyifdoesntexist" in content
    assert "AIVA-Collector-Setup-v0.2.7-desktop-rc2" in content
    assert "aiva-collector-cli.exe" in content
    assert "aiva-collector-background.exe" in content
    assert 'Name: "{group}\\AIVA Collector"; Filename: "{app}\\{#AppExeName}"' in content
    assert 'Filename: "{app}\\activate.bat"' not in content
    assert 'Filename: "{app}\\install_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated' in content
    assert 'Filename: "{app}\\uninstall_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated skipifdoesntexist' in content
    assert "run_discovery_dry.bat" not in content.split("[Run]", maxsplit=1)[1]


def test_installer_runtime_wrappers_are_safe():
    verify_windows_exe_package.assert_runtime_wrappers_safe()
    content = Path("packaging/windows_runtime/install_scheduled_task.bat").read_text(encoding="utf-8").lower()
    xml_content = content.replace("^", "")
    assert "<command>%aiva_exe%</command>" in xml_content
    assert "set \"aiva_exe=%~dp0aiva-collector-background.exe\"" in content
    assert "<arguments>run-auto --config \"%aiva_root%\\config.windows.json\"</arguments>" in xml_content
    assert "run_auto.bat" not in xml_content
    assert "powershell" not in xml_content
    uninstall = Path("packaging/windows_runtime/uninstall_scheduled_task.bat").read_text(encoding="utf-8").lower()
    assert 'if /i "%~1"=="/quiet"' in uninstall


def test_windows_workflow_runs_real_installer_verification_without_publishing():
    workflow = Path(".github/workflows/build-collector-windows-release.yml").read_text(encoding="utf-8")
    script = Path("scripts/verify_windows_installer.ps1").read_text(encoding="utf-8")
    assert "verify_windows_installer.ps1" in workflow
    assert "publish_release" in workflow
    assert "AIVA-Collector-Setup-v0.2.7-desktop-rc2.exe" in script
    assert "/VERYSILENT" in script
    assert "SIMULATED-RC1-TOKEN" in script
    assert "Get-AuthenticodeSignature" in script
    assert "unins000.exe" in script


def test_verify_without_artifacts_writes_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(verify_windows_exe_package, "MANIFEST_PATH", manifest)
    result = verify_windows_exe_package.verify(create_zip=False, require_artifacts=False)
    assert result["manifest"] == str(manifest)
    assert manifest.exists()
