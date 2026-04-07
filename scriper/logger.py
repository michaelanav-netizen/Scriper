import logging
import sys
from typing import Callable, Optional

_FMT = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

# All named loggers used by the app — so we can attach the GUI handler to all.
_LOGGER_NAMES = ["main", "auth", "scraper", "combinations", "export"]


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_FMT)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class _CallbackHandler(logging.Handler):
    """Forwards every log record to a callback (used by the GUI text widget)."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.setFormatter(_FMT)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record))
        except Exception:
            self.handleError(record)


def add_gui_handler(callback: Callable[[str], None]) -> None:
    """
    Attaches a logging handler to every app logger so that each log line is
    also passed to `callback(message_string)`.  Called once by gui.py.
    """
    handler = _CallbackHandler(callback)
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        # Avoid duplicate GUI handlers if called more than once.
        if not any(isinstance(h, _CallbackHandler) for h in logger.handlers):
            logger.addHandler(handler)


def remove_gui_handlers() -> None:
    """Removes all GUI callback handlers (e.g. between runs)."""
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers = [
            h for h in logger.handlers if not isinstance(h, _CallbackHandler)
        ]
