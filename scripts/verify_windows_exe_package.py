from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.1"
SPEC_PATH = ROOT / "packaging" / "pyinstaller" / "aiva_collector.spec"
INNO_PATH = ROOT / "packaging" / "inno" / "aiva_collector_setup.iss"
DIST_DIR = ROOT / "dist"
EXE_PATH = DIST_DIR / "aiva-collector.exe"
INSTALLER_PATH = DIST_DIR / "AIVA-Collector-Setup-v0.2.1.exe"
TECH_ZIP_PATH = DIST_DIR / "aiva-collector-windows-exe-v0.2.1.zip"
MANIFEST_PATH = DIST_DIR / "AIVA-Collector-Installer-v0.2.1.manifest.json"

FORBIDDEN_TEXT = [
    "/opt/aiva-collector",
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "AIVA_INTERNAL_SECRET",
    "collector_token=",
    "config.local.json\"; Source:",
]
FORBIDDEN_PACKAGE_NAMES = {
    ".env",
    "config.local.json",
    "collector_state.json",
    "last_summary.json",
}
SECRET_REGEXES = [
    ("Authorization: Bearer", re.compile(r"Authorization:\s*Bearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)),
    ("aiva_col_", re.compile(r"aiva_col_[A-Za-z0-9._-]{8,}")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9]{12,}")),
]
TECH_ZIP_FILES = [
    ROOT / "dist" / "aiva-collector.exe",
    ROOT / "docs" / "aiva_collector_windows_exe.md",
    ROOT / "docs" / "aiva_collector_windows_installer.md",
    ROOT / "windows" / "config.windows.example.json",
    ROOT / "packaging" / "windows_runtime" / "run_validate.bat",
    ROOT / "packaging" / "windows_runtime" / "activate.bat",
    ROOT / "packaging" / "windows_runtime" / "run_dry.bat",
    ROOT / "packaging" / "windows_runtime" / "run_auto.bat",
    ROOT / "packaging" / "windows_runtime" / "run_status.bat",
    ROOT / "packaging" / "windows_runtime" / "run_send.bat",
    ROOT / "packaging" / "windows_runtime" / "install_scheduled_task.bat",
    ROOT / "packaging" / "windows_runtime" / "uninstall_scheduled_task.bat",
    ROOT / "packaging" / "windows_runtime" / "collect_diagnostics.bat",
]


class VerifyError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_text_file_safe(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_TEXT:
        if forbidden in text:
            raise VerifyError(f"Texto prohibido en {path}: {forbidden}")
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern_name, regex in SECRET_REGEXES:
            if regex.search(line) and not (
                path.as_posix().endswith("aiva_collector.spec") and pattern_name == "Authorization: Bearer"
            ):
                raise VerifyError(f"Patron sensible en {path}:{line_number}: {pattern_name}")


def assert_spec_safe(spec_path: Path = SPEC_PATH) -> None:
    if not spec_path.exists():
        raise VerifyError(f"No existe spec: {spec_path}")
    text = spec_path.read_text(encoding="utf-8")
    assert_text_file_safe(spec_path)
    required = [
        'name="aiva-collector"',
        "console=True",
        "aiva_collector_entrypoint.py",
        '"requests"',
        '"openpyxl"',
        '"certifi"',
        'excludes=["tests", "pytest"]',
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise VerifyError("Spec incompleto: " + ", ".join(missing))
    if str(ROOT) in text:
        raise VerifyError("Spec contiene ruta absoluta del workspace")


def assert_inno_safe(inno_path: Path = INNO_PATH) -> None:
    if not inno_path.exists():
        raise VerifyError(f"No existe Inno script: {inno_path}")
    text = inno_path.read_text(encoding="utf-8")
    assert_text_file_safe(inno_path)
    required = [
        "OutputBaseFilename=AIVA-Collector-Setup-v0.2.1",
        "Source: \"..\\..\\dist\\aiva-collector.exe\"",
        "DestName: \"config.local.json\"; Flags: onlyifdoesntexist",
        "C:\\AIVA_Comercio\\entrada",
        "C:\\AIVA_Comercio\\diagnostico",
        "activate.bat",
        "run_auto.bat",
        "install_scheduled_task.bat",
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise VerifyError("Inno script incompleto: " + ", ".join(missing))


def assert_runtime_wrappers_safe(root: Path = ROOT) -> None:
    wrappers = sorted((root / "packaging" / "windows_runtime").glob("*.bat"))
    if not wrappers:
        raise VerifyError("No hay wrappers runtime")
    for path in wrappers:
        text = path.read_text(encoding="utf-8")
        assert_text_file_safe(path)
        lowered = text.lower()
        if path.name != "run_send.bat" and "--send" in lowered:
            raise VerifyError(f"{path} no debe ejecutar envio")
        if path.name == "collect_diagnostics.bat":
            for forbidden in ("curl", "invoke-webrequest", "invoke-restmethod", "--send"):
                if forbidden in lowered:
                    raise VerifyError(f"Diagnostico contiene accion prohibida: {forbidden}")
    run_send = (root / "packaging" / "windows_runtime" / "run_send.bat").read_text(encoding="utf-8")
    token_check = run_send.find('if "%AIVA_COLLECTOR_TOKEN%"==""')
    prompt = run_send.find("Escribi ENVIAR")
    confirm = run_send.find('if /I not "%CONFIRM%"=="ENVIAR"')
    send = run_send.find('"%AIVA_EXE%" send')
    if not (0 <= token_check < prompt < confirm < send):
        raise VerifyError("run_send.bat no protege envio con token y confirmacion")


def create_technical_zip(zip_path: Path = TECH_ZIP_PATH) -> Path:
    missing = [path for path in TECH_ZIP_FILES if not path.exists()]
    if missing:
        raise VerifyError("Faltan archivos para ZIP tecnico: " + ", ".join(str(path) for path in missing))
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = zip_path.with_suffix(".zip.tmp")
    tmp_path.unlink(missing_ok=True)
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in TECH_ZIP_FILES:
            if path.name in FORBIDDEN_PACKAGE_NAMES:
                raise VerifyError(f"Archivo prohibido para ZIP tecnico: {path}")
            archive.write(path, path.relative_to(ROOT).as_posix())
    tmp_path.replace(zip_path)
    return zip_path


def assert_zip_safe(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        for name in names:
            path = Path(name)
            if path.name in FORBIDDEN_PACKAGE_NAMES or path.name.endswith(".local.json") or path.name.endswith(".log"):
                raise VerifyError(f"Archivo prohibido en ZIP tecnico: {name}")
            if "tests" in path.parts or ".venv" in path.parts or "__pycache__" in path.parts:
                raise VerifyError(f"Ruta prohibida en ZIP tecnico: {name}")
            if path.suffix.lower() in {".bat", ".json", ".md", ".py", ".toml", ".txt"}:
                text = archive.read(name).decode("utf-8", errors="replace")
                for pattern_name, regex in SECRET_REGEXES:
                    if regex.search(text):
                        raise VerifyError(f"Patron sensible en ZIP tecnico {name}: {pattern_name}")


def write_manifest(paths: list[Path], manifest_path: Path | None = None) -> Path:
    if manifest_path is None:
        manifest_path = MANIFEST_PATH
    artifacts = []
    for path in paths:
        if path.exists():
            artifacts.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    manifest = {
        "name": "AIVA Collector Windows Installer",
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "safety_checks_passed": True,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return manifest_path


def verify(create_zip: bool = False, require_artifacts: bool = False) -> dict[str, object]:
    assert_spec_safe()
    assert_inno_safe()
    assert_runtime_wrappers_safe()

    artifacts = []
    if require_artifacts:
        for path in (EXE_PATH, INSTALLER_PATH):
            if not path.exists():
                raise VerifyError(f"No existe artifact requerido: {path}")
            artifacts.append(path)
    elif EXE_PATH.exists():
        artifacts.append(EXE_PATH)
    if create_zip:
        tech_zip = create_technical_zip()
        assert_zip_safe(tech_zip)
        artifacts.append(tech_zip)
    if INSTALLER_PATH.exists() and INSTALLER_PATH not in artifacts:
        artifacts.append(INSTALLER_PATH)

    manifest_path = write_manifest(artifacts)
    return {
        "manifest": str(manifest_path),
        "artifacts": [{"name": path.name, "sha256": sha256(path)} for path in artifacts],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Windows exe/installer packaging assets")
    parser.add_argument("--create-zip", action="store_true")
    parser.add_argument("--require-artifacts", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = verify(create_zip=args.create_zip, require_artifacts=args.require_artifacts)
    except (VerifyError, zipfile.BadZipFile) as exc:
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"VERIFY OK: {result['manifest']}")
    for artifact in result["artifacts"]:
        print(f"SHA256 {artifact['name']}: {artifact['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
