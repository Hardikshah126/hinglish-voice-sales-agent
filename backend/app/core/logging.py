"""Structured (JSON-lines) logging. Never pass secrets into log fields."""

import json
import logging
import sys
from datetime import UTC, datetime

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
_REDACT = ("key", "secret", "token", "password", "authorization")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in _RESERVED:
                continue
            payload[k] = "[redacted]" if any(s in k.lower() for s in _REDACT) else v
        if record.exc_info and record.exc_info[0]:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
