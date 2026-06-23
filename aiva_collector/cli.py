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
from .logging_setup import setup_logging
from .normalizer import normalize_rows
from .readers import detect_columns, discover_input_files, read_file
from .state import save_state
from .summarizer import build_summary, idempotency_key
from .token_store import save_token


WINDOWS_DEFAULT_CONFIG = r"C:\AIVA_Comercio\config.local.json"
DEFAULT_BACKEND_URL = "http://187.77.44.118:8080"
DEFAULT_COLLECTOR_VERSION = "0.2.2"


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


def cmd_run_auto(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    config.require_send_ready()
    for key in ("processed_dir", "error_dir", "output_dir", "state_dir"):
        config.path(key).mkdir(parents=True, exist_ok=True)
    files = discover_input_files(config)
    if not files:
        logging.info("run-auto: no hay archivos CSV/XLSX en input_dir")
        print("Sin archivos para procesar.")
        return 0
    client = CollectorClient(config)
    backend_mapping = _backend_mapping(config)
    summary, valid_files, error_files, discarded, candidates = _collect_auto(config, files, backend_mapping=backend_mapping)
    if candidates:
        for candidate in candidates:
            try:
                client.post_mapping_candidate(candidate)
            except BackendError as exc:
                logging.error("No se pudo enviar mapping candidate; archivo queda en entrada: %s", exc)
                print("AIVA necesita revisar el mapeo de columnas desde el admin. No se envió summary.")
                return 2
        message = "AIVA necesita revisar el mapeo de columnas desde el admin."
        logging.warning(message)
        try:
            client.post_status("error", message)
        except BackendError:
            pass
        print(f"{message} No se envió summary.")
        return 2
    assert summary is not None
    for item in discarded[:20]:
        logging.warning("Fila descartada file=%s row=%s reasons=%s", item.get("file"), item.get("row_number"), item.get("reasons"))
    if error_files:
        moved_errors = _move_files(error_files, config.path("error_dir"), suffix="parse_error")
        logging.info("run-auto parse errors moved=%s", moved_errors)
    output_path = _write_summary(config, summary)
    idem = idempotency_key(summary)
    backend_state = {
        "last_backend_commerce_id": config.commerce_id,
        "last_backend_collector_id": config.collector_id,
        "last_idempotency_key_hash": _safe_idem_hash(idem),
    }
    try:
        client.post_status("running")
        response = client.send_summary(summary)
        client.post_status("ok")
        moved = _move_files(valid_files, config.path("processed_dir")) if bool(config.raw.get("move_processed_files", True)) else []
        backend_state.update(
            {
                "last_backend_send_at": datetime.now(timezone.utc).isoformat(),
                "last_backend_status_code": response.get("_http_status_code"),
                "last_backend_summary_status": "sent",
            }
        )
        save_state(config, last_summary_file=safe_display_path(output_path), last_idempotency_key_hash=_safe_idem_hash(idem), last_status="ok", processed_files=moved, backend_state=backend_state)
        print("run-auto OK")
        return 0
    except BackendError as exc:
        if exc.status_code == 409:
            moved = _move_files(valid_files, config.path("processed_dir"), suffix="duplicate") if bool(config.raw.get("move_processed_files", True)) else []
            backend_state.update(
                {
                    "last_backend_send_at": datetime.now(timezone.utc).isoformat(),
                    "last_backend_status_code": 409,
                    "last_backend_summary_status": "duplicate",
                }
            )
            save_state(config, last_summary_file=safe_display_path(output_path), last_idempotency_key_hash=_safe_idem_hash(idem), last_status="duplicate", processed_files=moved, backend_state=backend_state)
            print("run-auto duplicate_summary")
            return 0
        logging.error("run-auto backend error; archivos quedan en entrada: %s", exc)
        save_state(config, last_summary_file=safe_display_path(output_path), last_idempotency_key_hash=_safe_idem_hash(idem), last_status="error", backend_state={**backend_state, "last_backend_status_code": exc.status_code})
        return 2


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
        raw_rows = read_file(files[0], config) if files else []
        _, mapping_result = _resolve_mapping_for_rows(config, raw_rows)
        _print_mapping_used(mapping_result)
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
    config.require_send_ready()
    response = CollectorClient(config).service_status()
    print(json.dumps(response, indent=2, ensure_ascii=True))
    return 0


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
