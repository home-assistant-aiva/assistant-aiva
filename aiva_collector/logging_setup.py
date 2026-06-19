from __future__ import annotations

import logging

from .config import CollectorConfig


def setup_logging(config: CollectorConfig) -> None:
    log_path = config.path("log_file")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
