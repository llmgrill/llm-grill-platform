import logging
import sys

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Redirect stdlib logging (uvicorn, sqlalchemy, ...) to loguru."""

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


_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
    "<level>{level: <8}</level> "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> "
    "<level>{message}</level>"
)


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, format=_FORMAT, backtrace=False, diagnose=False)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "sqlalchemy"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False
