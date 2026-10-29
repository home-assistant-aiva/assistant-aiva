"""Independent, dated inventory observations from a bounded file export."""

import hashlib
import json
from pathlib import Path

from .column_mapping import normalize_header
from .config import CollectorConfig
from .connectors.base import AccessError, bounded_rows
from .daily import stable_product_code
from .file_fingerprint import compute_file_sha256
from .normalizer import column_conventions, parse_date
from .numeric_format import CONVENTION_UNKNOWN, EMPTY_PLACEHOLDERS, parse_decimal_with
from .readers import read_file


def _date(row, mapping, field, fallback=None):
    source = mapping.get(field) or mapping.get(fallback or "")
    raw = row.get(source) if source else None
    if raw is None or str(raw).strip() == "":
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise AccessError("inventory_date_invalid", "Una fecha de inventario no se pudo leer. Revisá el mapeo y la exportación.")
    return parsed.isoformat()


def build_inventory(config, setup, path: Path, *, raw=None, file_hash=None, revision=1):
    """Group identical repeated values; contradicting assertions stay reviewable."""
    profile, mapping = setup["profile"], setup["mapping"]
    if not any(k in mapping for k in ("stock_actual", "costo_unitario", "precio_actual")):
        return None
    file_hash = file_hash or compute_file_sha256(path)
    reader = CollectorConfig({**profile.get("reader", {}), "column_mapping":mapping,
        "max_input_rows":min(int(profile.get("max_rows", 50000)), 50000)}, config.config_path)
    raw = raw if raw is not None else bounded_rows(read_file(path, reader), min(int(profile.get("max_rows", 50000)), 50000))
    if compute_file_sha256(path) != file_hash:
        raise AccessError("source_changed", "La exportación cambió durante la lectura; se reintentará.")
    if not raw:
        return None
    if profile.get("headers") and sorted(raw[0]) != profile["headers"]:
        raise AccessError("structure_changed", "Los campos de inventario cambiaron. Revisá el mapeo.")
    conventions, _ = column_conventions(raw, mapping, reader)
    confirmation = profile.get("inventory_confirmation") or {}
    confirmed = (confirmation.get("source_id") == setup["source_id"] and
                 confirmation.get("file_sha256") == file_hash and
                 parse_date(confirmation.get("observed_on")) is not None)
    asserted_date = confirmation.get("observed_on") if confirmed else None
    grouped = {}
    for row in raw:
        name = str(row.get(mapping.get("producto_nombre", "")) or "").strip()
        if not name or normalize_header(name) in {"total", "totales", "total general"}:
            continue
        identity = {"producto_codigo":row.get(mapping.get("producto_codigo", "")),
                    "producto_nombre":name,"categoria":row.get(mapping.get("categoria", ""))}
        code = stable_product_code(identity)
        category = str(identity["categoria"] or "Sin categoria")
        for kind, field, date_field, fallback in (
            ("stock", "stock_actual", "fecha_stock", None),
            ("current_cost", "costo_unitario", "fecha_costo", "fecha_valores_actuales"),
            ("current_price", "precio_actual", "fecha_precio", "fecha_valores_actuales"),
        ):
            if field not in mapping or (kind == "current_cost" and profile.get("cost_basis") != "current"):
                continue
            raw_value = row.get(mapping[field])
            if raw_value is None or str(raw_value).strip().casefold() in EMPTY_PLACEHOLDERS | {""}:
                continue
            value = parse_decimal_with(raw_value, conventions.get(field, CONVENTION_UNKNOWN))
            if value is None or value < 0:
                raise AccessError("inventory_value_invalid", "Hay stock, costo o precio actual ilegible o negativo. Revisá la exportación.")
            observed = _date(row, mapping, date_field, fallback)
            provenance = "mapped_column" if observed else "operator_confirmed" if asserted_date else "unknown"
            observed = observed or asserted_date
            key = (code, kind, observed)
            item = grouped.setdefault(key, {"product_code":code,"product_name":name,"category":category,
                "kind":kind,"observed_on":observed,"date_provenance":provenance,
                "provenance":"source_export","quality":"verified" if observed else "undated",
                "value":str(value)})
            if item["value"] != str(value) or item["product_name"] != name or item["category"] != category:
                item["value"] = None
                item["quality"] = "conflict"
    observations = sorted(grouped.values(), key=lambda item:(item["product_code"],item["kind"],item["observed_on"] or ""))
    if not observations:
        return None
    if len(observations) > 50000:
        raise AccessError("inventory_limit", "La foto supera 50.000 observaciones; dividí por productos sin repetirlos.")
    canonical = json.dumps(observations,sort_keys=True,separators=(",", ":"),ensure_ascii=True)
    return {"schema_version":"1.0.0","commerce_id":config.commerce_id,
            "collector_id":config.collector_id,"source_id":setup["source_id"],
            "content_sha256":hashlib.sha256(canonical.encode()).hexdigest(),
            "revision":revision,"scope":"partial","observations":observations}
