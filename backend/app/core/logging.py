import logging
import sys
from loguru import logger
from app.core.config import settings


class InterceptHandler(logging.Handler):
    """
    Redirect standard library `logging` records to `loguru`.
    """
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging():
    level = getattr(settings, "log_level", "INFO").upper()

    # Remove default handler
    logger.remove()

    # Modern colorized handler with formatted timestamps and call sites
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # Intercept standard library logging (uvicorn, httpx, etc.)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    for noisy_logger in ("httpx", "urllib3", "google", "botocore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    return logger


logger = setup_logging()