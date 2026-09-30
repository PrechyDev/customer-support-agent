import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handlers: list[logging.Handler] = []


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    """Send logs to stderr in one format, and also to `log_file` if given. Safe to call more than once.

    Only our own handlers are replaced; handlers added by others (e.g. pytest) are kept.
    The file is for local testing (LOG_FILE, gitignored under logs/); Cloud Run collects stderr itself.
    """
    root = logging.getLogger()
    for handler in _handlers:
        root.removeHandler(handler)
        handler.close()
    _handlers.clear()

    _handlers.append(logging.StreamHandler(sys.stderr))
    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        _handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for handler in _handlers:
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
