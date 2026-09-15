from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from aiva_collector.version import (
    INSTALLER_FILENAME,
    INSTALLER_MANIFEST_FILENAME,
    PUBLIC_VERSION,
    VERSION,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "pyinstaller" / "aiva_collector.spec"
INNO_PATH = ROOT / "packaging" / "inno" / "aiva_collector_setup.iss"
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "aiva-collector"
EXE_PATH = APP_DIR / "aiva-collector.exe"
CLI_EXE_PATH = APP_DIR / "aiva-collector-cli.exe"
BACKGROUND_EXE_PATH = APP_DIR / "aiva-collector-background.exe"
INSTALLER_PATH = DIST_DIR / INSTALLER_FILENAME
TECH_ZIP_PATH = DIST_DIR / f"aiva-collector-windows-exe-v{PUBLIC_VERSION}.zip"
MANIFEST_PATH = DIST_DIR / INSTALLER_MANIFEST_FILENAME

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
    EXE_PATH,
    CLI_EXE_PATH,
    BACKGROUND_EXE_PATH,
    ROOT / "docs" / "aiva_collector_windows_exe.md",
    ROOT / "docs" / "aiva_collector_windows_installer.md",
    ROOT / "windows" / "config.windows.example.json",
    ROOT / "packaging" / "windows_runtime" / "run_validate.bat",
    ROOT / "packaging" / "windows_runtime" / "activate.bat",
    ROOT / "packaging" / "windows_runtime" / "run_dry.bat",
    ROOT / "packaging" / "windows_runtime" / "run_auto.bat",
    ROOT / "packaging" / "windows_runtime" / "run_status.bat",
    ROOT / "packaging" / "windows_runtime" / "run_queue_status.bat",
    ROOT / "packaging" / "windows_runtime" / "run_retry_pending.bat",
    ROOT / "packaging" / "windows_runtime" / "run_send.bat",
    ROOT / "packaging" / "windows_runtime" / "diagnose_config.bat",
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


def directory_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256(item)))
    return digest.hexdigest(), len(files)


def build_commit() -> str | None:
    value = os.getenv("AIVA_BUILD_COMMIT", "").strip().lower()
    if not value:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise VerifyError("AIVA_BUILD_COMMIT no es un SHA Git completo")
    return value


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
        'name="aiva-collector-cli"',
        'name="aiva-collector-background"',
        "console=True",
        "console=False",
        "aiva_collector_entrypoint.py",
        "aiva_collector_cli_entrypoint.py",
        "aiva_collector_background_entrypoint.py",
        '"tkinter"',
        '"requests"',
        '"openpyxl"',
        '"certifi"',
        'excludes=["tests", "pytest"]',
        "COLLECT(",
        "exclude_binaries=True",
        "generate_windows_version_info.py",
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise VerifyError("Spec incompleto: " + ", ".join(missing))
    if str(ROOT) in text:
        raise VerifyError("Spec contiene ruta absoluta del workspace")
    if "upx=True" in text or text.count("upx=False") != 4:
        raise VerifyError("UPX debe estar deshabilitado en los tres EXE y en COLLECT")


def assert_inno_safe(inno_path: Path = INNO_PATH) -> None:
    if not inno_path.exists():
        raise VerifyError(f"No existe Inno script: {inno_path}")
    text = inno_path.read_text(encoding="utf-8")
    assert_text_file_safe(inno_path)
    required = [
        "#ifndef AppVersion",
        "#ifndef PublicVersion",
        "AppVersion={#AppVersion}",
        "OutputBaseFilename=AIVA-Collector-Setup-v{#PublicVersion}",
        "Source: \"..\\..\\dist\\aiva-collector\\*\"",
        "recursesubdirs createallsubdirs",
        "Compression=zip",
        "SolidCompression=no",
        "DestName: \"config.windows.json\"; Flags: onlyifdoesntexist",
        "{commonappdata}\\AIVA\\Collector\\entrada",
        "{commonappdata}\\AIVA\\Collector\\estado\\queue",
        "{commonappdata}\\AIVA\\Collector\\diagnostico",
        'Filename: "{app}\\install_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated',
        'Filename: "{app}\\uninstall_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated skipifdoesntexist',
        'Filename: "{app}\\{#AppExeName}"; Description: "Abrir AIVA Collector"',
        "Permissions: users-modify",
        'Source: "..\\windows_runtime\\*.bat"',
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise VerifyError("Inno script incompleto: " + ", ".join(missing))
    if "Compression=lzma" in text or "SolidCompression=yes" in text:
        raise VerifyError("Inno usa compresion anidada agresiva")


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
        if path.name == "install_scheduled_task.bat":
            xml_text = lowered.replace("^", "")
            if "aiva-collector-background.exe" not in lowered:
                raise VerifyError("La tarea automatica debe usar aiva-collector-background.exe")
            for forbidden in ("<command>%~dp0aiva-collector.exe</command>", "<command>run_auto.bat</command>", "<command>cmd.exe</command>", "powershell"):
                if forbidden in xml_text:
                    raise VerifyError(f"install_scheduled_task.bat programa comando prohibido: {forbidden}")
            for required in (
                "<hidden>true</hidden>",
                "<multipleinstancespolicy>ignorenew</multipleinstancespolicy>",
                "<delay>pt60s</delay>",
                "<interval>pt15m</interval>",
                "<executiontimelimit>%task_limit%</executiontimelimit>",
                "<restartonfailure><interval>pt5m</interval><count>3</count></restartonfailure>",
                '<arguments>run-auto --config "%aiva_root%\\config.windows.json"</arguments>',
            ):
                if required not in xml_text:
                    raise VerifyError(f"install_scheduled_task.bat no configura {required}")
            if "aiva_collector_token" in xml_text or "collector_token" in xml_text:
                raise VerifyError("install_scheduled_task.bat no debe pasar token en argumentos")
        if path.name == "collect_diagnostics.bat":
            for forbidden in ("curl", "invoke-webrequest", "invoke-restmethod", "--send"):
                if forbidden in lowered:
                    raise VerifyError(f"Diagnostico contiene accion prohibida: {forbidden}")
        if path.name == "uninstall_scheduled_task.bat":
            if 'if /i "%~1"=="/quiet"' not in lowered:
                raise VerifyError("uninstall_scheduled_task.bat debe soportar /quiet")
    run_send = (root / "packaging" / "windows_runtime" / "run_send.bat").read_text(encoding="utf-8")
    prompt = run_send.find("Escribi ENVIAR")
    confirm = run_send.find('if /I not "%CONFIRM%"=="ENVIAR"')
    send = run_send.find('"%AIVA_EXE%" send')
    if not (0 <= prompt < confirm < send):
        raise VerifyError("run_send.bat no protege envio con confirmacion")


def create_technical_zip(zip_path: Path = TECH_ZIP_PATH) -> Path:
    package_files = list(TECH_ZIP_FILES)
    if APP_DIR.is_dir():
        package_files.extend(path for path in APP_DIR.rglob("*") if path.is_file())
    package_files = sorted(set(package_files), key=lambda path: path.relative_to(ROOT).as_posix())
    missing = [path for path in package_files if not path.exists()]
    if missing:
        raise VerifyError("Faltan archivos para ZIP tecnico: " + ", ".join(str(path) for path in missing))
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = zip_path.with_suffix(".zip.tmp")
    tmp_path.unlink(missing_ok=True)
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in package_files:
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
    bundle_hash = None
    bundle_files = 0
    if APP_DIR.is_dir():
        bundle_hash, bundle_files = directory_sha256(APP_DIR)
    manifest = {
        "name": "AIVA Collector Windows Installer",
        "version": VERSION,
        "build_commit": build_commit(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pyinstaller_mode": "onedir",
        "upx_enabled": False,
        "bundle_sha256": bundle_hash,
        "bundle_files": bundle_files,
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
        support_dir = APP_DIR / "_internal"
        if not support_dir.is_dir() or not any(path.is_file() for path in support_dir.rglob("*")):
            raise VerifyError(f"No existe contenido de soporte onedir: {support_dir}")
        for path in (EXE_PATH, CLI_EXE_PATH, BACKGROUND_EXE_PATH, INSTALLER_PATH):
            if not path.exists():
                raise VerifyError(f"No existe artifact requerido: {path}")
            artifacts.append(path)
    elif EXE_PATH.exists():
        artifacts.append(EXE_PATH)
        if CLI_EXE_PATH.exists():
            artifacts.append(CLI_EXE_PATH)
        if BACKGROUND_EXE_PATH.exists():
            artifacts.append(BACKGROUND_EXE_PATH)
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
