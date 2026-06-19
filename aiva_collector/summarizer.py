from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from .config import CollectorConfig


def _money(value: float | None) -> float:
    return round(float(value or 0), 2)


def _product_key(row: dict[str, Any]) -> tuple[str, str, str]:
    code = row.get("producto_codigo")
    if code:
        return ("code", str(code), "")
    return ("name", str(row["producto_nombre"]), str(row.get("categoria") or "Sin categoria"))


def build_summary(
    rows: list[dict[str, Any]],
    config: CollectorConfig,
    files_processed: int,
    rows_read: int,
    rows_discarded: int,
) -> dict[str, Any]:
    dates = [row["fecha"] for row in rows if row.get("fecha")]
    fecha_inicio = min(dates).isoformat() if dates else date.today().isoformat()
    fecha_fin = max(dates).isoformat() if dates else date.today().isoformat()
    period_days = max(1, (date.fromisoformat(fecha_fin) - date.fromisoformat(fecha_inicio)).days + 1)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _product_key(row)
        item = grouped.setdefault(
            key,
            {
                "producto_codigo": row.get("producto_codigo"),
                "producto_nombre": row["producto_nombre"],
                "categoria": row.get("categoria") or "Sin categoria",
                "cantidad_vendida": 0.0,
                "facturacion_total": 0.0,
                "costo_total_estimado": 0.0,
                "cantidad_con_costo": 0.0,
                "stock_actual": None,
            },
        )
        qty = float(row["cantidad_vendida"])
        price = float(row["precio_venta"])
        cost = row.get("costo_unitario")
        item["cantidad_vendida"] += qty
        item["facturacion_total"] += qty * price
        if cost is not None:
            item["costo_total_estimado"] += qty * float(cost)
            item["cantidad_con_costo"] += qty
        if row.get("stock_actual") is not None:
            item["stock_actual"] = row["stock_actual"]

    productos: list[dict[str, Any]] = []
    max_products = int(config.raw.get("max_products_per_summary", 1000))
    for item in grouped.values():
        qty = item["cantidad_vendida"]
        facturacion = item["facturacion_total"]
        costo_total = item["costo_total_estimado"]
        margen = facturacion - costo_total if item["cantidad_con_costo"] > 0 else 0
        productos.append(
            {
                "producto_codigo": item["producto_codigo"],
                "producto_nombre": item["producto_nombre"],
                "categoria": item["categoria"],
                "cantidad_vendida": _money(qty),
                "precio_venta_promedio": _money(facturacion / qty if qty else 0),
                "facturacion_total": _money(facturacion),
                "costo_unitario_promedio": _money(costo_total / item["cantidad_con_costo"] if item["cantidad_con_costo"] else 0),
                "costo_total_estimado": _money(costo_total),
                "margen_bruto_estimado": _money(margen),
                "margen_porcentaje_estimado": _money((margen / facturacion * 100) if facturacion else 0),
                "stock_actual": _money(item["stock_actual"] or 0),
                "dias_sin_ventas": 30 if qty <= 0 and (item["stock_actual"] or 0) > 0 else 0,
                "venta_promedio_diaria": _money(qty / period_days),
            }
        )

    productos.sort(key=lambda p: p["facturacion_total"], reverse=True)
    productos = productos[:max_products]
    total_facturacion = sum(p["facturacion_total"] for p in productos)
    total_costo = sum(p["costo_total_estimado"] for p in productos)
    total_margen = total_facturacion - total_costo
    productos_con_costo = sum(1 for p in productos if p["costo_total_estimado"] > 0)

    return {
        "commerce_id": config.commerce_id,
        "collector_id": config.collector_id,
        "periodo": str(config.raw.get("periodo", "weekly")),
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "productos_resumidos": productos,
        "resumen_financiero": {
            "facturacion_total": _money(total_facturacion),
            "costo_total_estimado": _money(total_costo),
            "margen_bruto_estimado": _money(total_margen),
            "margen_porcentaje_estimado": _money((total_margen / total_facturacion * 100) if total_facturacion else 0),
            "productos_con_costo": productos_con_costo,
            "productos_sin_costo": len(productos) - productos_con_costo,
        },
        "metadata": {
            "sistema_origen": "excel_folder",
            "archivos_procesados": files_processed,
            "filas_leidas": rows_read,
            "filas_validas": len(rows),
            "filas_descartadas": rows_discarded,
        },
        "collector_version": config.collector_version,
    }


def stable_summary_hash(summary: dict[str, Any]) -> str:
    payload = json.dumps(summary.get("productos_resumidos", []), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def idempotency_key(summary: dict[str, Any]) -> str:
    base = "|".join(
        [
            str(summary["commerce_id"]),
            str(summary["collector_id"]),
            str(summary["fecha_inicio"]),
            str(summary["fecha_fin"]),
            stable_summary_hash(summary),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
