from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .token_store import load_token


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MAPPING_KEYS = {"producto_nombre", "cantidad_vendida", "precio_venta"}
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_windows_absolute_path(value: str) -> bool:
    return bool(WINDOWS_ABSOLUTE_RE.match(value)) or value.startswith("\\\\")


def _resolve_path_value(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or _looks_like_windows_absolute_path(value):
        return path
    return PROJECT_ROOT / path


@dataclass(frozen=True)
class CollectorConfig:
    raw: dict[str, Any]
    config_path: Path

    @property
    def collector_version(self) -> str:
        return str(self.raw.get("collector_version", "0.1.0"))

    @property
    def backend_url(self) -> str:
        return str(self.raw.get("backend_url", "")).rstrip("/")

    @property
    def commerce_id(self) -> str:
        return str(self.raw.get("commerce_id", "")).strip()

    @property
    def collector_id(self) -> str:
        return str(self.raw.get("collector_id", "")).strip()

    @property
    def collector_token_env(self) -> str:
        return str(self.raw.get("collector_token_env", "AIVA_COLLECTOR_TOKEN")).strip()

    @property
    def token(self) -> str | None:
        value = os.getenv(self.collector_token_env)
        if value:
            return value
        for key in ("collector_token", "token", "api_token", "secret", "aiva_secret", "internal_secret"):
            raw_value = self.raw.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return raw_value.strip()
        try:
            return load_token(self.path("state_dir"))
        except ConfigError:
            return None

    @property
    def column_mapping(self) -> dict[str, str]:
        mapping = self.raw.get("column_mapping", {})
        return dict(mapping) if isinstance(mapping, dict) else {}

    def path(self, key: str) -> Path:
        value = self.raw.get(key)
        if not value:
            raise ConfigError(f"Falta config requerida: {key}")
        return _resolve_path_value(str(value))

    def optional_path(self, key: str) -> Path | None:
        value = self.raw.get(key)
        if not value:
            return None
        return _resolve_path_value(str(value))

    def require_send_ready(self) -> None:
        missing = []
        if not self.backend_url:
            missing.append("backend_url")
        if not self.commerce_id:
            missing.append("commerce_id")
        if not self.collector_id:
            missing.append("collector_id")
        if missing:
            raise ConfigError("Faltan campos para enviar: " + ", ".join(missing))
        if not self.token:
            raise ConfigError("collector_not_activated: Falta token; activá AIVA Collector antes de enviar")


def load_config(path: str | Path) -> CollectorConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        raise ConfigError(f"No existe config: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    config = CollectorConfig(raw=data, config_path=config_path)
    validate_config_shape(config)
    return config


def validate_config_shape(config: CollectorConfig) -> None:
    if not config.commerce_id:
        raise ConfigError("commerce_id es requerido")
    if not config.collector_id:
        raise ConfigError("collector_id es requerido")
    if not config.collector_token_env:
        raise ConfigError("collector_token_env es requerido")
    mapping = config.column_mapping
    if not mapping:
        return
    missing = sorted(REQUIRED_MAPPING_KEYS - set(mapping))
    if missing:
        raise ConfigError("Faltan mappings requeridos: " + ", ".join(missing))


def init_config(output: str | Path, overwrite: bool = False) -> Path:
    source = PROJECT_ROOT / "configs" / "example_config.json"
    dest = Path(output)
    if not dest.is_absolute():
        dest = PROJECT_ROOT / dest
    if dest.exists() and not overwrite:
        raise ConfigError(f"Ya existe config: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return dest
