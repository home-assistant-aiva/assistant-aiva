import importlib.util
import json
from pathlib import Path

import pytest


VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_windows_exe_package", Path("scripts/verify_windows_exe_package.py")
)
verify_windows_exe_package = importlib.util.module_from_spec(VERIFY_SPEC)
assert VERIFY_SPEC.loader is not None
VERIFY_SPEC.loader.exec_module(verify_windows_exe_package)


OFFICIAL_WORKFLOW_PATH = Path(".github/workflows/build-collector-windows-release.yml")
RETIRED_WORKFLOW_PATH = Path(".github/workflows/build-windows-installer.yml")


def _job(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"  {name}:")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("  ") and not lines[index].startswith("    ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _step(job: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = job.index(marker)
    following = job.find("\n      - name:", start + len(marker))
    return job[start:] if following == -1 else job[start:following]


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
    assert "OutputBaseFilename=AIVA-Collector-Setup-v{#PublicVersion}" in content
    assert '#define AppVersion "0.2.7rc3"' not in content
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
    assert 'ExpectedInstallerName = "AIVA-Collector-Setup-v$ExpectedPublicVersion.exe"' in script
    assert '"/DAppVersion=$env:AIVA_PACKAGE_VERSION"' in workflow
    assert '"/DPublicVersion=$env:AIVA_RELEASE_VERSION"' in workflow
    assert "/VERYSILENT" in script
    assert "SIMULATED-RC1-TOKEN" in script
    assert "Get-AuthenticodeSignature" in script
    assert "unins000.exe" in script
    assert "function Stop-InstalledCollectorProcesses" in script
    assert "taskkill.exe /PID $process.Id /T /F" in script
    assert script.count("Stop-InstalledCollectorProcesses") >= 4
    assert "function Assert-PreservedFiles" in script
    for evidence_field in (
        "config_preserved",
        "activation_preserved",
        "token_preserved",
        "state_preserved",
        "queue_preserved",
        "mappings_preserved",
        "logs_preserved",
        "source_folder_preserved",
        "binaries_replaced",
    ):
        assert evidence_field in script
    remove_task = script.split("function Remove-ScheduledTask", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "$global:LASTEXITCODE = 0" in remove_task


def test_only_one_official_windows_build_and_publication_workflow_exists():
    assert OFFICIAL_WORKFLOW_PATH.exists()
    assert not RETIRED_WORKFLOW_PATH.exists()
    workflow_files = sorted(Path(".github/workflows").glob("*.y*ml"))
    publishers = [
        path
        for path in workflow_files
        if "gh release create" in path.read_text(encoding="utf-8")
        or "ISCC.exe" in path.read_text(encoding="utf-8")
    ]
    assert publishers == [OFFICIAL_WORKFLOW_PATH]


def test_official_workflow_requires_explicit_manual_publication_opt_in():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger = workflow.split("\npermissions:", maxsplit=1)[0]
    assert "workflow_dispatch:" in trigger
    assert "publish_release:" in trigger
    assert "default: false" in trigger
    assert "\n  push:" not in trigger
    assert "\n  pull_request:" not in trigger
    assert "\n    tags:" not in trigger
    assert "if: github.event_name == 'workflow_dispatch' && inputs.publish_release == true" in workflow
    assert "startsWith(github.ref, 'refs/tags/')" not in workflow
    assert "inputs.release_tag" not in workflow


def test_official_workflow_separates_build_and_publish_permissions():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("contents: write") == 1
    assert "\n  publish:\n" in workflow
    assert "uses: actions/download-artifact@v4" in workflow


def test_official_workflow_rejects_release_name_collisions_without_clobber():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "Reject existing release or tag" in workflow
    assert "git check-ref-format" in workflow
    assert "gh release list" in workflow
    assert "gh api" in workflow
    assert "GH_REPO: ${{ github.repository }}" in workflow
    assert "Could not inspect existing releases" in workflow
    assert "Could not inspect existing tags" in workflow
    assert "Release or tag already exists" in workflow
    assert "AIVA_TARGET_SHA: ${{ needs.build-release.outputs.source_commit }}" in workflow
    assert "--clobber" not in workflow


def test_official_publication_is_serialized_and_reserves_tags_atomically():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    publish_job = _job(workflow, "publish")
    precheck = _step(publish_job, "Reject existing release or tag")
    reservation = _step(publish_job, "Reserve immutable release tag")
    publication = _step(publish_job, "Publish GitHub pre-release")

    assert "group: aiva-collector-release-publication" in publish_job
    assert "cancel-in-progress: false" in publish_job
    assert publish_job.index("- name: Reject existing release or tag") < publish_job.index(
        "- name: Reserve immutable release tag"
    ) < publish_job.index("- name: Publish GitHub pre-release")
    assert "gh release list" in precheck
    assert 'gh api --method POST "repos/$env:GITHUB_REPOSITORY/git/refs"' in reservation
    assert '-f ref="refs/tags/$tag" -f sha="$target"' in reservation
    assert "if ($LASTEXITCODE -ne 0)" in reservation
    assert "Reserved release tag target mismatch" in reservation
    assert 'gh release create "$env:AIVA_RELEASE_TAG"' in publication
    assert "--verify-tag" in publication
    assert "Release creation failed without overwriting existing resources" in publication
    assert "softprops/action-gh-release" not in publish_job
    assert "--clobber" not in publish_job
    assert "--method DELETE" not in publish_job


def test_official_workflow_builds_and_publishes_the_verified_source_commit():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    build_job = _job(workflow, "build-release")
    publish_job = _job(workflow, "publish")
    checkout = _step(build_job, "Checkout")
    revision = _step(build_job, "Verify immutable source revision")
    provenance = _step(publish_job, "Verify artifact source revision")

    assert "ref: ${{ github.sha }}" in checkout
    assert build_job.index("- name: Checkout") < build_job.index("- name: Verify immutable source revision")
    assert "git rev-parse HEAD" in revision
    assert "$actual -ne $expected" in revision
    assert "AIVA_BUILD_COMMIT=$actual" in revision
    assert "commit=$actual" in revision
    assert "source_commit: ${{ steps.source-revision.outputs.commit }}" in build_job
    assert "uses: actions/download-artifact@v4" in publish_job
    assert "AIVA_EXPECTED_SHA: ${{ needs.build-release.outputs.source_commit }}" in provenance
    assert 'if ($expected -ne "${{ github.sha }}".ToLowerInvariant())' in provenance
    assert "ConvertFrom-Json).build_commit" in provenance
    assert "Build evidence commit mismatch" in provenance
    assert "AIVA_TARGET_SHA: ${{ needs.build-release.outputs.source_commit }}" in publish_job


def test_official_workflow_reads_release_names_from_canonical_version_module():
    workflow = OFFICIAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "from aiva_collector.version import release_metadata" in workflow
    for output in (
        "package_version",
        "public_version",
        "release_tag",
        "release_title",
        "installer_filename",
        "installer_manifest_filename",
        "manual_zip_filename",
    ):
        assert f"{output}: ${{{{ steps.release-metadata.outputs.{output} }}}}" in workflow
    assert "0.2.7rc3" not in workflow
    assert "0.2.7-desktop-rc3" not in workflow


def test_installer_manifest_and_windows_evidence_record_build_commit(tmp_path, monkeypatch):
    build_sha = "a" * 40
    manifest = tmp_path / "manifest.json"
    monkeypatch.setenv("AIVA_BUILD_COMMIT", build_sha)
    monkeypatch.setattr(verify_windows_exe_package, "MANIFEST_PATH", manifest)

    verify_windows_exe_package.verify(create_zip=False, require_artifacts=False)

    assert json.loads(manifest.read_text(encoding="utf-8"))["build_commit"] == build_sha
    installer_verifier = Path("scripts/verify_windows_installer.ps1").read_text(encoding="utf-8")
    assert "build_commit = $BuildCommit.Trim().ToLowerInvariant()" in installer_verifier
    assert "AIVA_BUILD_COMMIT no identifica el commit compilado" in installer_verifier


def test_installer_manifest_rejects_invalid_build_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVA_BUILD_COMMIT", "branch-name")
    monkeypatch.setattr(verify_windows_exe_package, "MANIFEST_PATH", tmp_path / "manifest.json")

    with pytest.raises(verify_windows_exe_package.VerifyError, match="SHA Git completo"):
        verify_windows_exe_package.verify(create_zip=False, require_artifacts=False)


def test_verify_without_artifacts_writes_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(verify_windows_exe_package, "MANIFEST_PATH", manifest)
    result = verify_windows_exe_package.verify(create_zip=False, require_artifacts=False)
    assert result["manifest"] == str(manifest)
    assert manifest.exists()
