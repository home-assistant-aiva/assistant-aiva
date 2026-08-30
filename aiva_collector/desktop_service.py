from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli import (
    DEFAULT_BACKEND_URL,
    DEFAULT_COLLECTOR_VERSION,
    _report_selected_input_source,
    _write_activation_config,
    cmd_run_auto,
    stable_machine_id,
)
from .client import CollectorClient, activate_collector
from .config import collector_data_dir
from .config_discovery import resolve_runtime_config, standard_config_path
from .errors import CollectorError, ConfigError
from .local_state import local_db_path
from .token_store import save_token


TASK_NAME = "AIVA Collector Auto"
SUPPORTED_SOURCE_SUFFIXES = {".csv", ".xlsx"}


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    title: str
    message: str


@dataclass(frozen=True)
class DashboardSnapshot:
    state: str
    title: str
    detail: str
    version: str
    config_path: str | None
    commerce_id: str | None
    collector_id: str | None
    input_dir: str | None
    source_exists: bool
    source_files: int
    token_configured: bool
    scheduled_task_installed: bool | None
    last_run_at: str | None
    last_result: str | None
    files_processed: int
    summaries_sent: int
    queue_pending: int
    last_error: str | None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _short_identifier(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip()
    if len(clean) <= 12:
        return clean
    return f"…{clean[-8:]}"


def _uses_secure_transport(backend_url: str) -> bool:
    return backend_url.strip().lower().startswith("https://")


def _source_file_count(path: Path | None) -> int:
    if path is None or not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for item in path.iterdir() if item.is_file() and item.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES)
    except OSError:
        return 0


def _read_queue_pending(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM upload_queue WHERE status IN ('pending', 'retrying', 'processing')"
            ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0


def scheduled_task_installed() -> bool | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def load_dashboard_snapshot() -> DashboardSnapshot:
    task_installed = scheduled_task_installed()
    try:
        runtime = resolve_runtime_config()
        config = runtime.config
    except CollectorError as exc:
        return DashboardSnapshot(
            state="setup",
            title="Falta conectar este equipo",
            detail="Ingresá el código generado en AIVA Comercial para vincular el Collector.",
            version=DEFAULT_COLLECTOR_VERSION,
            config_path=str(standard_config_path()),
            commerce_id=None,
            collector_id=None,
            input_dir=None,
            source_exists=False,
            source_files=0,
            token_configured=False,
            scheduled_task_installed=task_installed,
            last_run_at=None,
            last_result=None,
            files_processed=0,
            summaries_sent=0,
            queue_pending=0,
            last_error=str(exc),
        )

    try:
        token_configured = bool(config.token)
        token_error = None
    except CollectorError as exc:
        token_configured = False
        token_error = str(exc)
    try:
        input_path = config.path("input_dir")
    except ConfigError:
        input_path = None
    auto_state = _read_json(config.path("state_dir") / "last_auto_run.json")
    pending = _read_queue_pending(local_db_path(config))
    source_exists = bool(input_path and input_path.exists() and input_path.is_dir())
    source_files = _source_file_count(input_path)
    last_result = str(auto_state.get("result") or "") or None
    last_error = str(auto_state.get("error_summary") or "") or None

    if not token_configured:
        state = "setup"
        title = "Falta activar AIVA Collector"
        detail = "Usá un código de activación para conectar este equipo de forma segura."
    elif not source_exists:
        state = "attention"
        title = "Conectado, falta elegir la carpeta de datos"
        detail = "Seleccioná la carpeta donde el sistema de ventas genera archivos CSV o Excel."
    elif not _uses_secure_transport(config.backend_url):
        state = "attention"
        title = "Conectado en modo de prueba"
        detail = "El servicio todavía usa HTTP. Antes de instalarlo en clientes, AIVA debe publicarse con HTTPS."
    elif last_result == "error":
        state = "error"
        title = "Conectado, con una sincronización pendiente de revisión"
        detail = last_error or "La última ejecución encontró un problema. AIVA volverá a intentarlo."
    elif pending:
        state = "attention"
        title = "Conectado, con envíos pendientes"
        detail = f"Hay {pending} envío(s) en cola. AIVA volverá a intentarlo automáticamente."
    else:
        state = "connected"
        title = "AIVA Collector está conectado"
        detail = "La conexión está preparada y la sincronización automática queda activa."

    return DashboardSnapshot(
        state=state,
        title=title,
        detail=detail,
        version=config.collector_version or DEFAULT_COLLECTOR_VERSION,
        config_path=str(runtime.selected_path),
        commerce_id=_short_identifier(config.commerce_id),
        collector_id=_short_identifier(config.collector_id),
        input_dir=str(input_path) if input_path else None,
        source_exists=source_exists,
        source_files=source_files,
        token_configured=token_configured,
        scheduled_task_installed=task_installed,
        last_run_at=str(auto_state.get("finished_at") or auto_state.get("started_at") or "") or None,
        last_result=last_result,
        files_processed=int(auto_state.get("files_processed") or 0),
        summaries_sent=int(auto_state.get("summaries_sent") or 0),
        queue_pending=pending,
        last_error=last_error or token_error,
    )


def activate_installation(code: str, backend_url: str = DEFAULT_BACKEND_URL) -> OperationResult:
    activation_code = code.strip()
    if not activation_code:
        return OperationResult(False, "Falta el código", "Pegá el código generado desde AIVA Comercial.")
    url = backend_url.strip().rstrip("/") or DEFAULT_BACKEND_URL
    if not (url.startswith("https://") or url.startswith("http://")):
        return OperationResult(False, "Dirección inválida", "La dirección de AIVA debe comenzar con https:// o http://.")
    try:
        response = activate_collector(
            backend_url=url,
            activation_code=activation_code,
            machine_id=stable_machine_id(),
            hostname=socket.gethostname(),
            collector_version=DEFAULT_COLLECTOR_VERSION,
        )
        config_path = standard_config_path()
        _write_activation_config(config_path, backend_url=url, response=response)
        config = resolve_runtime_config(config_path).config
        save_token(config.path("state_dir"), response["collector_token"])
        CollectorClient(config).service_status()
    except (CollectorError, KeyError, OSError) as exc:
        return OperationResult(False, "No se pudo conectar", str(exc))
    if _uses_secure_transport(url):
        message = "La activación quedó guardada de forma segura. Ahora elegí la carpeta de datos del sistema de ventas."
    else:
        message = (
            "El equipo quedó conectado en modo de prueba. Antes de usarlo con clientes, configurá el servicio AIVA con HTTPS. "
            "Ahora elegí la carpeta de datos."
        )
    return OperationResult(True, "Equipo conectado", message)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def configure_source_folder(value: str | Path) -> OperationResult:
    folder = Path(value).expanduser()
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        return OperationResult(False, "Carpeta no disponible", f"No se puede acceder a la carpeta seleccionada: {exc}")
    if not folder.is_dir():
        return OperationResult(False, "Selección inválida", "Elegí una carpeta, no un archivo.")
    try:
        runtime = resolve_runtime_config()
        config_path = runtime.selected_path
        payload = dict(runtime.config.raw)
        backup_dir = collector_data_dir() / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(config_path, backup_dir / f"config-before-source-{stamp}.json")
        payload["input_dir"] = str(folder)
        payload["source_mode"] = "watched_folder"
        payload["source_read_only"] = True
        payload["move_processed_files"] = False
        payload["move_error_files"] = False
        payload["keep_original_files"] = True
        payload["source_configured_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(config_path, payload)
        config = resolve_runtime_config(config_path).config
        try:
            _report_selected_input_source(config)
        except CollectorError:
            pass
    except (CollectorError, OSError) as exc:
        return OperationResult(False, "No se pudo guardar la carpeta", str(exc))
    count = _source_file_count(folder)
    suffix = f" Se encontraron {count} archivo(s) compatible(s)." if count else " La carpeta está vacía; AIVA esperará nuevos archivos."
    return OperationResult(True, "Carpeta conectada", f"AIVA observará: {folder}.{suffix}")


def test_aiva_connection() -> OperationResult:
    try:
        config = resolve_runtime_config().config
        config.require_send_ready()
        CollectorClient(config).service_status()
    except CollectorError as exc:
        return OperationResult(False, "Conexión no disponible", str(exc))
    if not _uses_secure_transport(config.backend_url):
        return OperationResult(
            True,
            "Conexión correcta en modo de prueba",
            "Este equipo pudo autenticarse, pero la dirección usa HTTP. Configurá HTTPS antes de instalarlo en clientes.",
        )
    return OperationResult(True, "Conexión correcta", "Este equipo pudo autenticarse con AIVA mediante HTTPS.")


def synchronize_now() -> OperationResult:
    try:
        runtime = resolve_runtime_config()
        code = cmd_run_auto(argparse.Namespace(config=str(runtime.selected_path)))
    except CollectorError as exc:
        return OperationResult(False, "No se pudo sincronizar", str(exc))
    except Exception as exc:  # pragma: no cover - last-resort desktop boundary
        return OperationResult(False, "No se pudo sincronizar", f"Error interno del Collector: {exc}")
    if code != 0:
        return OperationResult(False, "Sincronización con observaciones", "Revisá el estado y el registro de actividad.")
    snapshot = load_dashboard_snapshot()
    if snapshot.source_files == 0 and snapshot.files_processed == 0:
        return OperationResult(True, "Collector activo", "No había archivos nuevos. AIVA seguirá observando la carpeta automáticamente.")
    return OperationResult(
        True,
        "Sincronización finalizada",
        f"Procesados: {snapshot.files_processed}. Enviados: {snapshot.summaries_sent}. Pendientes: {snapshot.queue_pending}.",
    )


def open_folder(path: str | Path) -> OperationResult:
    folder = Path(path)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        return OperationResult(False, "No se pudo abrir la carpeta", str(exc))
    return OperationResult(True, "Carpeta abierta", str(folder))


def logs_folder() -> Path:
    try:
        return resolve_runtime_config().config.path("log_file").parent
    except CollectorError:
        return collector_data_dir() / "logs"
