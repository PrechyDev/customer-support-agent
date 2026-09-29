import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handler: logging.Handler | None = None


def configure_logging(level: str = "INFO") -> None:
    """Send logs to stderr in one format. Safe to call more than once.

    Only our own handler is replaced; handlers added by others (e.g. pytest) are kept.
    """
    global _handler
    root = logging.getLogger()
    if _handler is not None:
        root.removeHandler(_handler)
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(_handler)
    root.setLevel(level)
