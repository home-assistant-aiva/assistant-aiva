from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST_DIR = PROJECT_ROOT / "dist"
RUNTIME_CONFIG_NAME = "config.clean-test.local.json"
VENV_DIR_NAME = ".venv_clean_test"
PROJECT_ROOT_MARKER = "/opt/aiva-collector"

REQUIRED_PATHS = [
    Path("aiva_collector"),
    Path("windows"),
    Path("docs"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("configs/example_config.json"),
    Path("samples/input/ventas_demo.csv"),
    Path("logs"),
    Path("state"),
    Path("samples/output"),
    Path("samples/processed"),
    Path("samples/error"),
]

FORBIDDEN_NAMES = {
    ".env",
    "config.local.json",
    "collector_state.json",
    "last_summary.json",
}

FORBIDDEN_PARTS = {
    "tests",
    "__pycache__",
    ".pytest_cache",
}

SECRET_REGEXES = [
    ("AIVA_INTERNAL_SECRET", re.compile(r"AIVA_INTERNAL_SECRET\s*=")),
    ("TELEGRAM_BOT_TOKEN", re.compile(r"TELEGRAM_BOT_TOKEN\s*=")),
    ("OPENAI_API_KEY", re.compile(r"OPENAI_API_KEY\s*=")),
    ("Authorization: Bearer", re.compile(r"Authorization:\s*Bearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)),
    ("aiva_col_", re.compile(r"aiva_col_[A-Za-z0-9._-]{8,}")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9]{12,}")),
    ("collector_token", re.compile(r"collector_token")),
]

TEXT_SUFFIXES = {".bat", ".cfg", ".csv", ".ini", ".json", ".log", ".md", ".py", ".sh", ".toml", ".txt", ""}
RUNTIME_SCAN_PATHS = [
    Path(RUNTIME_CONFIG_NAME),
    Path("samples/output/last_summary.json"),
    Path("logs/aiva_collector.log"),
    Path("state/collector_state.json"),
]


class CleanInstallError(RuntimeError):
    pass


def latest_zip(dist_dir: Path = DEFAULT_DIST_DIR) -> Path:
    candidates = sorted(dist_dir.glob("aiva-collector-windows-manual-v*.zip"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise CleanInstallError(f"No se encontraron ZIPs en {dist_dir}")
    return candidates[-1]


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_path(path: Path) -> tuple[bool, int | None, int | None]:
    if not path.exists():
        return (False, None, None)
    stat = path.stat()
    return (True, stat.st_size, stat.st_mtime_ns)


def extract_zip(zip_path: Path, install_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(install_dir)


def validate_structure(install_dir: Path) -> None:
    missing = [str(path) for path in REQUIRED_PATHS if not (install_dir / path).exists()]
    if missing:
        raise CleanInstallError("Falta estructura obligatoria: " + ", ".join(missing))


def validate_forbidden_files(install_dir: Path) -> None:
    for path in install_dir.rglob("*"):
        relative = path.relative_to(install_dir)
        parts = set(relative.parts)
        if path.is_dir() and path.name == VENV_DIR_NAME:
            continue
        if path.name == VENV_DIR_NAME:
            continue
        if parts & FORBIDDEN_PARTS:
            raise CleanInstallError(f"Ruta prohibida en instalacion limpia: {relative.as_posix()}")
        if path.name in FORBIDDEN_NAMES or path.name.endswith(".local.json") or path.name.endswith(".log"):
            raise CleanInstallError(f"Archivo runtime/local prohibido antes de ejecutar: {relative.as_posix()}")
        if relative.match("logs/*.log"):
            raise CleanInstallError(f"Log real prohibido antes de ejecutar: {relative.as_posix()}")
        if relative.match("samples/output/*.json"):
            raise CleanInstallError(f"Output real prohibido antes de ejecutar: {relative.as_posix()}")


def line_is_allowed(pattern_name: str, line: str) -> bool:
    if pattern_name == "collector_token":
        safe_contexts = (
            "collector_token_env",
            "collector_token no debe guardarse",
            "No guardar `collector_token`",
            "No guarda `collector_token`",
            "no guarda `collector_token`",
            "sin `collector_token`",
            '"collector_token" in data',
            '"collector_token" not in data',
            '"collector_token",',
            "Properties.Remove('collector_token')",
        )
        return any(context in line for context in safe_contexts)
    if pattern_name == "Authorization: Bearer":
        return 'f"Bearer {token}"' in line
    return False


def scan_text_files(paths: Iterable[Path], base_dir: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(base_dir)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, regex in SECRET_REGEXES:
                if regex.search(line) and not line_is_allowed(pattern_name, line):
                    findings.append({"file": relative.as_posix(), "line": line_number, "pattern": pattern_name})
    return findings


def validate_no_secrets_in_package(install_dir: Path) -> None:
    findings = scan_text_files((path for path in install_dir.rglob("*") if path.is_file()), install_dir)
    if findings:
        first = findings[0]
        raise CleanInstallError(
            f"Se detecto patron sensible en {first['file']}:{first['line']}: {first['pattern']}"
        )


def create_clean_config(install_dir: Path) -> Path:
    source = install_dir / "configs" / "example_config.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data.update(
        {
            "backend_url": "http://127.0.0.1:8080",
            "commerce_id": "commerce_clean_test",
            "collector_id": "collector_clean_test",
            "collector_token_env": "AIVA_COLLECTOR_TOKEN",
            "input_dir": str((install_dir / "samples" / "input").resolve()),
            "processed_dir": str((install_dir / "samples" / "processed").resolve()),
            "error_dir": str((install_dir / "samples" / "error").resolve()),
            "output_dir": str((install_dir / "samples" / "output").resolve()),
            "state_dir": str((install_dir / "state").resolve()),
            "log_file": str((install_dir / "logs" / "aiva_collector.log").resolve()),
            "move_processed_files": False,
        }
    )
    data.pop("collector_token", None)
    config_path = install_dir / RUNTIME_CONFIG_NAME
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return config_path


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "AIVA_COLLECTOR_TOKEN",
        "AIVA_INTERNAL_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "PYTHONPATH",
    ):
        env.pop(key, None)
    return env


def venv_python(install_dir: Path) -> Path:
    if sys.platform == "win32":
        return install_dir / VENV_DIR_NAME / "Scripts" / "python.exe"
    return install_dir / VENV_DIR_NAME / "bin" / "python"


def run_command(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str], label: str) -> subprocess.CompletedProcess[str]:
    result = run_command(command, cwd=cwd, env=env)
    if result.returncode != 0:
        raise CleanInstallError(f"{label} fallo con exit={result.returncode}: {safe_output(result)}")
    return result


def safe_output(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stdout + "\n" + result.stderr).strip()
    return text[-1200:]


def create_venv_and_install(install_dir: Path) -> Path:
    venv.create(install_dir / VENV_DIR_NAME, with_pip=True)
    python_bin = venv_python(install_dir)
    env = clean_env()
    run_checked([str(python_bin), "-m", "pip", "install", "-U", "pip"], cwd=install_dir, env=env, label="pip install -U pip")
    run_checked([str(python_bin), "-m", "pip", "install", "-e", "."], cwd=install_dir, env=env, label="pip install -e .")
    return python_bin


def run_cli_dry_install(install_dir: Path, python_bin: Path, config_path: Path) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    env = clean_env()
    validate = run_checked(
        [str(python_bin), "-m", "aiva_collector.cli", "validate", "--config", str(config_path)],
        cwd=install_dir,
        env=env,
        label="validate",
    )
    dry_run = run_checked(
        [str(python_bin), "-m", "aiva_collector.cli", "run-once", "--config", str(config_path)],
        cwd=install_dir,
        env=env,
        label="run-once dry-run",
    )
    if "--send" in " ".join(validate.args) or "--send" in " ".join(dry_run.args):
        raise CleanInstallError("La prueba limpia intento ejecutar --send")
    if "Dry-run: no se envio nada al backend." not in dry_run.stdout:
        raise CleanInstallError("run-once no confirmo dry-run sin envio")
    return validate, dry_run


def validate_summary(install_dir: Path) -> tuple[Path, int]:
    summary_path = install_dir / "samples" / "output" / "last_summary.json"
    if not summary_path.exists():
        raise CleanInstallError(f"No se genero summary en {summary_path}")
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    products_count = len(data.get("productos_resumidos") or [])
    if products_count <= 0:
        raise CleanInstallError("last_summary.json no tiene productos_resumidos")
    metadata = data.get("metadata") or {}
    if int(metadata.get("filas_validas") or 0) <= 0:
        raise CleanInstallError("last_summary.json no tiene filas_validas > 0")
    return summary_path, products_count


def validate_runtime_isolation(install_dir: Path, marker: str = PROJECT_ROOT_MARKER) -> None:
    runtime_files = [install_dir / path for path in RUNTIME_SCAN_PATHS]
    for path in runtime_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if marker in text:
            raise CleanInstallError(f"Referencia runtime prohibida a {marker} en {path.relative_to(install_dir).as_posix()}")


def validate_runtime_secrets(install_dir: Path) -> None:
    runtime_files = [install_dir / path for path in RUNTIME_SCAN_PATHS]
    findings = scan_text_files(runtime_files, install_dir)
    if findings:
        first = findings[0]
        raise CleanInstallError(
            f"Se detecto secreto runtime en {first['file']}:{first['line']}: {first['pattern']}"
        )


def run_clean_install(zip_path: Path, *, keep_temp: bool = False) -> dict[str, object]:
    zip_path = zip_path.resolve()
    if not zip_path.exists():
        raise CleanInstallError(f"No existe ZIP: {zip_path}")

    temp_parent = Path(tempfile.gettempdir()) / f"aiva_collector_clean_install_{int(time.time())}"
    temp_parent.mkdir(parents=False, exist_ok=False)
    install_dir = temp_parent
    source_summary = PROJECT_ROOT / "samples" / "output" / "last_summary.json"
    source_summary_before = snapshot_path(source_summary)
    cleaned = False

    try:
        extract_zip(zip_path, install_dir)
        validate_structure(install_dir)
        validate_forbidden_files(install_dir)
        validate_no_secrets_in_package(install_dir)
        config_path = create_clean_config(install_dir)
        if "collector_token" in json.loads(config_path.read_text(encoding="utf-8")):
            raise CleanInstallError("La config temporal contiene collector_token")
        python_bin = create_venv_and_install(install_dir)
        _validate_result, _dry_run_result = run_cli_dry_install(install_dir, python_bin, config_path)
        summary_path, products_count = validate_summary(install_dir)
        validate_runtime_isolation(install_dir)
        validate_runtime_secrets(install_dir)
        source_summary_after = snapshot_path(source_summary)
        if source_summary_before != source_summary_after:
            raise CleanInstallError("La prueba limpia modifico samples/output del repo fuente")

        result = {
            "zip_path": str(zip_path),
            "zip_sha256": sha256(zip_path),
            "temp_install_dir": str(install_dir),
            "validate_status": "ok",
            "dry_run_status": "ok",
            "products_count": products_count,
            "output_summary_path": str(summary_path),
            "isolation_ok": True,
            "secrets_ok": True,
            "cleaned_temp": False,
        }
    except Exception:
        if not keep_temp:
            shutil.rmtree(install_dir, ignore_errors=True)
        raise

    if not keep_temp:
        shutil.rmtree(install_dir, ignore_errors=True)
        cleaned = True
    result["cleaned_temp"] = cleaned
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test clean install from AIVA Collector Windows ZIP")
    parser.add_argument("--zip", dest="zip_path", default=None)
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    try:
        zip_path = Path(args.zip_path) if args.zip_path else latest_zip()
        result = run_clean_install(zip_path, keep_temp=args.keep_temp)
    except CleanInstallError as exc:
        print(f"CLEAN INSTALL FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
