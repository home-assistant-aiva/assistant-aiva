"""Versioned, tenant-bound configuration. Contains no source credentials or samples."""
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .connectors.base import AccessError, Window

STATES = ("detected", "configuration_incomplete", "credentials_required", "driver_required", "profile_required",
          "access_tested", "mapping_pending", "ready", "sync_completed", "intervention_required", "paused")
FORBIDDEN = {"password", "pwd", "token", "access_token", "refresh_token", "api_key", "authorization", "connection_string", "client_secret", "secret", "username"}


def reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN:
                raise AccessError("secret_in_profile", "El perfil contiene credenciales. Ingresalas en el almacén protegido, no en JSON.")
            reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            reject_secrets(item)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def context(config):
    from urllib.parse import urlsplit
    parsed = urlsplit(config.backend_url)
    destination = [parsed.scheme.lower(), (parsed.hostname or '').lower(), parsed.port, parsed.path.rstrip('/')]
    return digest([destination, config.commerce_id, config.collector_id])


def connection_path(config):
    return config.path("state_dir") / ("connection-" + context(config) + ".json")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as f:
            os.chmod(temporary, 0o600)
            json.dump(value, f, ensure_ascii=True, sort_keys=True, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def period(days=90, *, timezone="America/Argentina/Buenos_Aires", start=None, end=None, include_today=False, now=None, mode=None):
    today = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone)).date()
    until = date.fromisoformat(end) if end else today if include_today else today - timedelta(days=1)
    if mode == 'three_closed_months_current':
        month_index = today.year * 12 + today.month - 1 - 3
        year, month = divmod(month_index, 12)
        since = date(year, month + 1, 1)
    elif mode is None:
        since = date.fromisoformat(start) if start else until - timedelta(days=int(days) - 1)
    else:
        raise AccessError('period_invalid', 'La opción de historial no es válida.')
    if until > today:
        raise AccessError("future_period", "No se puede solicitar información de días futuros.")
    return Window(since, until)


def load_connection(config):
    path = connection_path(config)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get("version") != 1 or data.get("context") != context(config):
        raise AccessError("context_changed", "La configuración pertenece a otra vinculación o versión.")
    reject_secrets(data)
    return data


def validate_profile(profile):
    reject_secrets(profile)
    reader_allowed = {"date_format", "xlsx_sheet", "xlsx_header_row", "decimal_conventions", "decimal_separator", "column_mapping", "price_semantics", "discount_semantics"}
    if set(profile.get("reader", {})) - reader_allowed:
        raise AccessError("reader_option_invalid", "El perfil incluye opciones ajenas a lectura y mapeo.")
    if profile.get("kind") not in {"files", "rest", "sqlite", "odbc"}:
        raise AccessError("profile_required", "Elegí un conector implementado o pedí una exportación CSV/XLSX.")
    if profile.get("scope", "whole_commerce") != "whole_commerce":
        raise AccessError("scope_unsupported", "El contrato actual exige el comercio completo; sucursales o depósitos separados necesitan un perfil de consolidación revisado.")
    if profile.get("semantics", "whole_day_snapshot") != "whole_day_snapshot":
        raise AccessError("delta_unsupported", "Se requieren snapshots completos por día. Lotes incrementales requieren adaptación del proveedor.")
    required = {"files": ("folder",), "rest": ("base_url", "path", "fields", "date_filters"),
                "sqlite": ("path", "table", "columns", "date_column"),
                "odbc": ("engine", "server", "database", "table", "columns", "date_column", "auth")}[profile["kind"]]
    if any(not profile.get(k) for k in required):
        raise AccessError("configuration_incomplete", "Faltan parámetros del perfil de lectura.")
    if profile["kind"] == "rest":
        from .connectors.rest import secure_url
        secure_url(profile["base_url"])
    if profile.get("location_column") or profile.get("unit_factor", 1) != 1:
        raise AccessError("scope_unsupported", "Sucursales, depósitos y conversiones de unidades necesitan un perfil de consolidación revisado; no se agregan automáticamente.")
    if profile.get("status_column") and not (profile.get("accepted_values") and isinstance(profile.get("cancelled_values"), list)):
        raise AccessError("status_profile_required", "Confirmá estados aceptados y anulados con el proveedor.")
    if profile.get("cost_basis", "unknown") not in {"historical", "current", "unknown"}:
        raise AccessError("cost_basis_invalid", "Confirmá si el costo es histórico, actual o desconocido.")
    if profile.get('history_mode') not in (None, 'three_closed_months_current'):
        raise AccessError('period_invalid', 'La opción de historial no es válida.')


def save_connection(config, profile, mapping, window, *, frequency=15, review_days=7, confirmed=False, expected=None, source_id=None):
    validate_profile(profile)
    if not {"fecha", "producto_nombre", "cantidad_vendida", "precio_venta"} <= set(mapping):
        raise AccessError("mapping_pending", "Confirmá fecha, producto, cantidad y precio unitario.")
    if len(set(mapping.values())) != len(mapping):
        raise AccessError("mapping_invalid", "Una columna no puede representar dos campos.")
    if not confirmed:
        raise AccessError("confirmation_required", "Revisá mapeo, precios, cobertura y período antes de activar.")
    if int(frequency) not in {15, 30, 60, 180, 360, 1440} or not 1 <= int(review_days) <= 365:
        raise AccessError("schedule_invalid", "Elegí una frecuencia válida y entre 1 y 365 días de revisión.")
    previous = load_connection(config)
    if expected != (digest(previous) if previous else None):
        raise AccessError("stale_confirmation", "La configuración cambió. Volvé a probar y confirmar la fuente.")
    identity = {k: v for k, v in profile.items() if k not in {"mapping", "reader", "complete_days", "cost_basis", "max_rows", "timeout_seconds", "history_mode", "include_today", "inventory_confirmation"}}
    source = source_id or "source_" + digest([context(config), identity])[:40]
    if previous and previous["source_id"] != source:
        raise AccessError("source_transition_required", "Cambiar de fuente puede solapar ventas. Conservá la fuente actual y solicitá una transición revisada en Backend.")
    revision = (previous or {}).get("configuration_revision", 0) + 1
    value = {"version": 1, "context": context(config), "source_id": source, "configuration_revision": revision,
             "profile": {**profile, "mapping": mapping}, "mapping": mapping,
             "window": {"start": str(window.start), "end": str(window.end)},
             "frequency_minutes": int(frequency), "review_days": int(review_days), "state": "ready", "paused": False,
             "mapping_revision": digest(mapping), "confirmed": True}
    atomic_json(connection_path(config), value)
    return value


def set_paused(config, paused):
    value = load_connection(config)
    if not value:
        raise AccessError("configuration_incomplete", "Primero configurá una fuente.")
    value.update(paused=bool(paused), state="paused" if paused else "ready")
    atomic_json(connection_path(config), value)


def recommendations(alternatives):
    """Explain evidence; never let a detected driver outrank verified coverage."""
    result = []
    for alternative in alternatives:
        a = dict(alternative)
        evidence = a.get("evidence", {})
        reasons = []
        score = 0
        for field, weight, label in (("access_tested", 5, "Acceso probado"), ("sales", 4, "Ventas comprobadas"),
                ("costs", 2, "Costos comprobados"), ("stock", 2, "Stock con fecha comprobado"),
                ("history", 2, "Historial comprobado"), ("stable_ids", 2, "Identificadores estables"),
                ("corrections", 2, "Permite corregir períodos"), ("automated", 2, "Lectura automática"),
                ("read_only", 3, "Lectura segura"), ("stable_profile", 2, "Perfil estable")):
            if evidence.get(field) is True:
                score += weight
                reasons.append(label)
        if evidence.get("manual_exports"):
            score -= 2
            reasons.append("Depende de exportaciones manuales")
        if evidence.get("high_impact"):
            score -= 4
            reasons.append("Puede cargar el sistema comercial")
        a.update(score=score, reasons=reasons or ["Detección sin acceso ni campos comprobados"],
                 recommendation="candidate" if evidence.get("access_tested") else "needs_verification")
        result.append(a)
    return sorted(result, key=lambda a: -a["score"])
