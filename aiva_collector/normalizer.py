from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .config import CollectorConfig


@dataclass
class NormalizedResult:
    rows: list[dict[str, Any]]
    discarded: list[dict[str, Any]]


def clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: Any, date_format: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in (date_format, "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_rows(raw_rows: list[dict[str, Any]], config: CollectorConfig) -> NormalizedResult:
    mapping = config.column_mapping
    valid: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    date_format = str(config.raw.get("date_format", "%Y-%m-%d"))

    for index, raw in enumerate(raw_rows, start=1):
        def mapped(name: str) -> Any:
            source = mapping.get(name)
            return raw.get(source) if source else None

        producto_nombre = clean_string(mapped("producto_nombre"))
        cantidad_vendida = parse_number(mapped("cantidad_vendida"))
        precio_venta = parse_number(mapped("precio_venta"))
        reasons = []
        if not producto_nombre:
            reasons.append("producto_nombre requerido")
        if cantidad_vendida is None:
            reasons.append("cantidad_vendida requerida")
        elif cantidad_vendida < 0:
            reasons.append("cantidad_vendida negativa")
        if precio_venta is None:
            reasons.append("precio_venta requerido")
        elif precio_venta < 0:
            reasons.append("precio_venta negativo")
        if reasons:
            discarded.append({"row_number": index, "reasons": reasons})
            continue

        valid.append(
            {
                "fecha": parse_date(mapped("fecha"), date_format),
                "producto_codigo": clean_string(mapped("producto_codigo")),
                "producto_nombre": producto_nombre,
                "categoria": clean_string(mapped("categoria")) or "Sin categoria",
                "cantidad_vendida": cantidad_vendida,
                "precio_venta": precio_venta,
                "costo_unitario": parse_number(mapped("costo_unitario")),
                "stock_actual": parse_number(mapped("stock_actual")),
            }
        )

    return NormalizedResult(rows=valid, discarded=discarded)
