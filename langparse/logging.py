"""
Logging for the library.

A library should not choose a logging framework for the application embedding
it, nor write to stderr uninvited. The stdlib logger with a NullHandler stays
silent until the host configures logging, and costs no dependency -- which
leaves langparse installable with nothing but the extras a caller actually
needs for their formats.
"""

from __future__ import annotations

import logging

ROOT_LOGGER_NAME = "langparse"

_root = logging.getLogger(ROOT_LOGGER_NAME)
_root.addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the `langparse` namespace."""
    if not name:
        return _root
    if name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
