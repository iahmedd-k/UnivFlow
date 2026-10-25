import logging
import sys

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSUTIL_AVAILABLE = False

from app.core.config import settings

_configured = False


def get_memory_rss_mb() -> float:
    """Return current process resident set size in MB."""
    if _PSUTIL_AVAILABLE:
        try:
            return psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:
            pass
    # Fallback: parse /proc/self/status (Linux)
    try:
        with open("/proc/self/status", "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    # "VmRSS:   12345 kB"
                    parts = line.split()
                    if len(parts) >= 2:
                        return float(parts[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def setup_logging() -> logging.Logger:
    global _configured

    logger = logging.getLogger(settings.project_name)
    if _configured:
        return logger

    level = logging.DEBUG if settings.debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    _configured = True

    return logger


logger = setup_logging()