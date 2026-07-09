from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import CollectorClient
from .config import CollectorConfig
from .errors import BackendError
from .local_state import connect as connect_local_state, local_db_path
from .offline_queue import enqueue_payload, is_temporary_backend_error


DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}
TEXT_REPORT_EXTENSIONS = {".txt"}
DATABASE_EXTENSIONS = {".db": "sqlite", ".sqlite": "sqlite", ".sqlite3": "sqlite", ".mdb": "access", ".accdb": "access", ".fdb": "firebird", ".gdb": "firebird"}
POSITIVE_SIGNALS = {
    "venta",
    "ventas",
    "sales",
    "stock",
    "inventario",
    "inventory",
    "producto",
    "productos",
    "articulo",
    "articulos",
    "artículos",
    "prices",
    "precios",
    "costo",
    "costos",
    "proveedores",
    "clientes",
    "reportes",
    "reporte",
    "cierre",
    "movimientos",
    "detalle",
    "comprobantes",
    "aiva",
    "sistema",
}
NEGATIVE_SIGNALS = {
    "password",
    "contraseñas",
    "contrasenas",
    "backup_personal",
    "dni",
    "sueldos",
    "recibo",
    "banco",
    "bank",
    "tarjeta",
    "fotos",
    "images",
    "chrome",
    "firefox",
    "whatsapp",
    "telegram",
    "private",
    "personal",
}
EXCLUDED_PARTS = {
    "$recycle.bin",
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "system volume information",
}
EXCLUDED_SUFFIXES = (
    "\\windows",
    "\\windows\\system32",
    "\\appdata\\local\\google",
    "\\appdata\\local\\microsoft",
    "\\appdata\\roaming\\mozilla",
    "\\appdata\\local\\temp",
)


@dataclass(frozen=True)
class DiscoveryConfig:
    enabled: bool = True
    max_depth: int = 3
    max_files_per_dir: int = 50
    max_total_candidates: int = 100
    max_report_candidates: int = 20
    include_user_dirs: bool = True
    include_program_dirs: bool = True
    include_drive_roots: bool = False
    timeout_seconds: int = 30
    safe_mode: bool = True
    dry_run: bool = False
    include_paths: tuple[Path, ...] = ()
    min_confidence: float = 0.25

    @classmethod
    def from_collector_config(
        cls,
        config: CollectorConfig,
        *,
        dry_run: bool = False,
        safe_mode: bool | None = None,
        max_total_candidates: int | None = None,
        timeout_seconds: int | None = None,
        include_paths: list[str] | None = None,
    ) -> "DiscoveryConfig":
        raw = config.raw
        discovery_raw = raw.get("discovery") if isinstance(raw.get("discovery"), dict) else {}

        def value(name: str, default: Any) -> Any:
            flat_name = f"discovery_{name}"
            if flat_name in raw:
                return raw[flat_name]
            return discovery_raw.get(name, default)

        paths = tuple(Path(item) for item in (include_paths or value("include_paths", []) or []))
        return cls(
            enabled=bool(value("enabled", True)),
            max_depth=int(value("max_depth", 3)),
            max_files_per_dir=int(value("max_files_per_dir", 50)),
            max_total_candidates=int(max_total_candidates if max_total_candidates is not None else value("max_total_candidates", 100)),
            max_report_candidates=int(value("max_report_candidates", 20)),
            include_user_dirs=bool(value("include_user_dirs", True)),
            include_program_dirs=bool(value("include_program_dirs", True)),
            include_drive_roots=bool(value("include_drive_roots", False)),
            timeout_seconds=int(timeout_seconds if timeout_seconds is not None else value("timeout_seconds", 30)),
            safe_mode=bool(safe_mode if safe_mode is not None else value("safe_mode", True)),
            dry_run=dry_run,
            include_paths=paths,
            min_confidence=float(value("min_confidence", 0.25)),
        )


@dataclass
class DiscoveryCandidate:
    source_type: str
    name: str
    confidence: float
    detected_path: str | None = None
    detected_host: str | None = None
    detected_engine: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    sample_metadata: dict[str, Any] = field(default_factory=dict)
    raw_discovery: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryReportResult:
    attempted: int = 0
    sent: int = 0
    duplicate: int = 0
    queued: int = 0
    errors: int = 0


def _utc_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _norm_text(value: str) -> str:
    return value.lower().replace("\\", "/")


def _has_signal(name: str, signals: set[str]) -> bool:
    lowered = name.lower()
    return any(signal in lowered for signal in signals)


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _is_hidden_or_system(path: Path) -> bool:
    name = path.name
    return name.startswith(".") or name.lower() in EXCLUDED_PARTS


def _is_excluded(path: Path) -> bool:
    lowered = str(path).lower().replace("/", "\\")
    parts = {part.lower() for part in path.parts}
    return bool(parts & EXCLUDED_PARTS) or any(lowered.endswith(suffix) or f"{suffix}\\" in lowered for suffix in EXCLUDED_SUFFIXES)


def _redact_user_path(path_value: str) -> str:
    home = str(Path.home())
    if home and path_value.startswith(home):
        return path_value.replace(home, "%USERPROFILE%", 1)
    return path_value


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"token", "authorization", "password", "secret"} or lowered.endswith("_token"):
                continue
            clean[str(key)] = _safe_json(child)
        return clean
    if isinstance(value, list):
        return [_safe_json(item) for item in value[:20]]
    if isinstance(value, Path):
        return _redact_user_path(str(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class DiscoveryScanner:
    def __init__(self, config: DiscoveryConfig | None = None) -> None:
        self.config = config or DiscoveryConfig()
        self._started = 0.0

    def scan(self) -> list[DiscoveryCandidate]:
        if not self.config.enabled:
            return []
        self._started = time.monotonic()
        candidates: list[DiscoveryCandidate] = []
        roots = self._scan_roots()
        for root in roots:
            if self._timed_out() or len(candidates) >= self.config.max_total_candidates:
                break
            candidates.extend(self.scan_common_folders(root))
        if not self._timed_out():
            candidates.extend(self.scan_database_services())
        candidates = self.deduplicate_candidates(candidates)
        candidates = [self.sanitize_candidate(candidate) for candidate in candidates if candidate.confidence >= self.config.min_confidence]
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[: self.config.max_total_candidates]

    def _timed_out(self) -> bool:
        return bool(self.config.timeout_seconds and time.monotonic() - self._started > self.config.timeout_seconds)

    def _scan_roots(self) -> list[Path]:
        roots: list[Path] = list(self.config.include_paths)
        if self.config.include_user_dirs:
            home = Path.home()
            roots.extend([home / "Desktop", home / "Documents", home / "Downloads"])
        common = [
            r"C:\AIVA",
            r"C:\AIVA\Comercial",
            r"C:\AIVA\Comercial\Entrada",
            r"C:\Sistema",
            r"C:\Sistemas",
            r"C:\Gestion",
            r"C:\Gestión",
            r"C:\Ventas",
            r"C:\Reportes",
            r"C:\Reportes\Ventas",
            r"C:\Datos",
            r"C:\Data",
            r"C:\Backups",
        ]
        if self.config.include_program_dirs:
            common.extend([r"C:\Program Files", r"C:\Program Files (x86)"])
        if self.config.include_drive_roots:
            common.append(r"C:\\")
        roots.extend(Path(item) for item in common)
        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root).lower()
            if key in seen or _is_excluded(root) or not root.exists():
                continue
            seen.add(key)
            deduped.append(root)
        return deduped

    def scan_common_folders(self, root: Path) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        root_depth = len(root.parts)
        for directory, dirnames, filenames in os.walk(root):
            current = Path(directory)
            if self._timed_out() or len(candidates) >= self.config.max_total_candidates:
                break
            if _is_excluded(current) or _is_hidden_or_system(current):
                dirnames[:] = []
                continue
            depth = len(current.parts) - root_depth
            if depth >= self.config.max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [name for name in dirnames if not _is_hidden_or_system(current / name) and not _is_excluded(current / name)]
            limited_files = [current / name for name in filenames[: self.config.max_files_per_dir]]
            candidates.extend(self.scan_candidate_files(current, limited_files))
        return candidates

    def scan_candidate_files(self, folder: Path, files: list[Path]) -> list[DiscoveryCandidate]:
        data_files: list[dict[str, Any]] = []
        database_candidates: list[DiscoveryCandidate] = []
        for path in files:
            if _is_excluded(path) or _is_hidden_or_system(path):
                continue
            suffix = path.suffix.lower()
            if self._negative_file(path):
                continue
            if suffix in DATA_EXTENSIONS or (suffix in TEXT_REPORT_EXTENSIONS and _has_signal(path.name, POSITIVE_SIGNALS)):
                metadata = self._file_metadata(path)
                if metadata:
                    data_files.append(metadata)
            elif suffix in DATABASE_EXTENSIONS:
                candidate = self._database_candidate(path, suffix)
                if candidate:
                    database_candidates.append(candidate)
        folder_candidate = self._folder_candidate(folder, data_files) if data_files or _has_signal(folder.name, POSITIVE_SIGNALS) else None
        result = [folder_candidate] if folder_candidate else []
        result.extend(database_candidates)
        return result

    def scan_local_database_files(self, folder: Path, files: list[Path]) -> list[DiscoveryCandidate]:
        return [candidate for path in files if (candidate := self._database_candidate(path, path.suffix.lower()))]

    def scan_database_services(self) -> list[DiscoveryCandidate]:
        if platform.system().lower() != "windows":
            logging.info("service discovery unavailable on this OS")
            return []
        try:
            result = subprocess.run(["sc", "query", "state=", "all"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            logging.info("service discovery unavailable: %s", exc)
            return []
        text = result.stdout.lower()
        candidates: list[DiscoveryCandidate] = []
        service_map = [
            ("sqlserver", "localhost\\SQLEXPRESS" if "sqlexpress" in text else "localhost", ("mssql", "sql server", "sqlexpress")),
            ("mysql", "localhost", ("mysql", "mysqld")),
            ("postgresql", "localhost", ("postgresql", "postgres")),
            ("firebird", "localhost", ("firebird",)),
        ]
        for engine, host, signals in service_map:
            if any(signal in text for signal in signals):
                candidates.append(
                    DiscoveryCandidate(
                        source_type="database",
                        name=f"Servicio {engine} detectado",
                        detected_host=host,
                        detected_engine=engine,
                        confidence=0.65 if engine != "sqlserver" else 0.7,
                        capabilities={"database_service": True, "connection_requires_credentials": True, "read_supported_future": True},
                        sample_metadata={"service_detected": True, "connection_not_attempted": True},
                        raw_discovery={"method": "windows_services", "engine": engine, "host": host},
                    )
                )
        return candidates

    def _negative_file(self, path: Path) -> bool:
        text = f"{path.name} {path.parent.name}".lower()
        return _has_signal(text, NEGATIVE_SIGNALS)

    def _file_metadata(self, path: Path) -> dict[str, Any] | None:
        stat = _safe_stat(path)
        if not stat:
            return None
        return {
            "name": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "modified_at": _utc_from_timestamp(stat.st_mtime),
            "path": path,
            "positive_signal": _has_signal(path.name, POSITIVE_SIGNALS),
        }

    def _folder_candidate(self, folder: Path, files: list[dict[str, Any]]) -> DiscoveryCandidate | None:
        extensions = {str(item["extension"]) for item in files}
        recent_cutoff = time.time() - 90 * 24 * 3600
        recent_count = sum(1 for item in files if _safe_stat(Path(item["path"])) and _safe_stat(Path(item["path"])).st_mtime >= recent_cutoff)
        examples = [str(item["name"]) for item in files[:5]]
        capabilities = {
            "files": True,
            "csv": ".csv" in extensions,
            "xlsx": bool({".xlsx", ".xls"} & extensions),
            "databases": any(ext in DATABASE_EXTENSIONS for ext in extensions),
            "recent_files": recent_count,
        }
        sample_metadata = {"files_found": len(files), "examples": examples}
        confidence = self.score_candidate(folder=folder, files=files)
        if confidence < self.config.min_confidence:
            return None
        name = "Reportes detectados" if files else f"Carpeta candidata {folder.name}"
        return DiscoveryCandidate(
            source_type="watched_folder",
            name=name,
            detected_path=str(folder),
            confidence=confidence,
            capabilities=capabilities,
            sample_metadata=sample_metadata,
            raw_discovery={"folder": folder, "files_found": len(files), "examples": examples},
        )

    def _database_candidate(self, path: Path, suffix: str) -> DiscoveryCandidate | None:
        engine = DATABASE_EXTENSIONS.get(suffix)
        stat = _safe_stat(path)
        if not engine or not stat or self._negative_file(path):
            return None
        confidence = 0.7 if _has_signal(path.name, POSITIVE_SIGNALS) or _has_signal(path.parent.name, POSITIVE_SIGNALS) else 0.45
        if confidence < self.config.min_confidence:
            return None
        return DiscoveryCandidate(
            source_type="database",
            name=f"Base {engine} detectada",
            detected_path=str(path),
            detected_engine=engine,
            confidence=confidence,
            capabilities={"database_file": True, "engine": engine, "read_supported_future": True},
            sample_metadata={
                "extension": suffix,
                "size_bytes": stat.st_size,
                "modified_at": _utc_from_timestamp(stat.st_mtime),
                "connection_not_attempted": True,
            },
            raw_discovery={"path": path, "extension": suffix, "engine": engine},
        )

    def score_candidate(self, *, folder: Path, files: list[dict[str, Any]]) -> float:
        path_text = _norm_text(str(folder))
        file_signal_count = sum(1 for item in files if bool(item.get("positive_signal")))
        data_count = len(files)
        score = 0.2
        if "aiva/comercial/entrada" in path_text or "aiva_comercio/entrada" in path_text:
            score += 0.55
        if any(signal in path_text for signal in ("reportes", "ventas", "stock", "sistema", "gestion", "gestión")):
            score += 0.25
        if data_count >= 3:
            score += 0.2
        elif data_count >= 1:
            score += 0.15
        if file_signal_count >= 2:
            score += 0.15
        elif file_signal_count == 1:
            score += 0.1
        if "downloads" in path_text or "documents" in path_text or "documentos" in path_text:
            if file_signal_count and data_count:
                score = max(score, 0.55)
            score = min(score, 0.75)
        if _has_signal(str(folder), NEGATIVE_SIGNALS):
            score -= 0.4
        return round(max(0.0, min(score, 0.95)), 2)

    def deduplicate_candidates(self, candidates: list[DiscoveryCandidate]) -> list[DiscoveryCandidate]:
        deduped: dict[str, DiscoveryCandidate] = {}
        for candidate in candidates:
            if candidate.detected_path:
                key = f"{candidate.source_type}:path:{candidate.detected_path.lower()}"
            else:
                key = f"{candidate.source_type}:host:{candidate.detected_host}:{candidate.detected_engine}".lower()
            existing = deduped.get(key)
            if not existing or candidate.confidence > existing.confidence:
                deduped[key] = candidate
        return list(deduped.values())

    def sanitize_candidate(self, candidate: DiscoveryCandidate) -> DiscoveryCandidate:
        candidate.confidence = round(max(0.0, min(float(candidate.confidence), 1.0)), 2)
        candidate.raw_discovery = _safe_json(candidate.raw_discovery)
        candidate.sample_metadata = _safe_json(candidate.sample_metadata)
        candidate.capabilities = _safe_json(candidate.capabilities)
        return candidate

    def to_backend_payload(self, candidate: DiscoveryCandidate, collector_config: CollectorConfig) -> dict[str, Any]:
        payload = {
            "collector_id": collector_config.collector_id,
            "source_type": candidate.source_type,
            "name": candidate.name[:120],
            "confidence": candidate.confidence,
            "capabilities": candidate.capabilities,
            "sample_metadata": candidate.sample_metadata,
            "raw_discovery": candidate.raw_discovery,
        }
        for key in ("detected_path", "detected_host", "detected_engine"):
            value = getattr(candidate, key)
            if value:
                payload[key] = value
        return _safe_json(payload)


def discovery_queue_file_id(payload: dict[str, Any]) -> str:
    stable = json.dumps(
        {
            "source_type": payload.get("source_type"),
            "detected_path": payload.get("detected_path"),
            "detected_host": payload.get("detected_host"),
            "detected_engine": payload.get("detected_engine"),
            "name": payload.get("name"),
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return "discovery-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]


def discovery_queue_payload(payload: dict[str, Any], config: CollectorConfig) -> dict[str, Any]:
    queued = dict(payload)
    queued["_aiva_queue_kind"] = "data_source_discovery"
    queued["commerce_id"] = config.commerce_id
    queued["collector_id"] = config.collector_id
    return queued


class DiscoveryReporter:
    def __init__(self, collector_config: CollectorConfig, *, client: CollectorClient | None = None) -> None:
        self.collector_config = collector_config
        self.client = client or CollectorClient(collector_config)

    def report_discoveries(self, candidates: list[DiscoveryCandidate], scanner: DiscoveryScanner) -> DiscoveryReportResult:
        result = DiscoveryReportResult()
        for candidate in candidates[: scanner.config.max_report_candidates]:
            one = self.report_one(scanner.to_backend_payload(candidate, self.collector_config))
            result.attempted += one.attempted
            result.sent += one.sent
            result.duplicate += one.duplicate
            result.queued += one.queued
            result.errors += one.errors
        return result

    def report_one(self, payload: dict[str, Any]) -> DiscoveryReportResult:
        result = DiscoveryReportResult(attempted=1)
        try:
            response = self.client.post_data_source_discovery(payload)
            self.handle_backend_response(response)
            result.sent += 1
        except BackendError as exc:
            if exc.status_code == 409:
                result.duplicate += 1
                return result
            if is_temporary_backend_error(exc):
                self.queue_if_offline(payload, str(exc))
                result.queued += 1
                return result
            logging.error("Discovery backend error: %s", exc)
            result.errors += 1
        return result

    def queue_if_offline(self, payload: dict[str, Any], last_error: str) -> None:
        queued_payload = discovery_queue_payload(payload, self.collector_config)
        conn = connect_local_state(local_db_path(self.collector_config))
        try:
            enqueue_payload(
                conn,
                self.collector_config,
                file_id=discovery_queue_file_id(payload),
                payload=queued_payload,
                last_error=last_error,
            )
        finally:
            conn.close()

    def handle_backend_response(self, response: dict[str, Any]) -> None:
        status = int(response.get("_http_status_code", 200))
        if status not in (200, 201):
            raise BackendError(f"Backend respondio HTTP {status}", status_code=status)
