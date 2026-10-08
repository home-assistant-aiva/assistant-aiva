"""Local source setup. Preview never contacts the backend or mutates source files."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import CollectorConfig, collector_data_dir
from .errors import ConfigError, ValidationError
from .file_fingerprint import compute_file_sha256

FIELDS = {
    "fecha": "Fecha de venta", "producto_nombre": "Producto",
    "producto_codigo": "Código estable", "cantidad_vendida": "Cantidad",
    "precio_venta": "Precio unitario", "descuento": "Descuento",
    "costo_unitario": "Costo unitario", "stock_actual": "Stock",
    "fecha_stock": "Fecha del stock", "categoria": "Categoría",
}
REQUIRED = {"fecha", "producto_nombre", "producto_codigo", "cantidad_vendida", "precio_venta"}


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


def preview_source(path, mapping, *, price, discount, complete=False,
                   timezone_name="America/Argentina/Buenos_Aires", sheet="", header_row=None):
    from .config_discovery import resolve_runtime_config
    from .normalizer import normalize_rows
    from .readers import read_file
    from .summarizer import build_summary
    from .column_mapping import validate_explicit_mapping
    from decimal import Decimal
    config = resolve_runtime_config().config
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValidationError("Sólo se admiten CSV y XLSX tabulares; XLS, bases y APIs necesitan otro conector.")
    mapping = {key: value for key, value in mapping.items() if value}
    if not REQUIRED <= mapping.keys() or len(set(mapping.values())) != len(mapping):
        raise ValidationError("Asigná fecha, producto, código, cantidad y precio a columnas distintas.")
    if price not in {"final_net", "gross_before_discount"} or discount not in {"per_unit", "per_line", "percentage"}:
        raise ValidationError("Elegí el significado del precio y del descuento antes de continuar.")
    raw = {**config.raw, "column_mapping": mapping, "input_dir": str(path.parent),
           "source_schema_version": "2.0.0", "price_semantics": price, "discount_semantics": discount,
           "business_timezone": timezone_name, "daily_snapshot_complete": bool(complete),
           "daily_complete_file_sha256": None, "xlsx_sheet": sheet, "xlsx_header_row": header_row,
           "source_read_only": True, "move_processed_files": False, "move_error_files": False,
           "keep_original_files": True, "source_setup_required": False}
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
    normalized = normalize_rows(rows, candidate)
    if normalized.discarded or any(not r.get("fecha") or not r.get("producto_codigo") for r in normalized.rows):
        raise ValidationError("Hay filas inválidas, fechas ilegibles o códigos vacíos. Corregí la fuente; no se enviarán totales parciales.")
    summary = build_summary(normalized.rows, candidate, 1, len(rows), 0)
    if compute_file_sha256(path) != digest:
        raise ValidationError("El archivo cambió durante la vista previa. Volvé a previsualizar.")
    metrics = summary["daily_snapshot"]["metrics"]
    total = lambda key: sum((Decimal(m[key]) for m in metrics if m[key] is not None), Decimal(0))
    cost = total("cogs") if all(m["cogs"] is not None for m in metrics) else None
    net = total("net_revenue")
    from .daily import row_economics
    example_net, example_discount = row_economics(normalized.rows[0], candidate)
    return {"config": raw, "path": str(path), "sha256": digest,
            "original_context": context_key(config), "summary": summary,
            "totals": {"unidades": str(total("quantity")), "ventas_netas": str(net),
                       "descuentos": str(total("discount_amount")), "costos": str(cost) if cost is not None else "desconocido",
                       "margen": str(net-cost) if cost is not None else "desconocido"},
            "example": f"Primera línea: {normalized.rows[0]['cantidad_vendida']} unidades × precio {normalized.rows[0]['precio_venta']}; descuento total {example_discount}; venta neta {example_net}. "
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
    return OperationResult(True, "Fuente configurada", "Mapeo y cálculo guardados para este comercio. Podés sincronizar o reprocesar sólo el archivo rechazado.")


def reprocess_rejected(path):
    from .cli import _single_run_lock, _process_reliable_file
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
                               (str(path), config.commerce_id, config.collector_id, config.backend_url, config.raw["daily_source_id"])).fetchone()
            if not row or row["status"] not in {"error", "needs_mapping"}:
                raise ConfigError("Este archivo no está rechazado en el comercio activo. No se reenvió.")
            add_event(conn, file_id=row["file_id"], event_type="selective_retry_requested", level="info", message="Reproceso selectivo solicitado desde la interfaz.")
            status, message = _process_reliable_file(config=config, client=CollectorClient(config), conn=conn, path=path,
                                                    backend_mapping=None, expected_sha256=compute_file_sha256(path))
            return OperationResult(status in {"sent", "duplicate"}, "Reproceso " + status, message or "Archivo procesado; historial y cola conservados.")
        finally:
            conn.close()
