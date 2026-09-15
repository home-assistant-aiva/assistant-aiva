import importlib.util
import json
import re
from pathlib import Path

from aiva_collector.version import PUBLIC_VERSION


def _load_script(name: str):
    path = Path("scripts") / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


version_info = _load_script("generate_windows_version_info")
binary_security = _load_script("verify_windows_binary_security")
package_verifier = _load_script("verify_windows_exe_package")


WORKFLOW = Path(".github/workflows/build-collector-windows-release.yml")
SPEC = Path("packaging/pyinstaller/aiva_collector.spec")
INNO = Path("packaging/inno/aiva_collector_setup.iss")
INSTALLER_VERIFIER = Path("scripts/verify_windows_installer.ps1")
DEFENDER_VERIFIER = Path("scripts/verify_windows_defender.ps1")


def test_pyinstaller_uses_shared_onedir_and_disables_upx_everywhere():
    spec = SPEC.read_text(encoding="utf-8")

    assert "upx=True" not in spec
    assert spec.count("upx=False") == 4
    assert spec.count("exclude_binaries=True") == 3
    assert "COLLECT(" in spec
    assert 'name="aiva-collector"' in spec
    for filename in version_info.EXECUTABLE_METADATA:
        assert f'version=str(version_files["{filename}"])' in spec


def test_build_scripts_and_workflow_never_invoke_upx():
    invocation = re.compile(
        r"(?im)^\s*(?:&\s+)?(?:[\"']?[^ \r\n]*[\\/])?upx(?:\.exe)?[\"']?(?:\s|$)"
    )
    paths = [
        WORKFLOW,
        *Path("scripts").glob("*.py"),
        *Path("scripts").glob("*.ps1"),
    ]

    offenders = [
        path.as_posix()
        for path in paths
        if invocation.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_each_executable_has_consistent_distinct_pe_metadata():
    descriptions = set()
    for filename, metadata in version_info.EXECUTABLE_METADATA.items():
        rendered = version_info.render_version_info(filename)
        expected = binary_security.expected_metadata(filename)

        assert expected["CompanyName"] == "AIVA Comercial"
        assert expected["ProductName"] == "AIVA Collector"
        assert expected["FileDescription"] == metadata["description"]
        assert expected["OriginalFilename"] == filename
        assert expected["ProductVersion"] == PUBLIC_VERSION
        assert expected["LegalCopyright"] == version_info.COPYRIGHT
        for key, value in expected.items():
            assert f"StringStruct({key!r}, {value!r})" in rendered
        descriptions.add(expected["FileDescription"])

    assert len(descriptions) == 3


def test_inno_installs_complete_onedir_with_less_aggressive_compression():
    package_verifier.assert_inno_safe()
    inno = INNO.read_text(encoding="utf-8")

    assert 'Source: "..\\..\\dist\\aiva-collector\\*"' in inno
    assert "recursesubdirs createallsubdirs" in inno
    assert "Compression=zip" in inno
    assert "SolidCompression=no" in inno
    assert "Compression=lzma" not in inno
    assert "SolidCompression=yes" not in inno


def test_manifest_records_onedir_upx_policy_and_bundle_hash(tmp_path, monkeypatch):
    app_dir = tmp_path / "aiva-collector"
    internal = app_dir / "_internal"
    internal.mkdir(parents=True)
    (app_dir / "aiva-collector.exe").write_bytes(b"desktop")
    (internal / "python311.dll").write_bytes(b"runtime")
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(package_verifier, "APP_DIR", app_dir)

    package_verifier.write_manifest([], manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["pyinstaller_mode"] == "onedir"
    assert manifest["upx_enabled"] is False
    assert manifest["bundle_files"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["bundle_sha256"])


def test_workflow_uses_onedir_paths_and_publishes_security_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m pip install pyinstaller pefile" in workflow
    assert workflow.count("python scripts/verify_windows_binary_security.py") == 2
    assert '--extra-pe "dist\\$env:AIVA_INSTALLER_ASSET"' in workflow
    assert "Inspect Windows installer structure" in workflow
    assert r".\dist\aiva-collector\aiva-collector.exe" in workflow
    assert r".\dist\aiva-collector\aiva-collector-cli.exe" in workflow
    assert r".\dist\aiva-collector\aiva-collector-background.exe" in workflow
    assert r".\dist\aiva-collector.exe" not in workflow
    assert "-DefenderEvidencePath" in workflow
    for evidence in (
        "windows-binary-inspection.json",
        "windows-defender-scan.json",
        "windows-installer-verification.json",
    ):
        assert evidence in workflow
        assert f'"dist/{evidence}"' in workflow

    inspector = Path("scripts/verify_windows_binary_security.py").read_text(encoding="utf-8")
    assert '"pe_files":' in inspector
    assert '"additional_artifacts":' in inspector
    assert '"--extra-pe"' in inspector


def test_defender_check_validates_detection_evidence_and_authenticode():
    defender = DEFENDER_VERIFIER.read_text(encoding="utf-8")
    installer = INSTALLER_VERIFIER.read_text(encoding="utf-8")

    assert "Update-MpSignature -UpdateSource MicrosoftUpdateServer" in defender
    assert "Start-MpScan -ScanType CustomScan -ScanPath $target" in defender
    assert "Get-MpThreatDetection" in defender
    assert "Microsoft-Windows-Windows Defender/Operational" in defender
    assert "new_threat_detections" in defender
    assert "detection_events" in defender
    assert '$evidence.status = "detected"' in defender
    assert '$evidence.status = "unavailable"' in defender
    assert "throw" in defender.split('$evidence.status = "detected"', maxsplit=1)[1]
    assert "Get-AuthenticodeSignature" in defender
    assert "ScanPath @($BuiltAppDir, $Installer, $InstallDir)" in installer


def test_installer_upgrade_and_uninstall_guards_cover_persistent_data():
    installer = INSTALLER_VERIFIER.read_text(encoding="utf-8")

    assert '$taskXml -notmatch "token"' in installer
    assert "Assert-PreservedFiles $persistentHashes" in installer
    assert installer.count("Assert-PreservedFiles $persistentHashes") >= 2
    for field in (
        "config_preserved",
        "activation_preserved",
        "token_preserved",
        "state_preserved",
        "queue_preserved",
        "mappings_preserved",
        "logs_preserved",
        "source_folder_preserved",
        "uninstall",
    ):
        assert field in installer
