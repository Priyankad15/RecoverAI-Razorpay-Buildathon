"""Basic application-wide logging configuration."""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once at application startup."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
