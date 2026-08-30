from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PACKAGE_NAME = "aiva-collector-windows-manual"
DEFAULT_VERSION = "0.2.7rc2"
ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

REQUIRED_EMPTY_DIRS = [
    Path("samples/output"),
    Path("samples/processed"),
    Path("samples/error"),
    Path("logs"),
    Path("state"),
]

INCLUDE_PATHS = [
    Path("aiva_collector"),
    Path("windows"),
    Path("docs/aiva_collector_clean_install_test.md"),
    Path("docs/aiva_collector_column_mapping.md"),
    Path("docs/collector_discovery.md"),
    Path("docs/aiva_collector_first_client_data_request.md"),
    Path("docs/aiva_collector_mapping_test_cases.md"),
    Path("docs/aiva_collector_offline_queue.md"),
    Path("docs/aiva_collector_reliability.md"),
    Path("docs/aiva_collector_windows_manual.md"),
    Path("docs/aiva_collector_windows_package.md"),
    Path("docs/aiva_collector_windows_pilot_checklist.md"),
    Path("docs/aiva_collector_windows_pilot_results_template.md"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("configs/example_config.json"),
    Path("samples/input/ventas_demo.csv"),
    Path("samples/input/ventas_demo.xlsx"),
    Path("samples/output/.gitkeep"),
    Path("samples/processed/.gitkeep"),
    Path("samples/error/.gitkeep"),
    Path("logs/.gitkeep"),
    Path("state/.gitkeep"),
]

EXCLUDED_PATTERNS = [
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    "dist/",
    "build/",
    "*.egg-info/",
    ".env",
    "*.local.json",
    "config.local.json",
    "state/collector_state.json",
    "logs/*.log",
    "samples/output/last_summary.json",
    "samples/output/*.json",
    "samples/processed/*",
    "samples/error/*",
    "tests/",
]

TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    "",
}

SENSITIVE_REGEXES = [
    ("AIVA_INTERNAL_SECRET=", re.compile(r"AIVA_INTERNAL_SECRET\s*=")),
    ("TELEGRAM_BOT_TOKEN=", re.compile(r"TELEGRAM_BOT_TOKEN\s*=")),
    ("OPENAI_API_KEY=", re.compile(r"OPENAI_API_KEY\s*=")),
    ("Authorization: Bearer", re.compile(r"Authorization:\s*Bearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)),
    ("aiva_col_", re.compile(r"aiva_col_[A-Za-z0-9._-]{8,}")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9]{12,}")),
    ("config.local.json", re.compile(r"config\.local\.json")),
    (".env", re.compile(r"(^|[\\/])\.env($|[\\/])")),
    ("collector_token", re.compile(r"collector_token")),
]

SAFE_COLLECTOR_TOKEN_CONTEXTS = [
    "collector_token_env",
    '"collector_token" in data',
    '"collector_token" not in data',
    '"collector_token",',
    "Properties.Remove('collector_token')",
    "collector_token no debe guardarse",
    "No guardar `collector_token`",
    "No guarda `collector_token`",
    "no guarda `collector_token`",
    "sin `collector_token`",
    "collector_token como campo",
    "collector_token en config",
    'response["collector_token"]',
]


class PackageError(RuntimeError):
    pass


def read_version(root: Path = ROOT) -> str:
    pyproject = root / "pyproject.toml"
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        return str(version or DEFAULT_VERSION)
    except Exception:
        return DEFAULT_VERSION


def public_asset_version(version: str) -> str:
    if version in {"0.2.7rc1", "0.2.7rc2"}:
        return f"0.2.7-desktop-{version[-3:]}"
    if version == "0.2.6rc6":
        return "0.2.6-discovery-rc6"
    if version == "0.2.6rc3":
        return "0.2.6-silent-rc3"
    if version == "0.2.6rc2":
        return "0.2.6-discovery-rc2"
    if version == "0.2.6rc1":
        return "0.2.6-discovery-rc1"
    return version


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if any(part == "__pycache__" for part in path.parts):
        return True
    if parts & {".venv", ".pytest_cache", ".mypy_cache", "dist", "build", "tests"}:
        return True
    if path.name == ".env" or path.name == "config.local.json" or path.name.endswith(".local.json"):
        return True
    if path.name.endswith(".log"):
        return True
    if path.name == "collector_state.json":
        return True
    if path.suffix == ".pyc":
        return True
    if any(part.endswith(".egg-info") for part in path.parts):
        return True
    if path.match("samples/output/*.json"):
        return True
    if len(path.parts) >= 2 and path.parts[:2] in (("samples", "processed"), ("samples", "error")):
        return path.name != ".gitkeep"
    return False


def iter_included_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in INCLUDE_PATHS:
        source = root / relative
        if not source.exists():
            if relative == Path("samples/input/ventas_demo.xlsx"):
                continue
            raise PackageError(f"Archivo requerido no existe: {relative}")
        if source.is_dir():
            for file_path in sorted(source.rglob("*")):
                rel_file = file_path.relative_to(root)
                if file_path.is_file() and not should_skip(rel_file):
                    files.append(rel_file)
        elif source.is_file() and not should_skip(relative):
            files.append(relative)
    return sorted(set(files), key=lambda item: item.as_posix())


def copy_files(root: Path, staging: Path, files: Iterable[Path]) -> None:
    for relative in files:
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    for relative_dir in REQUIRED_EMPTY_DIRS:
        directory = staging / relative_dir
        directory.mkdir(parents=True, exist_ok=True)
        gitkeep = directory / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def line_is_allowed(pattern_name: str, relative: Path, line: str) -> bool:
    normalized = relative.as_posix()
    if pattern_name == "collector_token":
        if normalized == "aiva_collector/config_discovery.py" and "resolve_collector_token" in line:
            return True
        return any(context in line for context in SAFE_COLLECTOR_TOKEN_CONTEXTS)
    if pattern_name == "Authorization: Bearer":
        return normalized == "aiva_collector/client.py" and 'f"Bearer {token}"' in line
    if pattern_name == "config.local.json":
        if normalized == "aiva_collector/cli.py" and "WINDOWS_DEFAULT_CONFIG" in line:
            return True
        if normalized == "aiva_collector/config_discovery.py":
            return True
        return normalized.endswith(".md") or normalized.endswith(".bat") or normalized == "README.md"
    return False


def safety_scan(staging: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file() or not is_text_file(path):
            continue
        relative = path.relative_to(staging)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, regex in SENSITIVE_REGEXES:
                if regex.search(line) and not line_is_allowed(pattern_name, relative, line):
                    findings.append(
                        {
                            "file": relative.as_posix(),
                            "line": line_number,
                            "pattern": pattern_name,
                        }
                    )
    return findings


def zip_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_zip(staging: Path, zip_path: Path) -> int:
    files = sorted([path for path in staging.rglob("*") if path.is_file()], key=lambda item: item.relative_to(staging).as_posix())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(staging).as_posix())
    return len(files)


def build_package(root: Path = ROOT, dist_dir: Path = DIST_DIR) -> tuple[Path, Path, dict[str, object]]:
    root = root.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    version = read_version(root)
    asset_version = public_asset_version(version)
    zip_path = dist_dir / f"{PACKAGE_NAME}-v{asset_version}.zip"
    manifest_path = dist_dir / f"{PACKAGE_NAME}-v{asset_version}.manifest.json"

    with tempfile.TemporaryDirectory(prefix="aiva-collector-winpkg-") as tmp:
        staging = Path(tmp) / f"{PACKAGE_NAME}-v{asset_version}"
        staging.mkdir(parents=True)
        files = iter_included_files(root)
        copy_files(root, staging, files)
        findings = safety_scan(staging)
        if findings:
            zip_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            first = findings[0]
            raise PackageError(
                "Safety check fallo: "
                f"{first['file']}:{first['line']} patron={first['pattern']} "
                f"(findings={len(findings)})"
            )

        tmp_zip = dist_dir / f".{zip_path.name}.tmp"
        tmp_zip.unlink(missing_ok=True)
        files_count = create_zip(staging, tmp_zip)
        digest = zip_sha256(tmp_zip)
        tmp_zip.replace(zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        included_top_level = sorted({Path(name).parts[0] for name in archive.namelist() if name})

    manifest = {
        "package_name": PACKAGE_NAME,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files_count": files_count,
        "zip_path": str(zip_path),
        "sha256": digest,
        "excluded_patterns": EXCLUDED_PATTERNS,
        "included_top_level": included_top_level,
        "safety_checks_passed": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return zip_path, manifest_path, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AIVA Collector Windows manual ZIP")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--dist-dir", default=str(DIST_DIR))
    args = parser.parse_args(argv)

    try:
        zip_path, manifest_path, manifest = build_package(Path(args.root), Path(args.dist_dir))
    except PackageError as exc:
        print(str(exc))
        return 1

    print(f"ZIP: {zip_path}")
    print(f"Manifest: {manifest_path}")
    print(f"SHA256: {manifest['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
