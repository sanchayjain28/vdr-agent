import logging
import sys
from logging.config import dictConfig
from typing import Optional

# Third-party loggers to suppress (set to WARNING to reduce noise)
NOISY_LOGGERS = [
    "botocore",
    "boto3",
    "urllib3",
    "httpcore",
    "httpx",
    "s3transfer",
    "aiobotocore",
    "aiohttp",
    "asyncio",
    "chardet",
    "charset_normalizer",
]


def configure_logging(level: Optional[str] = "INFO") -> None:
    """Configure root logger with a structured format.

    Sets app loggers to the configured level while suppressing
    verbose third-party library logs (AWS SDK, HTTP clients, etc.)
    """

    resolved_level = (level or "INFO").upper()

    loggers_config: dict = {
        "uvicorn": {
            "handlers": ["console"],
            "level": resolved_level,
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": resolved_level,
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "app": {
            "level": resolved_level,
            "propagate": True,
        },
    }

    for logger_name in NOISY_LOGGERS:
        loggers_config[logger_name] = {
            "level": "WARNING",
            "propagate": False,
        }

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": resolved_level,
        },
        "loggers": loggers_config,
    }
    dictConfig(logging_config)
    logging.captureWarnings(True)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)
