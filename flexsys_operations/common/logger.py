"""Logging helpers for FlexSys Operations."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a standard Python logger for the requested namespace."""
    return logging.getLogger(name)
