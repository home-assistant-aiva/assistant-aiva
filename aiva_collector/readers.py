from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .config import CollectorConfig
from .errors import ValidationError


SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


def discover_input_files(config: CollectorConfig) -> list[Path]:
    input_dir = config.path("input_dir")
    if not input_dir.exists():
        raise ValidationError(f"No existe input_dir: {input_dir}")
    files = [
        path
        for path in sorted(input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return files


def read_file(path: Path, config: CollectorConfig) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return read_csv(path, config)
    if path.suffix.lower() == ".xlsx":
        return read_xlsx(path)
    raise ValidationError(f"Tipo de archivo no soportado: {path.name}")


def read_csv(path: Path, config: CollectorConfig) -> list[dict[str, Any]]:
    with path.open("r", encoding=str(config.raw.get("encoding", "utf-8")), newline="") as fh:
        reader = csv.DictReader(fh, delimiter=str(config.raw.get("delimiter", ",")))
        return [dict(row) for row in reader]


def read_xlsx(path: Path) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValidationError("openpyxl no está disponible para leer XLSX") from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    result: list[dict[str, Any]] = []
    for row in rows[1:]:
        result.append({headers[i]: row[i] if i < len(row) else None for i in range(len(headers))})
    workbook.close()
    return result


def detect_columns(files: list[Path], config: CollectorConfig) -> set[str]:
    columns: set[str] = set()
    for path in files:
        rows = read_file(path, config)
        if rows:
            columns.update(rows[0].keys())
        elif path.suffix.lower() == ".csv":
            with path.open("r", encoding=str(config.raw.get("encoding", "utf-8")), newline="") as fh:
                reader = csv.DictReader(fh, delimiter=str(config.raw.get("delimiter", ",")))
                columns.update(reader.fieldnames or [])
    return columns
