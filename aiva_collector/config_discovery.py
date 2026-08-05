from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, CollectorConfig, collector_data_dir, load_config
from .errors import ConfigError


CONFIG_FILENAMES = (
    "config.json",
    "config.windows.json",
    "aiva_collector_config.json",
    "collector_config.json",
    "config.local.json",
)
TOKEN_KEYS = ("collector_token", "token", "api_token", "secret", "aiva_secret", "internal_secret")
PLACEHOLDERS = ("reemplazar", "placeholder", "peg ar", "pegar", "example", "demo", "changeme", "xxx")
PREFERRED_ACTIVE_PARTS = ("programdata", "aiva collector", "aiva_comercio")
BACKUP_PARTS = ("backup", "backups", "copia")


@dataclass(frozen=True)
class ConfigCandidate:
    path: Path
    score: float
    modified_at: float
    has_backend_url: bool
    has_commerce_id: bool
    has_collector_id: bool
    has_token: bool
    valid: bool
    reason: str = ""


@dataclass(frozen=True)
class RuntimeConfigResult:
    config: CollectorConfig
    selected_path: Path
    standard_path: Path
    candidates: list[ConfigCandidate]
    migrated: bool = False
    backup_path: Path | None = None


def standard_config_path() -> Path:
    override = os.getenv("AIVA_COLLECTOR_STANDARD_CONFIG")
    if override:
        return Path(override)
    base_override = os.getenv("AIVA_COLLECTOR_STANDARD_DIR")
    if base_override:
        return Path(base_override) / "config.local.json"
    return collector_data_dir() / "config.local.json"


def installed_config_dirs(*, exe_dir: Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    env_config = os.getenv("AIVA_COLLECTOR_CONFIG")
    if env_config:
        dirs.append(Path(env_config).parent)
    if exe_dir:
        dirs.append(exe_dir)
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.extend(
        [
            Path.cwd(),
            Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else PROJECT_ROOT,
            PROJECT_ROOT,
            standard_config_path().parent,
            Path(r"C:\ProgramData\AIVA Collector"),
            Path(r"C:\ProgramData\AIVA"),
            Path(r"C:\AIVA_Collector"),
            Path(r"C:\AIVA_Comercio"),
            Path(r"C:\AIVA_Comercio_2.5 - copia"),
            Path(r"C:\AIVA_Comercio_TEST_MANUAL"),
            Path(r"C:\AIVA\Collector"),
            Path(r"C:\AIVA\Comercial"),
            Path(r"C:\AIVA\Comercial\Collector"),
            Path(r"C:\Program Files\AIVA Collector"),
            Path(r"C:\Program Files (x86)\AIVA Collector"),
        ]
    )
    extra_roots = os.getenv("AIVA_COLLECTOR_CONFIG_SEARCH_DIRS")
    if extra_roots:
        dirs.extend(Path(item) for item in extra_roots.split(os.pathsep) if item.strip())
    deduped: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        key = str(directory).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(directory)
    return deduped


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_installed_config_candidates(
    *,
    explicit_config: str | Path | None = None,
    exe_dir: Path | None = None,
    search_dirs: list[Path] | None = None,
) -> list[Path]:
    paths: list[Path] = []
    if explicit_config:
        paths.append(Path(explicit_config))
    env_config = os.getenv("AIVA_COLLECTOR_CONFIG")
    if env_config:
        paths.append(Path(env_config))
    paths.append(standard_config_path())
    for directory in search_dirs or installed_config_dirs(exe_dir=exe_dir):
        if directory.is_file():
            paths.append(directory)
            continue
        for filename in CONFIG_FILENAMES:
            paths.append(directory / filename)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key not in seen and path.exists() and path.is_file():
            seen.add(key)
            deduped.append(path)
    return deduped


def _value_present(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    return isinstance(value, str) and bool(value.strip())


def _has_placeholder(data: dict[str, Any], path: Path) -> bool:
    text = " ".join([path.name, str(path.parent), json.dumps(data, ensure_ascii=True)]).lower()
    return any(item in text for item in PLACEHOLDERS)


def _identity_has_placeholder(data: dict[str, Any]) -> bool:
    text = " ".join(str(data.get(key, "")) for key in ("backend_url", "commerce_id", "collector_id")).lower()
    return any(item in text for item in PLACEHOLDERS)


def _path_contains(path: Path, needles: tuple[str, ...]) -> bool:
    lowered = str(path).lower()
    return any(needle in lowered for needle in needles)


def config_has_token(data: dict[str, Any]) -> bool:
    return any(_value_present(data, key) for key in TOKEN_KEYS)


def score_config_candidate(path: Path) -> ConfigCandidate:
    data = _read_json(path)
    modified_at = path.stat().st_mtime if path.exists() else 0.0
    if data is None:
        return ConfigCandidate(path, 0.0, modified_at, False, False, False, False, False, "invalid_json")

    has_backend = _value_present(data, "backend_url")
    has_commerce = _value_present(data, "commerce_id")
    has_collector = _value_present(data, "collector_id")
    has_token = config_has_token(data)
    has_placeholder = _has_placeholder(data, path)
    valid = has_backend and has_commerce and has_collector and not _identity_has_placeholder(data)
    score = 0.0
    if has_backend:
        score += 30
    if has_commerce:
        score += 25
    if has_collector:
        score += 25
    if has_token:
        score += 20
    if _path_contains(path, PREFERRED_ACTIVE_PARTS):
        score += 8
    if _path_contains(path, BACKUP_PARTS):
        score -= 8
    lowered = str(path).lower()
    if any(word in lowered for word in ("example", "template", "sample")):
        score -= 50
    if has_placeholder:
        score -= 40
    score += min(max((modified_at or 0.0) / 1_000_000_000, 0.0), 3.0)
    reason = "valid" if valid else "missing_required_fields"
    return ConfigCandidate(path, round(score, 3), modified_at, has_backend, has_commerce, has_collector, has_token, valid, reason)


def select_best_config_candidate(candidates: list[Path] | None = None) -> ConfigCandidate | None:
    scored = [score_config_candidate(path) for path in (candidates or find_installed_config_candidates())]
    valid = [candidate for candidate in scored if candidate.valid and candidate.score > 0]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda item: (
            item.score,
            0 if _path_contains(item.path, BACKUP_PARTS) else 1,
            1 if _path_contains(item.path, PREFERRED_ACTIVE_PARTS) else 0,
            item.modified_at,
        ),
        reverse=True,
    )[0]


def migrate_config_to_standard_location(source: Path, *, standard_path: Path | None = None) -> tuple[Path, Path | None, bool]:
    standard = standard_path or standard_config_path()
    source = Path(source)
    if source.resolve() == standard.resolve() and standard.exists():
        return standard, None, False
    if standard.exists():
        current = score_config_candidate(standard)
        if current.valid:
            return standard, None, False
        backup_dir = standard.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backup_dir / f"config.previous.{stamp}.json"
        shutil.copy2(standard, backup)
    else:
        backup = None
    standard.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, standard)
    return standard, backup, True


def resolve_collector_token(config: CollectorConfig, cli_token: str | None = None) -> str | None:
    if cli_token:
        return cli_token
    env_token = os.getenv(config.collector_token_env or "AIVA_COLLECTOR_TOKEN")
    if env_token:
        return env_token
    for key in TOKEN_KEYS:
        value = config.raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_runtime_config(
    config_arg: str | Path | None = None,
    *,
    migrate: bool = True,
    search_dirs: list[Path] | None = None,
) -> RuntimeConfigResult:
    if config_arg:
        requested = Path(config_arg)
        try:
            config = load_config(requested)
        except ConfigError:
            # La tarea de Windows usa siempre la ruta canonica. Si una version
            # anterior dejo solo config.windows.json, permitimos que el mismo
            # arranque la encuentre y la migre sin perder la activacion.
            if requested.resolve() != standard_config_path().resolve():
                raise
        else:
            candidate = score_config_candidate(config.config_path)
            if requested.resolve() != standard_config_path().resolve() or candidate.valid:
                return RuntimeConfigResult(
                    config=config,
                    selected_path=config.config_path,
                    standard_path=standard_config_path(),
                    candidates=[candidate],
                )
    env_config = os.getenv("AIVA_COLLECTOR_CONFIG")
    if env_config:
        config = load_config(env_config)
        return RuntimeConfigResult(
            config=config,
            selected_path=config.config_path,
            standard_path=standard_config_path(),
            candidates=[score_config_candidate(config.config_path)],
        )
    candidates = find_installed_config_candidates(search_dirs=search_dirs)
    standard = standard_config_path()
    scored = [score_config_candidate(path) for path in candidates]
    standard_candidate = next((item for item in scored if item.path.resolve() == standard.resolve()), None)
    if standard_candidate and standard_candidate.valid:
        return RuntimeConfigResult(load_config(standard), standard, standard, scored)
    best = select_best_config_candidate(candidates)
    if not best:
        raise ConfigError(
            "No se encontro configuracion valida del Collector. "
            f"Ejecute la activacion o revise {standard}."
        )
    selected = best.path
    backup_path = None
    migrated = False
    if migrate:
        selected, backup_path, migrated = migrate_config_to_standard_location(best.path, standard_path=standard)
    return RuntimeConfigResult(load_config(selected), selected, standard, scored, migrated=migrated, backup_path=backup_path)
