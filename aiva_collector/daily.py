"""Exact daily observations. Completeness is a source declaration, never inferred."""

import hashlib
import json
import time
from decimal import Decimal, ROUND_HALF_EVEN
from zoneinfo import ZoneInfo


def decimal_number(value):
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace(" ", "")
    if "," in text and "." in text:
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        )
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
        return value if value.is_finite() else None
    except Exception:
        return None


def row_economics(row, config):
    """Return exact net line revenue and informational total discount, once."""
    numbers = row.get("_daily_decimal", {})
    def number(key):
        return decimal_number(numbers.get(key, row.get(key)))
    quantity, price = number("cantidad_vendida"), number("precio_venta")
    discount = number("descuento") or Decimal(0)
    semantics = config.raw.get("price_semantics", "final_net")
    kind = config.raw.get("discount_semantics")
    if semantics not in {"final_net", "gross_before_discount"}:
        raise ValueError("Elegí si el precio es bruto o neto en Configurar archivo.")
    if discount < 0:
        raise ValueError("El descuento no puede ser negativo.")
    amount = quantity * price
    if discount:
        if kind not in {"per_unit", "per_line", "percentage"}:
            raise ValueError("Descuento (discount) ambiguo: abrí Configurar archivo y elegí por unidad, por línea o porcentaje.")
        if kind == "percentage":
            if discount > 100 or (semantics == "final_net" and discount == 100):
                raise ValueError("Porcentaje inválido: un precio neto con 100% no permite reconstruir el descuento; usá el importe por línea.")
            discount = amount * discount / (100 if semantics == "gross_before_discount" else 100 - discount)
        elif kind == "per_unit":
            discount *= quantity
    if quantity == 0 and discount != 0:
        raise ValueError("Una línea sin unidades no puede tener descuento monetario.")
    net = amount - discount if semantics == "gross_before_discount" else amount
    if net < 0:
        raise ValueError("El descuento supera la venta bruta. Revisá precio y tipo de descuento.")
    return net, discount


def build_daily(rows, config, discarded):
    timezone = str(
        config.raw.get("business_timezone", "America/Argentina/Buenos_Aires")
    )
    ZoneInfo(timezone)
    expected_sha = config.raw.get("daily_complete_file_sha256")
    digest_matches = not expected_sha or expected_sha == config.raw.get("_active_file_sha256")
    declared = config.raw.get("daily_snapshot_complete") is True and discarded == 0 and digest_matches
    source_id = str(
        config.raw.get("daily_source_id")
        or (
            "excel_"
            + hashlib.sha256(
                str(config.raw.get("input_dir", "selected_excel_folder")).encode()
            ).hexdigest()[:32]
        )
    )
    grouped = {}
    for row in rows:
        key = (row["fecha"].isoformat(), row["producto_codigo"])
        item = grouped.setdefault(
            key,
            {
                "product_name": row["producto_nombre"],
                "category": row.get("categoria"),
                "quantity": Decimal(0),
                "net_revenue": Decimal(0),
                "discount": Decimal(0),
                "cogs": Decimal(0),
                "cost_known": True,
                "stocks": set(),
                "stock_known": True,
                "prices": set(),
                "costs": set(),
            },
        )
        numbers = row.get("_daily_decimal", {})

        def value(name):
            return decimal_number(numbers.get(name, row.get(name)))

        qty = value("cantidad_vendida")
        price = value("precio_venta")
        cost = value("costo_unitario")
        item["quantity"] += qty
        revenue, discount = row_economics(row, config)
        item["net_revenue"] += revenue
        item["discount"] += discount
        item["prices"].add(price)
        if cost is None:
            item["cost_known"] = False
        else:
            item["cogs"] += qty * cost
            item["costs"].add(cost)
        stock = value("stock_actual")
        if config.raw.get("source_profile") and row.get("fecha_stock") != row["fecha"]:
            stock = None
        if stock is not None and stock >= 0:
            item["stocks"].add(stock)
        else:
            item["stock_known"] = False
    metrics = []

    def text(value):
        return (
            str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))
            if value is not None
            else None
        )

    for (day, code), item in sorted(grouped.items()):
        qty = item["quantity"]
        revenue = item["net_revenue"]
        cost = item["cogs"] if item["cost_known"] else None
        if qty == 0 and len(item["costs"]) != 1:
            cost = None
        # Repeated different stock observations are not evidence of closing stock.
        stock = (
            next(iter(item["stocks"]))
            if item["stock_known"] and len(item["stocks"]) == 1
            else None
        )
        metrics.append(
            {
                "business_date": day,
                "product_code": code,
                "product_name": item["product_name"],
                "category": item["category"],
                "quantity": text(qty),
                "unit_sale_price": text(revenue / qty if qty else min(item["prices"])),
                "unit_cost": text(
                    cost / qty
                    if qty and cost is not None
                    else next(iter(item["costs"]))
                    if cost == 0
                    else None
                ),
                "discount_amount": text(item["discount"]),
                "net_revenue": text(revenue),
                "cogs": text(cost),
                "closing_stock": text(stock),
                "quality_flags": (["cost_missing"] if cost is None else [])
                + (["stock_unknown"] if stock is None else []),
            }
        )
    return {
        "source_id": source_id,
        "revision": time.time_ns(),
        "timezone": timezone,
        "semantics": "snapshot_replace",
        "price_semantics": "final_net_with_discounts" if any(m["discount_amount"] != "0.000000" for m in metrics) else "final_net",
        "scope": "whole_commerce",
        "completeness_declared": declared,
        "currency": config.raw.get("currency"),
        "coverage": [
            {"business_date": d, "status": "complete" if declared else "unknown"}
            for d in sorted({m["business_date"] for m in metrics})
        ],
        "metrics": metrics,
    }


def daily_idempotency(summary):
    snap = dict(summary["daily_snapshot"])
    snap.pop(
        "revision", None
    )  # Same observations remain the same ingestion across captures.
    body = {
        "commerce_id": summary["commerce_id"],
        "collector_id": summary["collector_id"],
        "source_schema_version": summary["source_schema_version"],
        "daily_snapshot": snap,
    }
    return hashlib.sha256(
        json.dumps(
            body, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
