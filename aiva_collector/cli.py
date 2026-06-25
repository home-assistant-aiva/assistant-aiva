from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .column_mapping import (
    ColumnMappingResult,
    detect_column_mapping,
    sample_preview,
    validate_explicit_mapping,
)
from .client import CollectorClient, activate_collector
from .config import PROJECT_ROOT, CollectorConfig, init_config, load_config
from .errors import BackendError, CollectorError, ConfigError, ValidationError
from .file_fingerprint import build_file_id, compute_file_sha256, compute_normalized_data_hash, wait_for_stable_file
from .local_state import (
    add_event,
    connect as connect_local_state,
    get_by_sha256,
    local_db_path,
    queue_counts,
    queue_summary,
    status_counts,
    update_file_state,
    upsert_detected_file,
    utc_now,
)
from .logging_setup import setup_logging
from .normalizer import normalize_rows
from .offline_queue import enqueue_payload, process_queue
from .readers import detect_columns, discover_input_files, read_file
from .state import save_state
from .summarizer import build_summary, idempotency_key
from .token_store import save_token
from .validation import validate_normalized_data


WINDOWS_DEFAULT_CONFIG = r"C:\AIVA_Comercio\config.local.json"
DEFAULT_BACKEND_URL = "http://187.77.44.118:8080"
DEFAULT_COLLECTOR_VERSION = "0.2.5"


def default_config_path() -> str | None:
    if sys.platform.startswith("win"):
        return WINDOWS_DEFAULT_CONFIG
    return None


def _safe_idem_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def safe_display_path(path: Path, base: Path = PROJECT_ROOT) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def validate_config(config: CollectorConfig) -> list[Path]:
    files = discover_input_files(config)
    if not files:
        raise ValidationError("No se detectaron archivos CSV/XLSX en input_dir")
    columns = detect_columns(files, config)
    explicit = validate_explicit_mapping(config.column_mapping, columns) if config.column_mapping else None
    detected = explicit if explicit and explicit.status == "auto_approved" else detect_column_mapping(columns)
    if detected.status == "failed":
        raise ValidationError("AIVA necesita revisar el mapeo de columnas desde el admin.")
    config.path("processed_dir").mkdir(parents=True, exist_ok=True)
    config.path("error_dir").mkdir(parents=True, exist_ok=True)
    config.path("output_dir").mkdir(parents=True, exist_ok=True)
    config.path("state_dir").mkdir(parents=True, exist_ok=True)
    return files


def _config_with_mapping(config: CollectorConfig, mapping: dict[str, str]) -> CollectorConfig:
    raw = dict(config.raw)
    raw["column_mapping"] = dict(mapping)
    return CollectorConfig(raw=raw, config_path=config.config_path)


def _headers_from_rows(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    return [str(header) for header in rows[0].keys()]


def _backend_mapping(config: CollectorConfig) -> dict[str, str] | None:
    if not config.token or not config.backend_url:
        return None
    try:
        response = CollectorClient(config).get_column_mapping()
    except BackendError as exc:
        logging.warning("No se pudo consultar mapping activo; se usa deteccion local: %s", exc)
        return None
    mapping = response.get("mapping")
    if isinstance(mapping, dict) and mapping:
        return {str(key): str(value) for key, value in mapping.items()}
    return None


def _resolve_mapping_for_rows(
    config: CollectorConfig,
    rows: list[dict],
    *,
    backend_mapping: dict[str, str] | None = None,
) -> tuple[CollectorConfig, ColumnMappingResult]:
    headers = _headers_from_rows(rows)
    warnings: list[str] = []
    for source, mapping in (("backend", backend_mapping), ("explicit", config.column_mapping)):
        if not mapping:
            continue
        result = validate_explicit_mapping(mapping, headers)
        if result.status == "auto_approved":
            if warnings:
                result.warnings[:0] = warnings
            return _config_with_mapping(config, result.mapping), result
        warnings.append(f"Mapping {source} no coincide con las columnas detectadas; se intentó autodetección.")
    result = detect_column_mapping(headers)
    result.warnings[:0] = warnings
    return _config_with_mapping(config, result.mapping), result


def _mapping_candidate_payload(path: Path, rows: list[dict], result: ColumnMappingResult, config: CollectorConfig) -> dict:
    include_preview = bool(config.raw.get("send_mapping_sample_preview", False))
    return {
        "commerce_id": config.commerce_id,
        "collector_id": config.collector_id,
        "headers": result.detected_headers,
        "suggested_mapping": result.mapping,
        "confidence": result.confidence,
        "status": result.status,
        "sample_preview": sample_preview(rows, result.detected_headers, include_values=include_preview),
        "file_name": path.name,
    }


def _print_mapping_used(result: ColumnMappingResult) -> None:
    print(f"mapping status: {result.status}")
    print(f"mapping confidence: {result.confidence}")
    print("mapping usado:")
    for field, source in sorted(result.mapping.items()):
        print(f"  {field}: {source}")


def _collect(config: CollectorConfig, *, backend_mapping: dict[str, str] | None = None) -> tuple[dict, list[Path], list[dict]]:
    files = validate_config(config)
    logging.info("collector run start")
    logging.info("files detected count=%s", len(files))
    all_rows = []
    discarded = []
    rows_read = 0
    for path in files:
        raw_rows = read_file(path, config)
        rows_read += len(raw_rows)
        effective_config, mapping_result = _resolve_mapping_for_rows(config, raw_rows, backend_mapping=backend_mapping)
        if mapping_result.status != "auto_approved":
            raise ValidationError("AIVA necesita revisar el mapeo de columnas desde el admin.")
        logging.info("mapping used file=%s confidence=%s mapping=%s", path.name, mapping_result.confidence, mapping_result.mapping)
        result = normalize_rows(raw_rows, effective_config)
        all_rows.extend(result.rows)
        for item in result.discarded:
            item["file"] = path.name
            discarded.append(item)
    summary = build_summary(
        all_rows,
        config,
        files_processed=len(files),
        rows_read=rows_read,
        rows_discarded=len(discarded),
    )
    logging.info(
        "summary built files=%s rows_read=%s rows_valid=%s rows_invalid=%s products=%s",
        len(files),
        rows_read,
        len(all_rows),
        len(discarded),
        len(summary["productos_resumidos"]),
    )
    return summary, files, discarded


def _write_summary(config: CollectorConfig, summary: dict) -> Path:
    output_dir = config.path("output_dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "last_summary.json"
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=True)
    return output_path


def _print_compact_summary(summary: dict, output_path: Path) -> None:
    metadata = summary["metadata"]
    financiero = summary["resumen_financiero"]
    print("AIVA Collector dry-run")
    print(f"archivos procesados: {metadata['archivos_procesados']}")
    print(f"filas leidas: {metadata['filas_leidas']}")
    print(f"filas validas: {metadata['filas_validas']}")
    print(f"filas descartadas: {metadata['filas_descartadas']}")
    print(f"productos resumidos: {len(summary['productos_resumidos'])}")
    print(f"facturacion total: {financiero['facturacion_total']}")
    print(f"margen estimado: {financiero['margen_bruto_estimado']}")
    print(f"periodo: {summary['fecha_inicio']} a {summary['fecha_fin']} ({summary['periodo']})")
    print(f"summary: {output_path}")


def _move_processed_if_enabled(config: CollectorConfig, files: list[Path]) -> list[str]:
    if not bool(config.raw.get("move_processed_files", False)):
        return []
    processed_dir = config.path("processed_dir")
    moved = []
    for source in files:
        dest = processed_dir / source.name
        shutil.move(str(source), str(dest))
        moved.append(safe_display_path(dest))
    return moved


def _timestamped_dest(directory: Path, source: Path, *, suffix: str | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    extra = f".{suffix}" if suffix else ""
    return directory / f"{source.stem}.{stamp}{extra}{source.suffix}"


def _move_files(files: list[Path], directory: Path, *, suffix: str | None = None) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    moved = []
    for source in files:
        if not source.exists():
            continue
        dest = _timestamped_dest(directory, source, suffix=suffix)
        shutil.move(str(source), str(dest))
        moved.append(safe_display_path(dest))
    return moved


def _config_bool(config: CollectorConfig, key: str, default: bool) -> bool:
    return bool(config.raw.get(key, default))


def _runtime_dirs(config: CollectorConfig) -> None:
    for key in ("input_dir", "processed_dir", "error_dir", "output_dir", "state_dir"):
        config.path(key).mkdir(parents=True, exist_ok=True)
    (config.path("processed_dir") / "duplicados").mkdir(parents=True, exist_ok=True)
    (config.path("state_dir") / "queue").mkdir(parents=True, exist_ok=True)


def _archive_file(config: CollectorConfig, path: Path, target_dir: Path, *, suffix: str | None = None) -> list[str]:
    if not path.exists():
        return []
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = _timestamped_dest(target_dir, path, suffix=suffix)
    if _config_bool(config, "keep_original_files", False):
        shutil.copy2(path, dest)
    else:
        shutil.move(str(path), str(dest))
    return [str(dest)]


def _write_error_note(error_file: Path, original: Path, message: str) -> Path:
    note = error_file.with_suffix(error_file.suffix + ".error.txt")
    note.write_text(
        f"AIVA Collector no envio este archivo.\nArchivo: {original.name}\nMotivo: {message}\n",
        encoding="utf-8",
    )
    return note


def _file_stat_metadata(path: Path) -> tuple[int, str]:
    stat = path.stat()
    return stat.st_size, datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()


def _attach_reliability_metadata(
    summary: dict,
    *,
    file_id: str,
    path: Path,
    file_sha256: str,
    normalized_data_hash: str,
    detected_at: str,
    processed_at: str,
    validation: dict,
) -> None:
    file_size, file_mtime = _file_stat_metadata(path)
    metadata = summary.setdefault("metadata", {})
    metadata["source_file"] = {
        "file_id": file_id,
        "file_name": path.name,
        "file_sha256": file_sha256,
        "normalized_data_hash": normalized_data_hash,
        "file_size": file_size,
        "file_mtime": file_mtime,
        "detected_at": detected_at,
        "processed_at": processed_at,
        "rows_total": validation["rows_total"],
        "rows_valid": validation["rows_valid"],
        "rows_invalid": validation["rows_invalid"],
    }
    metadata["validation"] = {
        "warnings": validation["warnings"],
        "blocking_errors": validation["blocking_errors"],
    }


def _machine_id_path() -> Path:
    if sys.platform.startswith("win"):
        return Path(r"C:\AIVA_Comercio\state\machine.id")
    return PROJECT_ROOT / "state" / "machine.id"


def stable_machine_id() -> str:
    path = _machine_id_path()
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = f"aiva-{uuid.uuid4().hex}"
    path.write_text(value, encoding="utf-8")
    return value


def _activation_config_path(value: str | None) -> Path:
    return Path(value or WINDOWS_DEFAULT_CONFIG)


def _looks_like_activation_code(value: str) -> bool:
    normalized = value.strip()
    return normalized.lower().startswith("aiva_col_") or normalized.upper().startswith("AIVA-")


def _normalize_backend_url(value: str) -> str:
    backend_url = (value.strip() or DEFAULT_BACKEND_URL).rstrip("/")
    if _looks_like_activation_code(backend_url):
        raise ConfigError(
            "Parece que pegaste el código en el campo URL. Presioná Enter en Backend URL y pegá el código cuando se pida Código de activación."
        )
    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("Backend URL inválida. Debe empezar con http:// o https://.")
    return backend_url


def _write_activation_config(path: Path, *, backend_url: str, response: dict) -> None:
    defaults = dict(response.get("config_defaults") or {})
    config = {
        "backend_url": backend_url.rstrip("/"),
        "commerce_id": response["commerce_id"],
        "collector_id": response["collector_id"],
        "collector_version": response.get("collector_version") or DEFAULT_COLLECTOR_VERSION,
        "collector_token_env": "AIVA_COLLECTOR_TOKEN",
        **defaults,
    }
    config.pop("collector_token", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _install_scheduled_task_if_available() -> None:
    if not sys.platform.startswith("win"):
        return
    script = Path(sys.executable).resolve().parent / "install_scheduled_task.bat"
    if script.exists():
        os.system(f'"{script}"')


def cmd_activate(args: argparse.Namespace) -> int:
    raw_backend_url = args.backend_url if args.backend_url is not None else input(f"Backend URL [{DEFAULT_BACKEND_URL}]: ")
    backend_url = _normalize_backend_url(raw_backend_url)
    code = args.code or input("Código de activación: ").strip()
    if not code:
        raise ConfigError("activation_code_invalid: ingresá un código de activación")
    response = activate_collector(
        backend_url=backend_url,
        activation_code=code,
        machine_id=stable_machine_id(),
        hostname=socket.gethostname(),
        collector_version=DEFAULT_COLLECTOR_VERSION,
    )
    config_path = _activation_config_path(args.config)
    _write_activation_config(config_path, backend_url=backend_url, response=response)
    config = load_config(config_path)
    save_token(config.path("state_dir"), response["collector_token"])
    try:
        CollectorClient(config).service_status()
    except BackendError as exc:
        raise BackendError(f"Activación guardada, pero falló estado conexión: {exc}", status_code=exc.status_code) from exc
    print("AIVA Collector activado correctamente.")
    print(f"Config: {config_path}")
    print("Token guardado de forma segura. No se muestra en pantalla.")
    if args.install_task:
        _install_scheduled_task_if_available()
    return 0


def _collect_auto(
    config: CollectorConfig,
    files: list[Path],
    *,
    backend_mapping: dict[str, str] | None = None,
) -> tuple[dict | None, list[Path], list[Path], list[dict], list[dict]]:
    valid_files: list[Path] = []
    error_files: list[Path] = []
    all_rows = []
    discarded = []
    candidates: list[dict] = []
    rows_read = 0
    for path in files:
        try:
            raw_rows = read_file(path, config)
            rows_read += len(raw_rows)
            effective_config, mapping_result = _resolve_mapping_for_rows(config, raw_rows, backend_mapping=backend_mapping)
            logging.info("mapping candidate file=%s status=%s confidence=%s", path.name, mapping_result.status, mapping_result.confidence)
            if mapping_result.status != "auto_approved":
                candidates.append(_mapping_candidate_payload(path, raw_rows, mapping_result, config))
                continue
            result = normalize_rows(raw_rows, effective_config)
        except Exception as exc:
            logging.error("parse error file=%s error=%s", path.name, exc)
            error_files.append(path)
            continue
        valid_files.append(path)
        all_rows.extend(result.rows)
        for item in result.discarded:
            item["file"] = path.name
            discarded.append(item)
    if candidates:
        return None, valid_files, error_files, discarded, candidates
    if not valid_files:
        raise ValidationError("No hubo archivos válidos para enviar")
    summary = build_summary(
        all_rows,
        config,
        files_processed=len(valid_files),
        rows_read=rows_read,
        rows_discarded=len(discarded),
    )
    return summary, valid_files, error_files, discarded, candidates


def _process_reliable_file(
    *,
    config: CollectorConfig,
    client: CollectorClient,
    conn,
    path: Path,
    backend_mapping: dict[str, str] | None,
) -> tuple[str, str | None]:
    if not wait_for_stable_file(
        path,
        checks=int(config.raw.get("stable_file_checks", 2)),
        interval_seconds=float(config.raw.get("stable_file_interval_seconds", 1)),
    ):
        message = "El archivo todavia se esta copiando o exportando. Se intentara en la proxima ejecucion."
        add_event(conn, file_id=None, event_type="file_not_stable", level="warning", message=message, context={"file_name": path.name})
        return "skipped", message

    file_sha256 = compute_file_sha256(path)
    existing_path = conn.execute(
        "SELECT * FROM processed_files WHERE file_path = ? AND status IN ('pending_send', 'retrying', 'processing') ORDER BY updated_at DESC LIMIT 1",
        (str(path),),
    ).fetchone()
    if existing_path:
        row = dict(existing_path)
        add_event(
            conn,
            file_id=row["file_id"],
            event_type="pending_send_skipped",
            level="info",
            message="Archivo ya tiene payload pendiente; no se parseo nuevamente.",
            context={"file_name": path.name, "status": row.get("status")},
        )
        return "pending_send", "Archivo pendiente de envio; se reintentara desde la cola offline."
    existing = get_by_sha256(conn, file_sha256)
    if existing and existing.get("status") == "sent":
        duplicate_dir = config.path("processed_dir") / "duplicados"
        moved = _archive_file(config, path, duplicate_dir, suffix="duplicate") if _config_bool(config, "move_processed_files", True) else []
        add_event(
            conn,
            file_id=existing["file_id"],
            event_type="duplicate_skipped",
            level="info",
            message="Archivo duplicado detectado localmente; no se envio.",
            context={"file_name": path.name, "moved": moved},
        )
        return "duplicate", "Archivo duplicado detectado. No se envio nuevamente."
    if existing and existing.get("status") in {"pending_send", "retrying", "processing"}:
        add_event(
            conn,
            file_id=existing["file_id"],
            event_type="pending_send_skipped",
            level="info",
            message="Archivo ya tiene payload pendiente; no se parseo nuevamente.",
            context={"file_name": path.name, "status": existing.get("status")},
        )
        return "pending_send", "Archivo pendiente de envio; se reintentara desde la cola offline."

    file_id = existing["file_id"] if existing else build_file_id(file_sha256, path.name)
    upsert_detected_file(
        conn,
        file_id=file_id,
        commerce_id=config.commerce_id,
        collector_id=config.collector_id,
        path=path,
        file_sha256=file_sha256,
        status="processing",
    )
    add_event(conn, file_id=file_id, event_type="processing_started", level="info", message="Procesamiento iniciado.")

    try:
        raw_rows = read_file(path, config)
        effective_config, mapping_result = _resolve_mapping_for_rows(config, raw_rows, backend_mapping=backend_mapping)
        if mapping_result.status != "auto_approved":
            raise ValidationError("AIVA necesita revisar el mapeo de columnas desde el admin.")
        result = normalize_rows(raw_rows, effective_config)
        validation = validate_normalized_data(
            raw_rows=raw_rows,
            mapping=effective_config.column_mapping,
            normalized_rows=result.rows,
            discarded_rows=result.discarded,
        )
    except Exception as exc:
        message = str(exc)
        update_file_state(conn, file_id, status="error", error_message=message, processed_at=utc_now())
        add_event(conn, file_id=file_id, event_type="processing_error", level="error", message=message)
        if _config_bool(config, "move_error_files", True):
            moved = _archive_file(config, path, config.path("error_dir"), suffix="error")
            if moved:
                _write_error_note(Path(moved[0]), path, message)
        return "error", message

    normalized_hash = compute_normalized_data_hash(result.rows)
    processed_at = utc_now()
    validation_dict = validation.as_dict()
    update_file_state(
        conn,
        file_id,
        status="validated" if validation.is_valid else "error",
        normalized_data_hash=normalized_hash,
        processed_at=processed_at,
        rows_total=validation.rows_total,
        rows_valid=validation.rows_valid,
        rows_invalid=validation.rows_invalid,
        error_message="; ".join(validation.blocking_errors) if validation.blocking_errors else None,
    )
    for warning in validation.warnings:
        add_event(conn, file_id=file_id, event_type="validation_warning", level="warning", message=warning)

    if not validation.is_valid:
        message = "; ".join(validation.blocking_errors)
        add_event(conn, file_id=file_id, event_type="validation_blocked", level="error", message=message)
        if _config_bool(config, "move_error_files", True):
            moved = _archive_file(config, path, config.path("error_dir"), suffix="validation_error")
            if moved:
                _write_error_note(Path(moved[0]), path, message)
        return "error", message

    summary = build_summary(
        result.rows,
        config,
        files_processed=1,
        rows_read=len(raw_rows),
        rows_discarded=len(result.discarded),
    )
    _attach_reliability_metadata(
        summary,
        file_id=file_id,
        path=path,
        file_sha256=file_sha256,
        normalized_data_hash=normalized_hash,
        detected_at=get_file_detected_at(conn, file_id),
        processed_at=processed_at,
        validation=validation_dict,
    )
    output_path = _write_summary(config, summary)
    idem = idempotency_key(summary)
    update_file_state(conn, file_id, idempotency_key=idem)

    try:
        client.post_status("running")
        response = client.send_summary(summary)
        client.post_status("ok")
    except BackendError as exc:
        if exc.status_code == 409:
            moved = _archive_file(config, path, config.path("processed_dir") / "duplicados", suffix="duplicate") if _config_bool(config, "move_processed_files", True) else []
            update_file_state(
                conn,
                file_id,
                status="duplicate",
                sent_at=utc_now(),
                backend_response_code=409,
                error_message=str(exc),
            )
            add_event(conn, file_id=file_id, event_type="backend_duplicate", level="info", message=str(exc), context={"moved": moved})
            return "duplicate", "Backend informo summary duplicado. No se reenvio."
        update_file_state(
            conn,
            file_id,
            status="pending_send",
            backend_response_code=exc.status_code,
            error_message=str(exc),
        )
        enqueue_payload(
            conn,
            config,
            file_id=file_id,
            payload=summary,
            last_error=str(exc),
        )
        add_event(conn, file_id=file_id, event_type="pending_send", level="warning", message=str(exc))
        return "pending_send", "No se pudo conectar con AIVA. El archivo quedo pendiente y se reintentara automaticamente."

    moved = _archive_file(config, path, config.path("processed_dir")) if _config_bool(config, "move_processed_files", True) else []
    update_file_state(
        conn,
        file_id,
        status="sent",
        sent_at=utc_now(),
        backend_summary_id=response.get("summary_id") or response.get("id"),
        backend_response_code=response.get("_http_status_code", 200),
        backend_response_json=response,
    )
    add_event(conn, file_id=file_id, event_type="sent", level="info", message="Summary enviado correctamente.", context={"moved": moved})
    return "sent", "Summary enviado correctamente."


def get_file_detected_at(conn, file_id: str) -> str:
    from .local_state import get_file

    row = get_file(conn, file_id)
    return str(row.get("detected_at")) if row else utc_now()


def cmd_run_auto(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    config.require_send_ready()
    _runtime_dirs(config)
    client = CollectorClient(config)
    conn = connect_local_state(local_db_path(config))
    initial_queue = process_queue(conn, config, client=client)
    files = discover_input_files(config)
    if not files:
        logging.info("run-auto: no hay archivos CSV/XLSX en input_dir")
        conn.close()
        print(
            "Sin archivos para procesar. "
            f"cola: enviados={initial_queue.sent} pendientes_reintentando={initial_queue.retrying} errores={initial_queue.errors}"
        )
        return 0
    backend_mapping = _backend_mapping(config)
    results: list[tuple[str, str | None]] = []
    try:
        for path in files:
            status, message = _process_reliable_file(
                config=config,
                client=client,
                conn=conn,
                path=path,
                backend_mapping=backend_mapping,
            )
            results.append((status, message))
            logging.info("run-auto file=%s status=%s message=%s", path.name, status, message)
        final_queue = process_queue(conn, config, client=client, force=True)
    finally:
        conn.close()

    sent = sum(1 for status, _ in results if status == "sent") + initial_queue.sent + final_queue.sent
    duplicates = sum(1 for status, _ in results if status == "duplicate")
    pending = sum(1 for status, _ in results if status == "pending_send")
    errors = sum(1 for status, _ in results if status == "error") + initial_queue.errors + final_queue.errors
    print(f"run-auto finalizado: enviados={sent} duplicados={duplicates} pendientes={pending} errores={errors}")
    if pending:
        print("No se pudo conectar con AIVA. El archivo quedo pendiente y se reintentara automaticamente.")
    save_state(
        config,
        last_summary_file=safe_display_path(config.path("output_dir") / "last_summary.json"),
        last_idempotency_key_hash=None,
        last_status="ok" if errors == 0 else "error",
    )
    return 0 if errors == 0 else 2


def cmd_init_config(args: argparse.Namespace) -> int:
    path = init_config(args.output, overwrite=args.force)
    print(f"Config creada: {path}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    files = validate_config(config)
    token_state = "presente" if config.token else "ausente (permitido para dry-run)"
    print("Config valida")
    print(f"input_dir: {config.path('input_dir')}")
    print(f"archivos detectados: {len(files)}")
    print(f"token: {token_state}")
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    if args.send:
        config.require_send_ready()
    backend_mapping = _backend_mapping(config) if args.send else None
    summary, files, discarded = _collect(config, backend_mapping=backend_mapping)
    for item in discarded[:20]:
        logging.warning("Fila descartada file=%s row=%s reasons=%s", item.get("file"), item.get("row_number"), item.get("reasons"))
    output_path = _write_summary(config, summary)
    idem = idempotency_key(summary)

    if not args.send:
        _print_compact_summary(summary, output_path)
        db_path = local_db_path(config)
        conn = connect_local_state(db_path) if db_path.exists() else None
        try:
            for file_path in files:
                raw_rows = read_file(file_path, config)
                effective_config, mapping_result = _resolve_mapping_for_rows(config, raw_rows)
                _print_mapping_used(mapping_result)
                normalized = normalize_rows(raw_rows, effective_config) if mapping_result.status == "auto_approved" else None
                validation = (
                    validate_normalized_data(
                        raw_rows=raw_rows,
                        mapping=effective_config.column_mapping,
                        normalized_rows=normalized.rows,
                        discarded_rows=normalized.discarded,
                    )
                    if normalized
                    else None
                )
                duplicate = False
                if conn:
                    duplicate = bool(get_by_sha256(conn, compute_file_sha256(file_path)))
                print(f"archivo: {file_path.name}")
                print(f"validacion: {'OK' if validation and validation.is_valid else 'ERROR'}")
                if validation:
                    print(f"filas validas: {validation.rows_valid}")
                    print(f"filas invalidas: {validation.rows_invalid}")
                    for warning in validation.warnings:
                        print(f"warning: {warning}")
                    for error in validation.blocking_errors:
                        print(f"error bloqueante: {error}")
                print(f"duplicado local: {'si' if duplicate else 'no'}")
                print(f"se enviaria: {'no' if duplicate or not validation or not validation.is_valid else 'si'}")
        finally:
            if conn:
                conn.close()
        print("Dry-run: no se envio nada al backend.")
        save_state(
            config,
            last_summary_file=safe_display_path(output_path),
            last_idempotency_key_hash=_safe_idem_hash(idem),
            last_status="dry_run",
            processed_files=[],
        )
        return 0

    client = CollectorClient(config)
    backend_state = {
        "last_backend_commerce_id": config.commerce_id,
        "last_backend_collector_id": config.collector_id,
        "last_idempotency_key_hash": _safe_idem_hash(idem),
        "idempotency_confirmed": False,
    }
    try:
        client.post_status("running")
        response = client.send_summary(summary)
        logging.info("backend send status=%s", response.get("_http_status_code"))
        client.post_status("ok")
    except BackendError as exc:
        logging.error("Backend error: %s", exc)
        try:
            client.post_status("error", str(exc))
        except BackendError:
            pass
        backend_state.update(
            {
                "last_backend_send_at": datetime.now(timezone.utc).isoformat(),
                "last_backend_status_code": getattr(exc, "status_code", None),
                "last_backend_summary_status": "error",
            }
        )
        save_state(
            config,
            last_summary_file=safe_display_path(output_path),
            last_idempotency_key_hash=_safe_idem_hash(idem),
            last_status="error",
            backend_state=backend_state,
        )
        raise

    moved = _move_processed_if_enabled(config, files)
    backend_state.update(
        {
            "last_backend_send_at": datetime.now(timezone.utc).isoformat(),
            "last_backend_status_code": response.get("_http_status_code"),
            "last_backend_summary_status": "sent",
        }
    )
    save_state(
        config,
        last_summary_file=safe_display_path(output_path),
        last_idempotency_key_hash=_safe_idem_hash(idem),
        last_status="ok",
        processed_files=moved,
        backend_state=backend_state,
    )
    print("Summary enviado correctamente")
    if response:
        print(json.dumps(response, indent=2, ensure_ascii=True))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    args.send = True
    return cmd_run_once(args)


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    db_path = local_db_path(config)
    local = {"db_path": str(db_path), "processed_files": {}, "upload_queue": {}}
    if db_path.exists():
        conn = connect_local_state(db_path)
        try:
            local["processed_files"] = status_counts(conn)
            local["upload_queue"] = queue_counts(conn)
        finally:
            conn.close()
    response: dict = {"local_state": local}
    if config.token and config.backend_url:
        response["backend"] = CollectorClient(config).service_status()
    print(json.dumps(response, indent=2, ensure_ascii=True))
    return 0


def cmd_queue_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    db_path = local_db_path(config)
    summary = {
        "pending": 0,
        "retrying": 0,
        "sent": 0,
        "error": 0,
        "duplicate": 0,
        "processing": 0,
        "next_retry_at": None,
        "last_error": None,
        "db_path": str(db_path),
    }
    if db_path.exists():
        conn = connect_local_state(db_path)
        try:
            details = queue_summary(conn)
            counts = details["counts"]
            summary.update({status: int(counts.get(status, 0)) for status in ("pending", "retrying", "sent", "error", "duplicate", "processing")})
            summary["next_retry_at"] = details["next_retry_at"]
            summary["last_error"] = details["last_error"]
        finally:
            conn.close()
    print("AIVA Collector - Estado de cola")
    print(f"pendientes: {summary['pending']}")
    print(f"reintentando: {summary['retrying']}")
    print(f"enviados: {summary['sent']}")
    print(f"duplicados: {summary['duplicate']}")
    print(f"errores: {summary['error']}")
    print(f"proximo reintento: {summary['next_retry_at'] or '-'}")
    print(f"ultima falla: {summary['last_error'] or '-'}")
    print(f"DB local: {summary['db_path']}")
    return 0


def cmd_retry_pending(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    config.require_send_ready()
    _runtime_dirs(config)
    conn = connect_local_state(local_db_path(config))
    try:
        result = process_queue(conn, config, force=True)
    finally:
        conn.close()
    print(
        "retry-pending finalizado: "
        f"intentados={result.attempted} enviados={result.sent} duplicados={result.duplicate} "
        f"reintentando={result.retrying} errores={result.errors}"
    )
    return 0 if result.errors == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiva-collector")
    sub = parser.add_subparsers(dest="command", required=True)
    config_default = default_config_path()

    p_init = sub.add_parser("init-config")
    p_init.add_argument("--output", required=True)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init_config)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--config", default=config_default, required=config_default is None)
    p_validate.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run-once")
    p_run.add_argument("--config", default=config_default, required=config_default is None)
    p_run.add_argument("--send", action="store_true")
    p_run.set_defaults(func=cmd_run_once)

    p_send = sub.add_parser("send")
    p_send.add_argument("--config", default=config_default, required=config_default is None)
    p_send.set_defaults(func=cmd_send)

    p_activate = sub.add_parser("activate")
    p_activate.add_argument("--backend-url", default=None)
    p_activate.add_argument("--code", default=None)
    p_activate.add_argument("--config", default=WINDOWS_DEFAULT_CONFIG)
    p_activate.add_argument("--install-task", action="store_true")
    p_activate.set_defaults(func=cmd_activate)

    p_auto = sub.add_parser("run-auto")
    p_auto.add_argument("--config", default=config_default, required=config_default is None)
    p_auto.set_defaults(func=cmd_run_auto)

    p_status = sub.add_parser("status")
    p_status.add_argument("--config", default=config_default, required=config_default is None)
    p_status.set_defaults(func=cmd_status)

    p_queue_status = sub.add_parser("queue-status")
    p_queue_status.add_argument("--config", default=config_default, required=config_default is None)
    p_queue_status.set_defaults(func=cmd_queue_status)

    p_retry_pending = sub.add_parser("retry-pending")
    p_retry_pending.add_argument("--config", default=config_default, required=config_default is None)
    p_retry_pending.set_defaults(func=cmd_retry_pending)

    p_service_status = sub.add_parser("service-status")
    p_service_status.add_argument("--config", default=config_default, required=config_default is None)
    p_service_status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CollectorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
