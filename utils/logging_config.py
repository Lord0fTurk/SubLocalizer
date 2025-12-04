from __future__ import annotations

from pathlib import Path
from loguru import logger


def configure_logging(log_file: Path | None = None) -> None:
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file, level="DEBUG", rotation="1 MB", retention=5)
