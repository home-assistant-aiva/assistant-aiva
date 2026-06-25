from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .column_mapping import REQUIRED_FIELDS


@dataclass
class ValidationResult:
    is_valid: bool
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    invalid_samples: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "blocking_errors": self.blocking_errors,
            "warnings": self.warnings,
            "rows_total": self.rows_total,
            "rows_valid": self.rows_valid,
            "rows_invalid": self.rows_invalid,
            "invalid_samples": self.invalid_samples[:5],
        }


def validate_normalized_data(
    *,
    raw_rows: list[dict[str, Any]],
    mapping: dict[str, str],
    normalized_rows: list[dict[str, Any]],
    discarded_rows: list[dict[str, Any]],
) -> ValidationResult:
    blocking: list[str] = []
    warnings: list[str] = []
    missing = [field for field in REQUIRED_FIELDS if field not in mapping]
    if missing:
        blocking.append("Faltan columnas requeridas luego del mapeo: " + ", ".join(missing))
    if not raw_rows:
        blocking.append("El archivo no tiene filas de datos.")
    if raw_rows and _all_rows_empty(raw_rows):
        blocking.append("Todas las filas del archivo estan vacias.")

    invalid_samples = [
        {"row_number": item.get("row_number"), "reasons": list(item.get("reasons") or [])[:3]}
        for item in discarded_rows[:5]
    ]
    for row in normalized_rows:
        if not str(row.get("producto_nombre") or "").strip():
            invalid_samples.append({"row_number": None, "reasons": ["producto vacio"]})
        if row.get("cantidad_vendida") is None or float(row.get("cantidad_vendida") or 0) < 0:
            invalid_samples.append({"row_number": None, "reasons": ["cantidad invalida o negativa"]})
        if row.get("precio_venta") is None or float(row.get("precio_venta") or 0) < 0:
            invalid_samples.append({"row_number": None, "reasons": ["precio vacio o invalido"]})

    invalid_samples = invalid_samples[:5]
    rows_invalid = len(discarded_rows) + max(0, len(invalid_samples) - min(len(discarded_rows), 5))
    rows_valid = len(normalized_rows)
    if rows_valid == 0:
        blocking.append("El archivo no tiene filas validas para enviar.")

    if discarded_rows:
        warnings.append(f"Se descartaron {len(discarded_rows)} filas con datos incompletos o invalidos.")
    if any(not row.get("producto_codigo") for row in normalized_rows):
        warnings.append("Hay productos sin codigo.")
    if any(row.get("costo_unitario") is None for row in normalized_rows):
        warnings.append("Hay filas sin costo; el margen puede quedar incompleto.")
    if any(row.get("stock_actual") is None for row in normalized_rows):
        warnings.append("Hay filas sin stock.")
    if any((row.get("stock_actual") is not None and float(row["stock_actual"]) < 0) for row in normalized_rows):
        warnings.append("Hay filas con stock negativo.")
    if any(row.get("fecha") is None for row in normalized_rows):
        warnings.append("Hay filas sin fecha; se usara el periodo configurado o la fecha actual.")
    if _has_potential_duplicates(normalized_rows):
        warnings.append("Hay posibles productos duplicados dentro del archivo.")

    return ValidationResult(
        is_valid=not blocking,
        blocking_errors=blocking,
        warnings=_unique(warnings),
        rows_total=len(raw_rows),
        rows_valid=rows_valid,
        rows_invalid=max(len(discarded_rows), rows_invalid),
        invalid_samples=invalid_samples,
    )


def _all_rows_empty(raw_rows: list[dict[str, Any]]) -> bool:
    return all(not any(str(value or "").strip() for value in row.values()) for row in raw_rows)


def _has_potential_duplicates(rows: list[dict[str, Any]]) -> bool:
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (row.get("fecha"), row.get("producto_codigo"), row.get("producto_nombre"), row.get("cantidad_vendida"), row.get("precio_venta"))
        if key in seen:
            return True
        seen.add(key)
    return False


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
