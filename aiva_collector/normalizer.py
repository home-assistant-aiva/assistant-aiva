from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

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
        return float(value) if math.isfinite(value) else None
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
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def cost_status(raw_value: Any, parsed: float | None) -> str:
    if raw_value is None or str(raw_value).strip() == "":
        return "missing"
    if parsed is None:
        return "invalid"
    if parsed < 0:
        return "negative"
    if parsed == 0:
        return "zero"
    return "valid"


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


def normalize_rows(
    raw_rows: list[dict[str, Any]], config: CollectorConfig
) -> NormalizedResult:
    mapping = config.column_mapping
    valid: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    date_format = str(config.raw.get("date_format", "%Y-%m-%d"))

    for index, raw in enumerate(raw_rows, start=1):

        def mapped(name: str) -> Any:
            source = mapping.get(name)
            if source:
                return raw.get(source)
            if name == "descuento":
                for key, value in raw.items():
                    if str(key).strip().casefold() in {"descuento", "discount"}:
                        return value
            return None

        producto_nombre = clean_string(mapped("producto_nombre"))
        cantidad_vendida = parse_number(mapped("cantidad_vendida"))
        precio_venta = parse_number(mapped("precio_venta"))
        costo_raw = mapped("costo_unitario")
        costo_unitario = parse_number(costo_raw)
        costo_estado = cost_status(costo_raw, costo_unitario)
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

        from .daily import decimal_number

        exact = {
            name: str(value) if value is not None else None
            for name in (
                "cantidad_vendida",
                "precio_venta",
                "costo_unitario",
                "stock_actual",
                "descuento",
            )
            for value in [decimal_number(mapped(name))]
        }
        if costo_estado not in {"valid", "zero"}:
            exact["costo_unitario"] = None
        raw_date = mapped("fecha")
        if isinstance(raw_date, str) and "T" in raw_date:
            try:
                raw_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                pass
        if isinstance(raw_date, datetime) and raw_date.tzinfo is not None:
            raw_date = raw_date.astimezone(
                ZoneInfo(
                    str(
                        config.raw.get(
                            "business_timezone", "America/Argentina/Buenos_Aires"
                        )
                    )
                )
            )
        valid.append(
            {
                "_daily_decimal": exact,
                "fecha": parse_date(raw_date, date_format),
                "producto_codigo": clean_string(mapped("producto_codigo")),
                "producto_nombre": producto_nombre,
                "categoria": clean_string(mapped("categoria")) or "Sin categoria",
                "cantidad_vendida": cantidad_vendida,
                "precio_venta": precio_venta,
                "costo_unitario": costo_unitario
                if costo_estado in {"valid", "zero"}
                else None,
                "costo_estado": costo_estado,
                "stock_actual": parse_number(mapped("stock_actual")),
            }
        )

    return NormalizedResult(rows=valid, discarded=discarded)
