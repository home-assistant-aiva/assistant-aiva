from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiva_collector.version import PUBLIC_VERSION, VERSION
from scripts.generate_windows_version_info import (
    COMPANY_NAME,
    COPYRIGHT,
    EXECUTABLE_METADATA,
    PRODUCT_NAME,
    numeric_version,
)


DEFAULT_APP_DIR = ROOT / "dist" / "aiva-collector"
DEFAULT_EVIDENCE_PATH = ROOT / "dist" / "windows-binary-inspection.json"
PE_SUFFIXES = {".exe", ".dll", ".pyd"}
UPX_SECTION_NAMES = {b"UPX", b"UPX0", b"UPX1", b"UPX2"}


class BinarySecurityError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_commit() -> str | None:
    value = os.getenv("AIVA_BUILD_COMMIT", "").strip().lower()
    if not value:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise BinarySecurityError("AIVA_BUILD_COMMIT no es un SHA Git completo")
    return value


def _walk_file_info(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_file_info(item)
    else:
        yield value
        for attribute in ("StringTable", "Var"):
            children = getattr(value, attribute, None)
            if children:
                yield from _walk_file_info(children)


def version_strings(pe: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _walk_file_info(getattr(pe, "FileInfo", [])):
        entries = getattr(item, "entries", None)
        if not isinstance(entries, dict):
            continue
        for raw_key, raw_value in entries.items():
            key = raw_key.decode("utf-8", errors="replace") if isinstance(raw_key, bytes) else str(raw_key)
            value = raw_value.decode("utf-8", errors="replace") if isinstance(raw_value, bytes) else str(raw_value)
            result[key] = value
    return result


def fixed_file_version(pe: Any) -> tuple[int, int, int, int] | None:
    fixed = getattr(pe, "VS_FIXEDFILEINFO", None)
    if not fixed:
        return None
    info = fixed[0]
    return (
        info.FileVersionMS >> 16,
        info.FileVersionMS & 0xFFFF,
        info.FileVersionLS >> 16,
        info.FileVersionLS & 0xFFFF,
    )


def inspect_pe(path: Path, pefile: Any, *, include_details: bool) -> dict[str, object]:
    try:
        pe = pefile.PE(str(path), fast_load=not include_details)
    except pefile.PEFormatError as exc:
        raise BinarySecurityError(f"PE invalido: {path}: {exc}") from exc
    section_names = [
        section.Name.rstrip(b"\0") for section in pe.sections
    ]
    upx_sections = [
        name.decode("ascii", errors="replace")
        for name in section_names
        if name.upper() in UPX_SECTION_NAMES or name.upper().startswith(b"UPX")
    ]
    result: dict[str, object] = {
        "path": path.as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "upx_sections": upx_sections,
    }
    if include_details:
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"],
            ]
        )
        imports = sorted(
            {
                entry.dll.decode("ascii", errors="replace")
                for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
            }
        )
        security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"]
        ]
        result.update(
            {
                "format": "PE32+" if pe.OPTIONAL_HEADER.Magic == 0x20B else "PE32",
                "machine": f"0x{pe.FILE_HEADER.Machine:04x}",
                "sections": [
                    {
                        "name": name.decode("ascii", errors="replace"),
                        "raw_bytes": section.SizeOfRawData,
                    }
                    for name, section in zip(section_names, pe.sections)
                ],
                "imports": imports,
                "version_strings": version_strings(pe),
                "fixed_file_version": fixed_file_version(pe),
                "embedded_signature": security.Size > 0,
            }
        )
    pe.close()
    return result


def expected_metadata(filename: str) -> dict[str, str]:
    metadata = EXECUTABLE_METADATA[filename]
    return {
        "CompanyName": COMPANY_NAME,
        "ProductName": PRODUCT_NAME,
        "FileDescription": metadata["description"],
        "FileVersion": ".".join(str(part) for part in numeric_version()),
        "ProductVersion": PUBLIC_VERSION,
        "OriginalFilename": filename,
        "InternalName": metadata["internal_name"],
        "LegalCopyright": COPYRIGHT,
    }


def verify(
    app_dir: Path = DEFAULT_APP_DIR,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    extra_paths: Iterable[Path] = (),
) -> dict[str, object]:
    try:
        import pefile
    except ImportError as exc:
        raise BinarySecurityError("Falta pefile para inspeccionar los binarios Windows") from exc

    app_dir = app_dir.resolve()
    resolved_extra_paths = [path.resolve() for path in extra_paths]
    missing_extra = [str(path) for path in resolved_extra_paths if not path.is_file()]
    if missing_extra:
        raise BinarySecurityError("Faltan PE adicionales: " + ", ".join(missing_extra))
    invalid_extra = [str(path) for path in resolved_extra_paths if path.suffix.lower() not in PE_SUFFIXES]
    if invalid_extra:
        raise BinarySecurityError("Artefactos adicionales no son PE soportados: " + ", ".join(invalid_extra))
    pe_paths = sorted(
        set(
            path for path in app_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in PE_SUFFIXES
        )
        | set(resolved_extra_paths),
        key=lambda path: path.as_posix(),
    )
    if not pe_paths:
        raise BinarySecurityError(f"No hay archivos PE en {app_dir}")

    main_paths = {app_dir / filename for filename in EXECUTABLE_METADATA}
    detail_paths = main_paths | set(resolved_extra_paths)
    missing = sorted(str(path) for path in main_paths if not path.exists())
    if missing:
        raise BinarySecurityError("Faltan ejecutables: " + ", ".join(missing))

    main_binaries = []
    pe_files = []
    additional_artifacts = []
    upx_findings = []
    for path in pe_paths:
        is_extra = path in resolved_extra_paths
        inspected = inspect_pe(path, pefile, include_details=path in detail_paths)
        display_path = (
            path.relative_to(app_dir).as_posix()
            if path.is_relative_to(app_dir)
            else path.name
        )
        inspected["path"] = display_path
        pe_files.append(inspected)
        if inspected["upx_sections"]:
            upx_findings.append(
                {
                    "path": display_path,
                    "sections": inspected["upx_sections"],
                }
            )
        if path in main_paths:
            strings = inspected["version_strings"]
            expected = expected_metadata(path.name)
            mismatches = {
                key: {"expected": value, "actual": strings.get(key)}
                for key, value in expected.items()
                if strings.get(key) != value
            }
            if inspected["fixed_file_version"] != numeric_version():
                mismatches["fixed_file_version"] = {
                    "expected": numeric_version(),
                    "actual": inspected["fixed_file_version"],
                }
            inspected["metadata_valid"] = not mismatches
            inspected["metadata_mismatches"] = mismatches
            main_binaries.append(inspected)
        if is_extra:
            additional_artifacts.append(inspected)

    evidence = {
        "build_commit": build_commit(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "public_version": PUBLIC_VERSION,
        "pyinstaller_mode": "onedir",
        "pe_files_scanned": len(pe_paths),
        "upx_enabled": False,
        "upx_findings": upx_findings,
        "pe_files": sorted(pe_files, key=lambda item: str(item["path"])),
        "binaries": sorted(main_binaries, key=lambda item: str(item["path"])),
        "additional_artifacts": sorted(additional_artifacts, key=lambda item: str(item["path"])),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    invalid_metadata = [
        item["path"] for item in main_binaries if not item["metadata_valid"]
    ]
    if upx_findings:
        raise BinarySecurityError(f"Se detectaron secciones UPX: {upx_findings}")
    if invalid_metadata:
        raise BinarySecurityError(f"Metadata PE invalida: {invalid_metadata}")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Windows PE metadata and reject UPX")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument(
        "--extra-pe",
        action="append",
        default=[],
        type=Path,
        help="Additional PE artifact to inspect (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        evidence = verify(args.app_dir, args.evidence, args.extra_pe)
    except BinarySecurityError as exc:
        print(f"BINARY SECURITY FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "BINARY SECURITY OK: "
        f"{evidence['pe_files_scanned']} PE files, no UPX sections, metadata valid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
