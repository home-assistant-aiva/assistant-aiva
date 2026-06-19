from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .client import CollectorClient
from .config import PROJECT_ROOT, CollectorConfig, init_config, load_config
from .errors import BackendError, CollectorError, ValidationError
from .logging_setup import setup_logging
from .normalizer import normalize_rows
from .readers import detect_columns, discover_input_files, read_file
from .state import save_state
from .summarizer import build_summary, idempotency_key


def _safe_idem_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def validate_config(config: CollectorConfig) -> list[Path]:
    files = discover_input_files(config)
    if not files:
        raise ValidationError("No se detectaron archivos CSV/XLSX en input_dir")
    columns = detect_columns(files, config)
    mapping = config.column_mapping
    required_sources = [mapping[name] for name in ("producto_nombre", "cantidad_vendida", "precio_venta")]
    missing_columns = sorted(source for source in required_sources if source not in columns)
    if missing_columns:
        raise ValidationError("Faltan columnas requeridas en archivos: " + ", ".join(missing_columns))
    config.path("processed_dir").mkdir(parents=True, exist_ok=True)
    config.path("error_dir").mkdir(parents=True, exist_ok=True)
    config.path("output_dir").mkdir(parents=True, exist_ok=True)
    config.path("state_dir").mkdir(parents=True, exist_ok=True)
    return files


def _collect(config: CollectorConfig) -> tuple[dict, list[Path], list[dict]]:
    files = validate_config(config)
    logging.info("collector run start")
    logging.info("files detected count=%s", len(files))
    all_rows = []
    discarded = []
    rows_read = 0
    for path in files:
        raw_rows = read_file(path, config)
        rows_read += len(raw_rows)
        result = normalize_rows(raw_rows, config)
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
        moved.append(str(dest.relative_to(PROJECT_ROOT)))
    return moved


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
    summary, files, discarded = _collect(config)
    for item in discarded[:20]:
        logging.warning("Fila descartada file=%s row=%s reasons=%s", item.get("file"), item.get("row_number"), item.get("reasons"))
    output_path = _write_summary(config, summary)
    idem = idempotency_key(summary)

    if not args.send:
        _print_compact_summary(summary, output_path)
        print("Dry-run: no se envio nada al backend.")
        save_state(
            config,
            last_summary_file=str(output_path.relative_to(PROJECT_ROOT)),
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
            last_summary_file=str(output_path.relative_to(PROJECT_ROOT)),
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
        last_summary_file=str(output_path.relative_to(PROJECT_ROOT)),
        last_idempotency_key_hash=_safe_idem_hash(idem),
        last_status="ok",
        processed_files=moved,
        backend_state=backend_state,
    )
    print("Summary enviado correctamente")
    if response:
        print(json.dumps(response, indent=2, ensure_ascii=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config)
    config.require_send_ready()
    response = CollectorClient(config).service_status()
    print(json.dumps(response, indent=2, ensure_ascii=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m aiva_collector.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-config")
    p_init.add_argument("--output", required=True)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init_config)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--config", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run-once")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--send", action="store_true")
    p_run.set_defaults(func=cmd_run_once)

    p_status = sub.add_parser("status")
    p_status.add_argument("--config", required=True)
    p_status.set_defaults(func=cmd_status)
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
