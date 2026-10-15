"""Bounded readers. No connector computes commercial metrics or writes source data."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


from ..errors import CollectorError


class AccessError(CollectorError):
    def __init__(self, code, message, *, retry_after=None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    def __post_init__(self):
        if self.end < self.start or (self.end - self.start).days > 3659:
            raise AccessError("period_invalid", "Revisá el rango: hasta 3660 días, desde anterior a hasta.")


@dataclass
class Reading:
    rows: list[dict[str, Any]]
    outside: int = 0
    complete: bool = False
    empty_confirmed: bool = False


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise AccessError("identifier_invalid", "Usá nombres simples de tabla y columnas; no se admite SQL libre.")
    return value


def bounded_rows(rows, limit):
    result = []
    total_bytes = 0
    for row in rows:
        if len(row) > 64:
            raise AccessError("column_limit", "Seleccioná hasta 64 campos necesarios por lectura.")
        for value in dict(row).values():
            if isinstance(value, (dict, list, bytes)) or len(str(value)) > 4096:
                raise AccessError("value_limit", "Hay campos no tabulares o demasiado extensos. Revisá el perfil del proveedor.")
            total_bytes += len(str(value).encode("utf-8"))
        if total_bytes > 50000000:
            raise AccessError("memory_limit", "La lectura supera el volumen permitido; reducí el período.")
        result.append(dict(row))
        if len(result) > limit:
            raise AccessError("row_limit", "La lectura supera el límite de filas; reducí el período o pedí una exportación.")
    return result


def safe_error(exc):
    if isinstance(exc, AccessError):
        return {"code": exc.code, "message": str(exc), "retry_after": exc.retry_after}
    return {"code": "access_failed", "message": "No se pudo leer la fuente. Revisá acceso, estructura y permisos.", "retry_after": None}


class Connector:
    def __init__(self, profile, secrets=None):
        self.profile = profile
        self.secrets = secrets or {}
        self.max_rows = min(max(int(profile.get("max_rows", 50000)), 1), 200000)
        self.timeout = min(max(int(profile.get("timeout_seconds", 20)), 1), 120)

    def availability(self):
        return {"state": "configuration_incomplete", "message": "Probá el acceso y confirmá el mapeo."}

    def test(self, window):
        sample = self.read(window, sample=True)
        return {"state": "access_tested", "fields": sorted({k for row in sample.rows for k in row}),
                "sample": sample.rows[:8], "count": len(sample.rows),
                "message": "Acceso correcto; revisá los campos." if sample.rows else "Acceso correcto; no se encontraron datos en el período."}

    def read(self, window, *, sample=False):
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def business_date(value, timezone_name):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ..normalizer import parse_date
    if isinstance(value, str) and 'T' in value:
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            pass
    if isinstance(value, datetime) and value.tzinfo is not None:
        value = value.astimezone(ZoneInfo(timezone_name))
    return parse_date(value)
