from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


REQUIRED_FILES = {
    "aiva_collector/__init__.py",
    "aiva_collector/cli.py",
    "windows/README_WINDOWS.md",
    "windows/config.windows.example.json",
    "windows/check_python.bat",
    "windows/install_manual.bat",
    "windows/install_dependencies.bat",
    "windows/collect_diagnostics.bat",
    "windows/run_validate.bat",
    "windows/run_dry.bat",
    "windows/run_send.bat",
    "windows/run_status.bat",
    "windows/set_token_example.bat",
    "windows/README_SUPPORT.md",
    "docs/aiva_collector_clean_install_test.md",
    "docs/aiva_collector_first_client_data_request.md",
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

FORBIDDEN_PARTS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    "tests",
}

FORBIDDEN_FILE_NAMES = {
    ".env",
    "config.local.json",
    "collector_state.json",
    "last_summary.json",
}

SECRET_REGEXES = [
    ("AIVA_INTERNAL_SECRET=", re.compile(r"AIVA_INTERNAL_SECRET\s*=")),
    ("TELEGRAM_BOT_TOKEN=", re.compile(r"TELEGRAM_BOT_TOKEN\s*=")),
    ("OPENAI_API_KEY=", re.compile(r"OPENAI_API_KEY\s*=")),
    ("Authorization: Bearer", re.compile(r"Authorization:\s*Bearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)),
    ("aiva_col_", re.compile(r"aiva_col_[A-Za-z0-9._-]{8,}")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9]{12,}")),
]

TEXT_SUFFIXES = {".bat", ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".sh", ".toml", ".txt", ""}


class VerifyError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8", errors="replace")


def assert_no_forbidden_paths(names: list[str]) -> None:
    for name in names:
        path = Path(name)
        parts = set(path.parts)
        if parts & FORBIDDEN_PARTS:
            raise VerifyError(f"Ruta prohibida en ZIP: {name}")
        if path.name in FORBIDDEN_FILE_NAMES or path.name.endswith(".local.json") or path.name.endswith(".log"):
            raise VerifyError(f"Archivo prohibido en ZIP: {name}")
        if path.match("samples/output/*.json"):
            raise VerifyError(f"Output real prohibido en ZIP: {name}")
        if len(path.parts) >= 2 and path.parts[:2] in (("samples", "processed"), ("samples", "error")) and path.name != ".gitkeep":
            raise VerifyError(f"Archivo runtime prohibido en ZIP: {name}")
        if any(part.endswith(".egg-info") for part in path.parts):
            raise VerifyError(f"Metadata de build prohibida en ZIP: {name}")


def assert_required_files(names: set[str]) -> None:
    missing = sorted(REQUIRED_FILES - names)
    if missing:
        raise VerifyError("Faltan archivos obligatorios: " + ", ".join(missing))


def line_is_safe_code(name: str, pattern_name: str, line: str) -> bool:
    if pattern_name == "Authorization: Bearer" and name == "aiva_collector/client.py" and 'f"Bearer {token}"' in line:
        return True
    if pattern_name == "collector_token" and name == "aiva_collector/cli.py" and 'response["collector_token"]' in line:
        return True
    return False


def assert_no_secrets(archive: zipfile.ZipFile, names: list[str]) -> None:
    for name in names:
        suffix = Path(name).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        text = read_text(archive, name)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, regex in SECRET_REGEXES:
                if regex.search(line) and not line_is_safe_code(name, pattern_name, line):
                    raise VerifyError(f"Se detecto patron sensible en {name}:{line_number}: {pattern_name}")


def assert_windows_assets(archive: zipfile.ZipFile) -> None:
    run_send = read_text(archive, "windows/run_send.bat")
    token_check = run_send.find('if "%AIVA_COLLECTOR_TOKEN%"==""')
    prompt = run_send.find("ENVIAR")
    confirm = run_send.find('if /I not "%CONFIRM%"=="ENVIAR"')
    send = run_send.find("--send")
    if not (0 <= token_check < prompt < confirm < send):
        raise VerifyError("run_send.bat no exige token y confirmacion ENVIAR antes de --send")

    if re.search(r"AIVA_COLLECTOR_TOKEN\s*=\s*[A-Za-z0-9._-]{8,}", run_send):
        raise VerifyError("run_send.bat contiene un token real o ejemplo inseguro")

    config = json.loads(read_text(archive, "windows/config.windows.example.json"))
    if "collector_token" in config:
        raise VerifyError("config.windows.example.json no debe contener collector_token")
    if config.get("collector_token_env") != "AIVA_COLLECTOR_TOKEN":
        raise VerifyError("config.windows.example.json debe usar collector_token_env")

    install_manual = read_text(archive, "windows/install_manual.bat")
    if 'if not exist "%AIVA_ROOT%\\config.local.json"' not in install_manual:
        raise VerifyError("install_manual.bat debe proteger config.local.json existente")
    if "Config existente detectada. No se pisa" not in install_manual:
        raise VerifyError("install_manual.bat debe avisar que no pisa config existente")

    diagnostics = read_text(archive, "windows/collect_diagnostics.bat")
    lowered = diagnostics.lower()
    forbidden = ["run_send", "--send", "curl", "invoke-webrequest", "invoke-restmethod", "/commerce/", "/admin/"]
    for value in forbidden:
        if value in lowered:
            raise VerifyError(f"collect_diagnostics.bat contiene accion prohibida: {value}")
    if re.search(r"AIVA_COLLECTOR_TOKEN\s*=\s*[A-Za-z0-9._-]{8,}", diagnostics):
        raise VerifyError("collect_diagnostics.bat contiene token real o ejemplo inseguro")


def verify_package(zip_path: Path) -> dict[str, object]:
    if not zip_path.exists():
        raise VerifyError(f"No existe ZIP: {zip_path}")
    if zip_path.suffix.lower() != ".zip":
        raise VerifyError(f"No es un ZIP: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        name_set = set(names)
        assert_required_files(name_set)
        assert_no_forbidden_paths(names)
        assert_no_secrets(archive, names)
        assert_windows_assets(archive)

    digest = sha256(zip_path)
    manifest_path = zip_path.with_name(zip_path.name.removesuffix(".zip") + ".manifest.json")
    manifest_ok = False
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_ok = manifest.get("sha256") == digest and manifest.get("safety_checks_passed") is True
        if not manifest_ok:
            raise VerifyError("Manifest no coincide con sha256 o safety_checks_passed")

    return {"zip_path": str(zip_path), "sha256": digest, "manifest_checked": manifest_ok}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify AIVA Collector Windows manual ZIP")
    parser.add_argument("zip_path")
    args = parser.parse_args(argv)

    try:
        result = verify_package(Path(args.zip_path))
    except (VerifyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"VERIFY OK: {result['zip_path']}")
    print(f"SHA256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
