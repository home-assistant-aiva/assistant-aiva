"""Local source setup. Preview never contacts the backend or mutates source files."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import CollectorConfig, collector_data_dir
from .errors import ConfigError, ValidationError
from .file_fingerprint import compute_file_sha256
from .numeric_format import (
    CONVENTION_COMMA,
    CONVENTION_DOT,
    CONVENTION_LABELS,
    CONVENTION_UNKNOWN,
    EMPTY_PLACEHOLDERS,
    canonical_decimal,
    clean_numeric_text,
    format_ar,
    normalize_convention,
    numeric_problem,
    parse_decimal_with,
)

FIELDS = {
    "fecha": "Fecha de venta", "producto_nombre": "Producto",
    "producto_codigo": "Código (opcional)", "cantidad_vendida": "Cantidad",
    "precio_venta": "Precio unitario", "descuento": "Descuento",
    "costo_unitario": "Costo unitario", "stock_actual": "Stock",
    "fecha_stock": "Fecha del stock", "categoria": "Categoría",
}
# El codigo es opcional: un kiosco que exporta sin codigo de barras es lo
# normal, y se deriva uno estable del nombre y la categoria.
REQUIRED = {"fecha", "producto_nombre", "cantidad_vendida", "precio_venta"}

NUMBER_FORMATS = {
    "Automático: AIVA lo detecta en cada columna": "auto",
    "1.234,56 — punto separa miles, coma decimales": CONVENTION_COMMA,
    "1,234.56 — coma separa miles, punto decimales": CONVENTION_DOT,
}

TIMEZONES = (
    "America/Argentina/Buenos_Aires",
    "America/Argentina/Cordoba",
    "America/Argentina/Salta",
    "America/Argentina/Jujuy",
    "America/Argentina/Tucuman",
    "America/Argentina/Catamarca",
    "America/Argentina/La_Rioja",
    "America/Argentina/San_Juan",
    "America/Argentina/Mendoza",
    "America/Argentina/San_Luis",
    "America/Argentina/Rio_Gallegos",
    "America/Argentina/Ushuaia",
    "America/Montevideo",
    "America/Asuncion",
    "America/Santiago",
)

TABLE_FIELDS = ("fecha", "producto_nombre", "producto_codigo", "cantidad_vendida", "precio_venta", "descuento", "costo_unitario", "stock_actual")
NUMERIC_TABLE_FIELDS = {"cantidad_vendida", "precio_venta", "descuento", "costo_unitario", "stock_actual"}
PLACEHOLDER_FIELDS = {"descuento", "costo_unitario", "stock_actual"}


def context_key(config, folder=None):
    context = [config.backend_url, config.commerce_id, config.collector_id,
               str(Path(folder or config.path("input_dir")).resolve())]
    return hashlib.sha256(json.dumps(context).encode()).hexdigest()


def validate_profile(config, headers=None):
    profile = config.raw.get("source_profile") or {}
    if profile.get("context") != context_key(config):
        raise ConfigError("La fuente pertenece a otra vinculación. Abrí Configurar archivo para este comercio.")
    if headers is not None and sorted(headers) != profile.get("headers"):
        raise ValidationError("Las columnas no coinciden con la fuente configurada. Revisá Configurar archivo.")


def inspect_source(path, *, sheet="", header_row=None):
    from .config_discovery import resolve_runtime_config
    from .readers import read_file
    path = Path(path).resolve(strict=True)
    config = resolve_runtime_config().config
    raw = {**config.raw, "xlsx_sheet": sheet, "xlsx_header_row": header_row, "column_mapping": {}}
    rows = read_file(path, CollectorConfig(raw, config.config_path))
    if not rows:
        raise ValidationError("El archivo está vacío o sólo tiene encabezados. Elegí una exportación con ventas.")
    return list(rows[0]), rows


def suggest_mapping(headers, rows):
    """Sugerencia inicial para los desplegables: nombres y valores de columnas."""

    from .column_mapping import detect_column_mapping
    return detect_column_mapping(headers, rows, fill_from_values=True)


def _check_mapping(mapping):
    mapping = {key: value for key, value in mapping.items() if value}
    missing = [FIELDS[key] for key in FIELDS if key in REQUIRED and key not in mapping]
    if missing:
        raise ValidationError("Falta elegir la columna de: " + ", ".join(missing) + ".")
    used: dict[str, list[str]] = {}
    for key, column in mapping.items():
        used.setdefault(column, []).append(FIELDS.get(key, key))
    repeated = {column: names for column, names in used.items() if len(names) > 1}
    if repeated:
        column, names = next(iter(repeated.items()))
        raise ValidationError(f"La columna '{column}' está elegida para {' y '.join(names)}. Cada columna puede usarse para un solo dato.")
    return mapping


def _conventions_for(rows, mapping, config, number_format):
    from .normalizer import column_conventions
    forced = normalize_convention(number_format)
    probe = {**config.raw, "column_mapping": mapping, "decimal_conventions": {}}
    probe["decimal_separator"] = forced or "auto"
    return column_conventions(rows, mapping, CollectorConfig(probe, config.config_path))


def interpret_sample(path, mapping, *, number_format="auto", sheet="", header_row=None, limit=8, discount=None):
    """Tabla para la pantalla: lo que dice el archivo y como lo lee AIVA.

    Nunca falla por una fila mala: la muestra con la marca para que el
    comercio vea exactamente donde esta el problema.
    """

    from .config_discovery import resolve_runtime_config
    from .normalizer import is_total_row, parse_date, source_header_for
    from .readers import read_file
    config = resolve_runtime_config().config
    path = Path(path).resolve(strict=True)
    mapping = {key: value for key, value in mapping.items() if value}
    raw = {**config.raw, "column_mapping": mapping, "xlsx_sheet": sheet, "xlsx_header_row": header_row}
    candidate = CollectorConfig(raw, config.config_path)
    rows = read_file(path, candidate)
    row_numbers = getattr(rows, "row_numbers", None) or list(range(2, len(rows) + 2))
    headers = list(rows[0]) if rows else []
    conventions, ambiguous = _conventions_for(rows, mapping, candidate, number_format)
    shown_fields = [key for key in TABLE_FIELDS if source_header_for(key, mapping, headers)]

    table_rows = []
    problem_rows = 0
    total_rows = 0
    for index, row in enumerate(rows):
        if is_total_row(row, mapping):
            total_rows += 1
            continue
        cells = []
        problem = False
        for key in shown_fields:
            source = source_header_for(key, mapping, headers)
            value = row.get(source)
            text = "" if value is None else str(value).strip()
            if key == "fecha":
                parsed = parse_date(value)
                if parsed is None:
                    problem = True
                    cells.append(f"{text or '(vacía)'} → ⚠ no es fecha")
                else:
                    shown = parsed.strftime("%d/%m/%Y")
                    cells.append(shown if shown == text else f"{text} → {shown}")
            elif key in NUMERIC_TABLE_FIELDS:
                if key in PLACEHOLDER_FIELDS and text.casefold() in EMPTY_PLACEHOLDERS:
                    cells.append(text)  # "-" = sin dato, igual que al sincronizar
                    continue
                if not text:
                    if key in {"cantidad_vendida", "precio_venta"}:
                        problem = True
                        cells.append("⚠ vacío")
                    else:
                        cells.append("")
                    continue
                number = parse_decimal_with(
                    value, conventions.get(key, CONVENTION_UNKNOWN),
                    allow_percent=key == "descuento" and discount == "percentage",
                )
                if number is None:
                    problem = True
                    cells.append(f"{text} → ⚠ {numeric_problem(value)}")
                else:
                    shown = format_ar(number)
                    cells.append(shown if shown == text else f"{text} → {shown}")
            else:
                if key == "producto_nombre" and not text:
                    problem = True
                    cells.append("⚠ vacío")
                else:
                    cells.append(text[:40])
        if problem:
            problem_rows += 1
        if len(table_rows) < limit or (problem and problem_rows <= 3):
            table_rows.append({"row": row_numbers[index] if index < len(row_numbers) else index + 2, "cells": cells, "problem": problem})

    return {
        "fields": shown_fields,
        "columns": [FIELDS[key].replace(" (opcional)", "") for key in shown_fields],
        "rows": table_rows,
        "total_rows": len(rows) - total_rows,
        "skipped_total_rows": total_rows,
        "numbers": number_report(rows, mapping, headers, conventions, ambiguous),
        "warnings": value_warnings(rows, mapping, headers, conventions),
    }


def number_report(rows, mapping, headers, conventions, ambiguous):
    """Una linea por campo numerico: formato usado y un ejemplo real."""

    from .normalizer import source_header_for
    report = []
    for key in ("precio_venta", "costo_unitario", "descuento", "cantidad_vendida", "stock_actual"):
        source = source_header_for(key, mapping, headers)
        if not source:
            continue
        convention = conventions.get(key, CONVENTION_UNKNOWN)
        example = None
        for row in rows:
            value = row.get(source)
            text = clean_numeric_text(value) if isinstance(value, str) else ""
            if text and ("." in text or "," in text):
                number = parse_decimal_with(value, convention)
                if number is not None:
                    example = f"'{str(value).strip()}' se lee como {format_ar(number)}"
                    break
        report.append({
            "field": key,
            "label": FIELDS[key].replace(" (opcional)", ""),
            "column": source,
            "convention": convention,
            "convention_label": CONVENTION_LABELS.get(convention, convention),
            "ambiguous": key in ambiguous,
            "example": example,
        })
    return report


def value_warnings(rows, mapping, headers, conventions):
    """Controles que solo se pueden hacer mirando los numeros."""

    from .normalizer import source_header_for
    warnings: list[str] = []
    qty_source = mapping.get("cantidad_vendida")
    price_source = mapping.get("precio_venta")
    if not rows or not qty_source or not price_source:
        return warnings

    def number(row, source, key=None):
        return parse_decimal_with(row.get(source), conventions.get(key, CONVENTION_UNKNOWN) if key else CONVENTION_UNKNOWN)

    sample = rows[:300]
    pairs = []
    for row in sample:
        qty, price = number(row, qty_source, "cantidad_vendida"), number(row, price_source, "precio_venta")
        if qty is not None and price is not None:
            pairs.append((row, qty, price))
    informative = [(row, qty, price) for row, qty, price in pairs if qty not in (Decimal(0), Decimal(1))]

    mapped_sources = set(mapping.values()) | {source_header_for("descuento", mapping, headers)}
    others = [header for header in headers if header not in mapped_sources]
    if len(informative) >= 3:
        def matches(a, b):
            return abs(a - b) <= max(Decimal("0.02"), abs(b) * Decimal("0.005"))
        for header in others:
            from .numeric_format import analyze_column
            convention = analyze_column(row.get(header) for row in sample).convention
            values = [(parse_decimal_with(row.get(header), convention), qty, price) for row, qty, price in informative]
            values = [(v, qty, price) for v, qty, price in values if v is not None]
            if len(values) < 3:
                continue
            as_total = sum(1 for v, qty, price in values if matches(v, qty * price))
            as_unit = sum(1 for v, qty, price in values if matches(price, qty * v))
            if as_unit >= 0.8 * len(values):
                warnings.append(
                    f"La columna elegida como precio ('{price_source}') parece ser el total de la línea: "
                    f"coincide con cantidad × '{header}'. Elegí '{header}' como precio unitario."
                )
                break
            if as_total >= 0.8 * len(values):
                warnings.append(
                    f"Control superado: '{header}' coincide con cantidad × precio en {as_total} de {len(values)} filas. "
                    "Los importes se están leyendo bien."
                )
                break

    qtys = sorted(qty for _row, qty, _price in pairs)
    prices = sorted(price for _row, _qty, price in pairs)
    if qtys and prices:
        median_qty, median_price = qtys[len(qtys) // 2], prices[len(prices) // 2]
        if median_qty >= 50 and median_price > 0 and median_qty > 10 * median_price:
            warnings.append(
                f"¿Cantidad y precio están invertidos? La cantidad típica ({format_ar(median_qty)}) es mucho mayor "
                f"que el precio típico ({format_ar(median_price)})."
            )

    fecha_source = mapping.get("fecha")
    if fecha_source:
        import re
        swapped = 0
        for row in sample:
            text = str(row.get(fecha_source) or "").strip()
            match = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}", text)
            if match and int(match.group(1)) <= 12 < int(match.group(2)):
                swapped += 1
        if swapped:
            warnings.append(
                f"{swapped} fecha(s) tienen el mes en segundo lugar mayor a 12 (ej. 09/25/2026): parece formato de EE.UU. "
                "AIVA lee día/mes/año; configurá el sistema de caja para exportar así."
            )
    return warnings


def preview_source(path, mapping, *, price, discount, complete=False,
                   timezone_name="America/Argentina/Buenos_Aires", sheet="", header_row=None,
                   number_format="auto"):
    from .config_discovery import resolve_runtime_config
    from .normalizer import count_problem_rows, describe_problems, normalize_rows
    from .readers import read_file
    from .summarizer import build_summary
    from .column_mapping import validate_explicit_mapping
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    config = resolve_runtime_config().config
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValidationError("Sólo se admiten CSV y XLSX tabulares; XLS, bases y APIs necesitan otro conector.")
    mapping = _check_mapping(mapping)
    if price not in {"final_net", "gross_before_discount"} or discount not in {"per_unit", "per_line", "percentage"}:
        raise ValidationError("Elegí el significado del precio y del descuento antes de continuar.")
    try:
        ZoneInfo(str(timezone_name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError("Elegí la zona horaria del comercio de la lista.") from exc
    if number_format not in {"auto", CONVENTION_COMMA, CONVENTION_DOT}:
        raise ValidationError("Elegí el formato de los números.")
    raw = {**config.raw, "column_mapping": mapping, "input_dir": str(path.parent),
           "source_schema_version": "2.0.0", "price_semantics": price, "discount_semantics": discount,
           "business_timezone": timezone_name, "daily_snapshot_complete": bool(complete),
           "daily_complete_file_sha256": None, "xlsx_sheet": sheet, "xlsx_header_row": header_row,
           "source_read_only": True, "move_processed_files": False, "move_error_files": False,
           "keep_original_files": True, "source_setup_required": False}
    raw.pop("decimal_separator", None)
    digest = compute_file_sha256(path)
    candidate = CollectorConfig(raw, config.config_path)
    identity = json.dumps([context_key(candidate), path.suffix.lower(), sheet]).encode()
    raw["daily_source_id"] = "source_" + hashlib.sha256(identity).hexdigest()[:40]
    rows = read_file(path, candidate)
    if not rows:
        raise ValidationError("No hay filas de ventas para previsualizar.")
    result = validate_explicit_mapping(mapping, list(rows[0]))
    if result.status != "auto_approved" or result.warnings or any(value not in rows[0] for value in mapping.values()):
        raise ValidationError("El mapeo no coincide con las columnas de la exportación.")
    raw["source_profile"] = {"context": context_key(candidate), "headers": sorted(rows[0]),
                             "suffix": path.suffix.lower()}

    # Se congela el formato de numeros que el comercio vio y confirmo en la
    # vista previa: el proximo archivo se lee igual aunque traiga otros valores.
    conventions, ambiguous = _conventions_for(rows, mapping, candidate, number_format)
    raw["decimal_conventions"] = {key: value for key, value in conventions.items() if value in {CONVENTION_COMMA, CONVENTION_DOT}}
    candidate = CollectorConfig(raw, config.config_path)

    normalized = normalize_rows(rows, candidate)
    problems = count_problem_rows(normalized, require_dates=True)
    if problems:
        detail = "\n".join("• " + line for line in describe_problems(normalized, require_dates=True))
        raise ValidationError(
            f"{problems} fila(s) no se pudieron leer; no se enviarán totales parciales. Revisá:\n{detail}"
        )
    summary = build_summary(normalized.rows, candidate, 1, len(rows), 0)
    if compute_file_sha256(path) != digest:
        raise ValidationError("El archivo cambió durante la vista previa. Volvé a previsualizar.")
    metrics = summary["daily_snapshot"]["metrics"]
    total = lambda key: sum((Decimal(m[key]) for m in metrics if m[key] is not None), Decimal(0))
    cost = total("cogs") if all(m["cogs"] is not None for m in metrics) else None
    net = total("net_revenue")
    from .daily import row_economics
    example_net, example_discount = row_economics(normalized.rows[0], candidate)
    first = normalized.rows[0]
    first_qty = canonical_decimal(first["_daily_decimal"].get("cantidad_vendida"))
    first_price = canonical_decimal(first["_daily_decimal"].get("precio_venta"))
    headers = list(rows[0])
    return {"config": raw, "path": str(path), "sha256": digest,
            "original_context": context_key(config), "summary": summary,
            "totals": {"unidades": str(total("quantity")), "ventas_netas": str(net),
                       "descuentos": str(total("discount_amount")), "costos": str(cost) if cost is not None else "desconocido",
                       "margen": str(net-cost) if cost is not None else "desconocido"},
            "totals_display": {"unidades": format_ar(total("quantity")), "ventas_netas": "$ " + format_ar(net),
                               "descuentos": "$ " + format_ar(total("discount_amount")),
                               "costos": "$ " + format_ar(cost) if cost is not None else "desconocido",
                               "margen": "$ " + format_ar(net - cost) if cost is not None else "desconocido"},
            "numbers": number_report(rows, mapping, headers, conventions, ambiguous),
            "warnings": value_warnings(rows, mapping, headers, conventions),
            "skipped_total_rows": normalized.skipped_total_rows,
            "products_without_code": len({m["product_code"] for m in metrics if str(m["product_code"]).startswith("name_hash:")}),
            "example": f"Primera venta: {format_ar(first_qty)} unidades × precio $ {format_ar(first_price)}; "
                       f"descuento $ {format_ar(example_discount)}; venta neta $ {format_ar(example_net)}. "
                       + ("El precio neto ya incluye el descuento; no se resta otra vez." if price == "final_net" else "El descuento se resta una sola vez del importe bruto.")}


def save_source_preview(preview):
    from .cli import _single_run_lock
    from .config_discovery import resolve_runtime_config
    from .desktop_service import _atomic_write_json, OperationResult
    runtime = resolve_runtime_config()
    with _single_run_lock(runtime.config) as acquired:
        if not acquired:
            raise ConfigError("Hay una sincronización activa; esperá a que termine.")
        if context_key(runtime.config) != preview["original_context"]:
            raise ConfigError("Cambió la vinculación o la fuente; repetí la vista previa.")
        if compute_file_sha256(Path(preview["path"])) != preview["sha256"]:
            raise ConfigError("El archivo cambió: repetí la vista previa antes de guardar.")
        backup = collector_data_dir() / "backups"
        backup.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(runtime.selected_path, backup / f"config-before-source-{stamp}.json")
        _atomic_write_json(runtime.selected_path, preview["config"])
    return OperationResult(True, "Fuente configurada", "Mapeo, formato de números y cálculo guardados para este comercio. Podés sincronizar o reprocesar sólo el archivo rechazado.")


def reprocess_rejected(path):
    from .cli import _backend_target, _single_run_lock, _process_reliable_file
    from .config_discovery import resolve_runtime_config
    from .client import CollectorClient
    from .desktop_service import OperationResult
    from .local_state import connect as connect_local_state, local_db_path, add_event
    config = resolve_runtime_config().config
    validate_profile(config)
    config.require_send_ready()
    path = Path(path).resolve(strict=True)
    if path.parent != config.path("input_dir").resolve():
        raise ConfigError("Elegí un archivo de la fuente del comercio activo.")
    with _single_run_lock(config) as acquired:
        if not acquired:
            raise ConfigError("Hay una sincronización activa; esperá a que termine.")
        conn = connect_local_state(local_db_path(config))
        try:
            row = conn.execute("SELECT * FROM processed_files WHERE file_path=? AND commerce_id=? AND collector_id=? AND backend_url=? AND (source_id=? OR source_id IS NULL) ORDER BY updated_at DESC LIMIT 1",
                               (str(path), config.commerce_id, config.collector_id, _backend_target(config), config.raw["daily_source_id"])).fetchone()
            if not row or row["status"] not in {"error", "needs_mapping"}:
                raise ConfigError("Este archivo no está rechazado en el comercio activo. No se reenvió.")
            add_event(conn, file_id=row["file_id"], event_type="selective_retry_requested", level="info", message="Reproceso selectivo solicitado desde la interfaz.")
            status, message = _process_reliable_file(config=config, client=CollectorClient(config), conn=conn, path=path,
                                                    backend_mapping=None, expected_sha256=compute_file_sha256(path))
            return OperationResult(status in {"sent", "duplicate"}, "Reproceso " + status, message or "Archivo procesado; historial y cola conservados.")
        finally:
            conn.close()
