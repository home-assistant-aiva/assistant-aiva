"""One-use, demo-commerce daily-v2 handoff for an already installed RC7 Collector.

No release installation, activation, message delivery, or automatic retries occur here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .cli import (
    _backend_mapping, _backend_target, _process_reliable_file,
    _resolve_mapping_for_rows, cmd_configure_daily_source,
)
from .client import CollectorClient
from .config import CollectorConfig, load_config
from .local_state import connect, get_by_sha256, local_db_path, queue_counts
from .normalizer import normalize_rows
from .readers import read_file
from .summarizer import build_summary
from .validation import validate_normalized_data
from .version import VERSION

COMMERCE = "commerce_a0e93d3ec7ac"
COLLECTOR = "collector_dc15555b7052"
SOURCE_SHA = "2a173badfd6bad847af779d89b947139110af3a3d0108601edb05a96e53f2cd3"
SOURCE_ZIP_SHA = "5b258b2edf6745c6149aef4a4c9ecb7dc061522ad5c15e8378a2c235302e37ef"
CLI_SHA = "edaf6f67b9cf01f2173db4127120591bbdcf07f3876373bde990d62a53904d9e"
SOURCE_NAME = "Ventas_demo_completas_35d_2026-08-25_a_2026-09-28.xlsx"
SOURCE_ID = "aiva_demo_synthetic_20260929_complete"
TASK = "AIVA Collector Auto"


class PilotStop(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise PilotStop(reason)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths() -> tuple[Path, Path, Path]:
    root = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AIVA" / "Collector"
    installed = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "AIVA Collector"
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "aiva-demo-daily-v2-source-20260929.zip"
    return root, installed, bundle


def _powershell(command: str, *, failure: str = "No se pudo inspeccionar la tarea programada.") -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=90, check=False,
    )
    require(result.returncode == 0, failure)
    return result.stdout.strip()


def _task_disabled() -> bool:
    state = _powershell("(Get-ScheduledTask -TaskName 'AIVA Collector Auto' -ErrorAction Stop).State")
    return state == "Disabled"


def _task_xml(path: Path) -> None:
    # The task XML is kept only in the protected local backup.
    xml = _powershell("Export-ScheduledTask -TaskName 'AIVA Collector Auto' -ErrorAction Stop")
    require("<Task" in xml, "No se pudo exportar la definición de la tarea.")
    path.write_text(xml, encoding="utf-8")


def verify_installed_rc7(cli: Path) -> None:
    require(cli.is_file() and sha256(cli) == CLI_SHA, "La instalación efectiva no coincide con RC7 verificado.")
    version = subprocess.run([str(cli), "--version"], capture_output=True, text=True, timeout=30)
    require(version.returncode == 0 and "0.2.7rc7" in version.stdout and VERSION == "0.2.7rc7", "Versión RC7 incorrecta.")


def _active_processes() -> set[str]:
    result = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, "No se pudieron inspeccionar los procesos Windows.")
    watched = {"aiva-collector.exe", "aiva-collector-cli.exe", "aiva-collector-background.exe"}
    return {row[0].lower() for row in csv.reader(io.StringIO(result.stdout)) if row and row[0].lower() in watched}


def _stop_gui_and_wait() -> None:
    _powershell("[System.Diagnostics.Process]::GetProcessesByName('aiva-collector') | ForEach-Object { [void]$_.CloseMainWindow() }", failure="No se pudo cerrar la interfaz del Collector.")
    for _ in range(90):
        if not _active_processes():
            return
        time.sleep(2)
    raise PilotStop("Sigue activo un proceso del Collector. La tarea continúa deshabilitada; no se envió nada.")


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _check_root_paths(config: CollectorConfig, root: Path) -> None:
    for key in ("input_dir", "state_dir", "output_dir", "processed_dir", "error_dir", "queue_dir", "mappings_dir", "log_file"):
        if config.raw.get(key):
            require(_under_root(config.path(key), root), f"La ruta {key} está fuera del respaldo previsto.")
    require(local_db_path(config).is_file(), "Falta la base SQLite local del Collector.")


def _sqlite_integrity(path: Path) -> None:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        require(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite restaurado no pasa integrity_check.")
    finally:
        con.close()


def backup_and_restore(root: Path, config: CollectorConfig) -> tuple[Path, int]:
    """Copy all persistent files, using SQLite's online backup API for the DB."""
    require(_task_disabled(), "La tarea programada debe permanecer Disabled.")
    _check_root_paths(config, root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = root.parent / f"Collector-backup-RC7-pilot-{stamp}"
    backup.mkdir(mode=0o700)
    db = local_db_path(config)
    exclude = {db.name, db.name + "-wal", db.name + "-shm"}
    copied = 0
    for src in root.rglob("*"):
        if not src.is_file():
            continue
        require(not src.is_symlink(), "Hay un enlace simbólico en ProgramData; detener para revisar respaldo.")
        rel = src.relative_to(root)
        if src.parent == db.parent and src.name in exclude:
            continue
        dst = backup / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        require(sha256(src) == sha256(dst), "No coincide una copia del respaldo.")
        copied += 1
    db_copy = backup / db.relative_to(root)
    db_copy.parent.mkdir(parents=True, exist_ok=True)
    src_con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    dst_con = sqlite3.connect(db_copy)
    try:
        src_con.backup(dst_con)
    finally:
        dst_con.close()
        src_con.close()
    _sqlite_integrity(db_copy)
    _task_xml(backup / "task-AIVA-Collector-Auto.xml")
    with TemporaryDirectory(prefix="aiva-rc7-restore-") as temp:
        restored = Path(temp) / "Collector"
        shutil.copytree(backup, restored)
        for src in backup.rglob("*"):
            if src.is_file():
                require(sha256(src) == sha256(restored / src.relative_to(backup)), "Falló la prueba de restauración.")
        _sqlite_integrity(restored / db.relative_to(root))
    require(_task_disabled(), "La tarea cambió durante el respaldo.")
    return backup, copied + 2


def _extract_verified(bundle: Path, dest: Path) -> tuple[Path, Path]:
    require(bundle.is_file() and sha256(bundle) == SOURCE_ZIP_SHA, "SHA incorrecto del ZIP sintético incluido en el EXE.")
    with zipfile.ZipFile(bundle) as archive:
        require(set(archive.namelist()) == {SOURCE_NAME, "manifest.json", "generator.py"}, "Contenido inesperado en el ZIP sintético.")
        for name in archive.namelist():
            target = dest / name
            target.write_bytes(archive.read(name))
    source = dest / SOURCE_NAME
    manifest = dest / "manifest.json"
    require(sha256(source) == SOURCE_SHA, "SHA incorrecto del Excel sintético.")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    require(data.get("sha256") == SOURCE_SHA and data.get("source_id") == SOURCE_ID, "Manifiesto sintético no coincide.")
    require(data.get("complete_by_construction") is True and data.get("synthetic") is True, "Completitud de fuente no demostrada.")
    require(sha256(dest / "generator.py") == data.get("generator_sha256"), "Generador no coincide con manifiesto.")
    return source, manifest


def _check_existing_state(config: CollectorConfig) -> str:
    con = sqlite3.connect(f"file:{local_db_path(config).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        q = {str(row[0]): int(row[1]) for row in con.execute("SELECT status, COUNT(*) FROM upload_queue GROUP BY status")}
        require(not any(q.get(s, 0) for s in ("pending", "retrying", "processing")), "Hay una cola pendiente; se detuvo para no reenviar payloads anteriores.")
        columns = {row[1] for row in con.execute("PRAGMA table_info(processed_files)")}
        schema_expr = "COALESCE(source_schema_version,'1.0.0')" if "source_schema_version" in columns else "'1.0.0'"
        rows = con.execute(
            f"SELECT status, {schema_expr} AS schema FROM processed_files "
            "WHERE file_sha256=? AND commerce_id=? AND collector_id=? ORDER BY updated_at DESC",
            (SOURCE_SHA, COMMERCE, COLLECTOR),
        ).fetchall()
        if rows:
            require(len(rows) == 1 and rows[0]["status"] == "sent" and rows[0]["schema"] == "2.0.0", "El SHA sintético ya tiene un estado local distinto de v2 sent; revisar sin reintentar.")
            return "already_sent"
        return "new"
    finally:
        con.close()


def _precheck(config: CollectorConfig, source: Path, backend_mapping: dict[str, str] | None = None) -> dict:
    require(config.raw.get("source_schema_version") == "2.0.0", "La configuración no es daily v2.")
    require(config.raw.get("daily_complete_file_sha256") == SOURCE_SHA, "Completitud no acotada al SHA previsto.")
    require(config.raw.get("daily_snapshot_complete") is True, "No está declarada la completitud verificada.")
    require(config.raw.get("business_timezone") == "America/Argentina/Buenos_Aires", "Zona horaria inesperada.")
    require(config.raw.get("price_semantics") == "final_net", "Semántica de precios inesperada.")
    require(config.path("input_dir") == source.parent and sha256(source) == SOURCE_SHA, "Fuente configurada distinta de la fuente verificada.")
    supported = [p for p in source.parent.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"}]
    require(supported == [source], "La carpeta piloto contiene otra fuente procesable.")
    raw = read_file(source, config)
    effective, mapping = _resolve_mapping_for_rows(config, raw, backend_mapping=backend_mapping)
    require(mapping.status == "auto_approved" and mapping.mapping.get("producto_codigo") == "Código", "El mapping efectivo no usa Código → producto_codigo.")
    require("fecha" in mapping.mapping, "El mapping efectivo no incluye fecha.")
    normalized = normalize_rows(raw, effective)
    validation = validate_normalized_data(raw_rows=raw, mapping=effective.column_mapping, normalized_rows=normalized.rows, discarded_rows=normalized.discarded)
    require(validation.is_valid and not normalized.discarded and len(normalized.rows) == 105, "Filas daily v2 inválidas o incompletas.")
    effective = CollectorConfig({**effective.raw, "_active_file_sha256": SOURCE_SHA}, effective.config_path)
    payload = build_summary(normalized.rows, effective, files_processed=1, rows_read=len(raw), rows_discarded=0)
    snap = payload.get("daily_snapshot") or {}
    metrics = snap.get("metrics") or []
    coverage = snap.get("coverage") or []
    require(payload.get("source_schema_version") == "2.0.0" and snap.get("completeness_declared") is True, "El payload previsto no declara v2 completo.")
    require(snap.get("source_id") == SOURCE_ID and snap.get("timezone") == "America/Argentina/Buenos_Aires" and snap.get("price_semantics") == "final_net", "Fuente/semántica del payload incorrecta.")
    days = {(date(2026, 8, 25) + timedelta(days=n)).isoformat() for n in range(35)}
    codes = {"DEMO-SYN-A", "DEMO-SYN-B", "DEMO-SYN-C"}
    require(len(metrics) == 105 and {(m["business_date"], m["product_code"]) for m in metrics} == {(d, c) for d in days for c in codes}, "El payload no cubre exactamente 35 días × 3 productos.")
    require(len(coverage) == 35 and {c["business_date"] for c in coverage} == days and all(c["status"] == "complete" for c in coverage), "Cobertura daily incompleta.")
    require(all(Decimal(m["discount_amount"]) == 0 for m in metrics), "Descuento inesperado.")
    require(sum(Decimal(m["quantity"]) == 0 for m in metrics) == 24, "Faltan observaciones de venta cero explícita.")
    week = [m for m in metrics if "2026-09-22" <= m["business_date"] <= "2026-09-28"]
    revenue = sum((Decimal(m["net_revenue"]) for m in week), Decimal(0))
    cogs = sum((Decimal(m["cogs"]) for m in week), Decimal(0))
    units = sum((Decimal(m["quantity"]) for m in week), Decimal(0))
    require((revenue, cogs, units) == (Decimal("736.50"), Decimal("303.00"), Decimal("51")), "Totales del payload distintos del manifiesto.")
    return {"schema": "2.0.0", "complete": True, "metrics": 105, "coverage_days": 35, "week_revenue": str(revenue), "week_cogs": str(cogs), "week_units": str(units), "mapping_code": mapping.mapping["producto_codigo"]}


def _send_once(config: CollectorConfig, source: Path, backend_mapping: dict[str, str] | None = None) -> tuple[str, str | None]:
    require(_task_disabled(), "La tarea se reactivó antes de la sincronización.")
    lock = config.path("state_dir") / "aiva_collector.lock"
    require(not lock.exists(), "Hay un bloqueo de sincronización; no se enviará.")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}).encode())
        con = connect(local_db_path(config))
        try:
            require(not any(queue_counts(con).get(s, 0) for s in ("pending", "retrying", "processing")), "La cola cambió antes del envío.")
            existing = get_by_sha256(con, SOURCE_SHA, commerce_id=COMMERCE, collector_id=COLLECTOR, backend_url=_backend_target(config))
            require(existing is None, "El archivo ya figura en estado local; no se reenvía.")
            result, message = _process_reliable_file(config=config, client=CollectorClient(config), conn=con, path=source, backend_mapping=backend_mapping, expected_sha256=SOURCE_SHA)
            return result, message
        finally:
            con.close()
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _deliver_report(path: Path) -> bool:
    tailscale = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    if not tailscale.is_file():
        return False
    try:
        result = subprocess.run([str(tailscale), "file", "cp", str(path), "srv1382697:"], capture_output=True, timeout=90)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run() -> int:
    root, installed, bundle = _paths()
    report = {"pilot": "AIVA RC7 demo daily v2", "commerce_id": COMMERCE, "collector_id": COLLECTOR,
              "source_sha256": SOURCE_SHA, "synced": False, "backup_verified": False}
    report_path = root.parent / ("aiva-rc7-pilot-result-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".json")
    backup = None
    original_config = None
    send_attempted = False
    try:
        require(os.name == "nt", "Este complemento sólo funciona en Windows.")
        import ctypes
        require(bool(ctypes.windll.shell32.IsUserAnAdmin()), "Abrí el complemento con privilegios de administrador.")
        require(_task_disabled(), "La tarea AIVA Collector Auto no está Disabled.")
        cli = installed / "aiva-collector-cli.exe"
        verify_installed_rc7(cli)
        report["installed_version"] = "0.2.7rc7"
        print("RC7 instalado y hash del CLI verificados.")
        config_path = root / "config.windows.json"
        config = load_config(config_path)
        require((config.commerce_id, config.collector_id) == (COMMERCE, COLLECTOR), "Identidad del Collector/comercio incorrecta.")
        config.require_send_ready()
        remote = CollectorClient(config).service_status()
        require(remote.get("ok") is True and remote.get("commerce_id") == COMMERCE and remote.get("collector_id") == COLLECTOR and remote.get("accepts_summaries") is True, "Backend no confirma este Collector activo para el comercio demo.")
        report["backend_identity_confirmed"] = True
        _check_root_paths(config, root)
        _stop_gui_and_wait()
        print("Tarea detenida; no hay procesos ni sincronización activa.")
        require(not (config.path("state_dir") / "aiva_collector.lock").exists(), "Hay una sincronización activa o bloqueo local.")
        with TemporaryDirectory(prefix="aiva-rc7-source-check-") as temp:
            source_tmp, manifest_tmp = _extract_verified(bundle, Path(temp))
            report["source_bundle_sha256"] = SOURCE_ZIP_SHA
            report["input_before"] = [{"sha256": sha256(p)} for p in config.path("input_dir").iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"}]
            state = _check_existing_state(config)
            backup, count = backup_and_restore(root, config)
            print("Backup y restauración de prueba verificados.")
            report.update({"backup_verified": True, "backup_path": str(backup), "backup_files": count, "restore_test": "ok", "task_disabled": True, "task_xml_sha256": sha256(backup / "task-AIVA-Collector-Auto.xml")})
            if state == "already_sent":
                report["result"] = "already_sent_v2"
                return 0
            pilot_dir = root / "pilot_rc7_daily_v2"
            pilot_dir.mkdir(exist_ok=True)
            for name in (SOURCE_NAME, "manifest.json", "generator.py"):
                destination = pilot_dir / name
                expected = sha256(Path(temp) / name)
                require(not destination.exists() or sha256(destination) == expected, "Hay un archivo piloto previo distinto; no se sobrescribe.")
                if not destination.exists():
                    temporary = pilot_dir / (name + ".part")
                    shutil.copy2(Path(temp) / name, temporary)
                    require(sha256(temporary) == expected, "Falló la copia de fuente piloto.")
                    temporary.replace(destination)
                require(sha256(destination) == expected, "Falló la copia de fuente piloto.")
            source = pilot_dir / SOURCE_NAME
            original_config = config_path.read_bytes()
            options = argparse.Namespace(config=str(config_path), file=str(source), manifest=str(pilot_dir / "manifest.json"),
                expected_sha256=SOURCE_SHA, expected_commerce_id=COMMERCE, expected_collector_id=COLLECTOR,
                source_id=SOURCE_ID, timezone="America/Argentina/Buenos_Aires")
            require(cmd_configure_daily_source(options) == 0, "No se pudo configurar la fuente sintética.")
            configured = load_config(config_path)
            backend_mapping = _backend_mapping(configured)
            report["precheck"] = _precheck(configured, source, backend_mapping)
            print("Precheck: payload 2.0.0, 105 métricas, 35/35 días completos; 22–28/09: ventas 736,50, costo 303,00, 51 unidades.")
            require(_check_existing_state(configured) == "new", "El estado cambió antes del envío.")
            send_attempted = True
            result, message = _send_once(configured, source, backend_mapping)
            print("Sincronización única finalizada:", result)
            report["send_result"] = result
            report["synced"] = result == "sent"
            report["result"] = "sent" if result == "sent" else "requires_backend_review"
            require(result == "sent", message or "La sincronización no terminó como sent.")
            con = sqlite3.connect(f"file:{local_db_path(configured).as_posix()}?mode=ro", uri=True)
            try:
                row = con.execute("SELECT status,source_schema_version,backend_summary_id,backend_response_code FROM processed_files WHERE file_sha256=? AND commerce_id=? AND collector_id=? ORDER BY updated_at DESC LIMIT 1", (SOURCE_SHA, COMMERCE, COLLECTOR)).fetchone()
                require(row and row[0] == "sent" and row[1] == "2.0.0" and row[2] and row[3] in (200, 201), "La respuesta local de Backend no confirma v2 sent.")
                report["backend_summary_id"] = row[2]
                report["backend_response_code"] = row[3]
            finally:
                con.close()
            return 0
    except Exception as exc:
        report["result"] = "stopped"
        reason = str(exc) if isinstance(exc, PilotStop) else (type(exc).__name__ + ": " + str(exc))
        if "config" in locals() and config.token:
            reason = reason.replace(config.token, "[redacted]")
        report["error"] = reason[:300]
        if original_config is not None and not send_attempted:
            try:
                temp_config = root / "config.windows.json.pilot-rollback"
                temp_config.write_bytes(original_config)
                temp_config.replace(root / "config.windows.json")
                report["config_rolled_back"] = True
            except OSError:
                report["config_rolled_back"] = False
        print("Piloto detenido:", report["error"])
        return 2
    finally:
        report["backup_path"] = str(backup) if backup else None
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        delivered = _deliver_report(report_path)
        print("Diagnóstico saneado:", report_path)
        print("Enviado al VPS por Tailscale:" if delivered else "No llegó por Tailscale; diagnóstico conservado localmente.", delivered)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        root, installed, bundle = _paths()
        print(json.dumps({"version": VERSION, "bundle_sha256": sha256(bundle) if bundle.exists() else None, "source_sha256": SOURCE_SHA}))
        return 0 if bundle.exists() and sha256(bundle) == SOURCE_ZIP_SHA else 2
    if os.name == "nt":
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, "", None, 1)
            return 0 if result > 32 else 2
    code = run()
    if getattr(sys, "frozen", False):
        try:
            input("Presioná Enter para cerrar esta ventana...")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
