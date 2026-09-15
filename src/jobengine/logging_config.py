"""Structured logging shared by every module.

One place configures the root handler/format; modules just call
get_logger(__name__). Level comes from JOBENGINE_LOG_LEVEL via config.
"""
from __future__ import annotations

import logging

from . import config

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
