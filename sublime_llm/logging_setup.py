"""Logger with secret-redacting filter."""
import logging
import re
import sys
from typing import Set

_LOGGER_NAME = "sublime_llm"
_REDACTED = "[REDACTED]"

_REGEX_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}"),
]

_secrets: Set[str] = set()
_initialized = False


def register_secret(value: str) -> None:
    if value:
        _secrets.add(value)


def unregister_secret(value: str) -> None:
    _secrets.discard(value)


def _redact(text: str) -> str:
    if not isinstance(text, str):
        return text
    for secret in _secrets:
        if secret:
            text = text.replace(secret, _REDACTED)
    for pat in _REGEX_PATTERNS:
        text = pat.sub(_REDACTED, text)
    return text


class SecretRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(
                        _redact(a) if isinstance(a, str) else a for a in record.args
                    )
                elif isinstance(record.args, dict):
                    record.args = {
                        k: (_redact(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
        except Exception:
            pass
        return True


def get_logger() -> logging.Logger:
    global _initialized
    logger = logging.getLogger(_LOGGER_NAME)
    if not _initialized:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[sublime-llm] %(levelname)s %(message)s"))
        handler.addFilter(SecretRedactFilter())
        logger.addHandler(handler)
        _initialized = True
    return logger
