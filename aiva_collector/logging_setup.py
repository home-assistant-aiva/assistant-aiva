from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import CollectorConfig


def setup_logging(config: CollectorConfig) -> None:
    log_path = config.path("log_file")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
