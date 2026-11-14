"""Log safety for the gateway (Stage F).

Two guarantees, both tested:

1. Secrets never reach a log line. `redact()` strips client keys
   (``pag_sk_...``), admin keys (``pag_admin_...``), upstream-style
   ``sk-...`` tokens, ``Bearer ...`` headers and ``password=...`` /
   ``*_PASSWORD=...`` / ``*_API_KEY=...`` assignments from arbitrary
   text. `RedactingFilter` applies the same pass to every record the
   ``gateway`` logger emits, so a future ``logger.*`` call cannot leak
   a secret by accident.

2. Log rotation is available without changing the default. By default
   logs go to stdout (container / journald owns rotation in
   production). When ``GATEWAY_LOG_FILE`` is set, a
   ``RotatingFileHandler`` (10 MiB x 5) is added.

What this module deliberately does NOT do: it never touches prompt
content — prompt bodies are never passed to the logger in the first
place (see ``gateway.main.record``), and redaction is a second line of
defence, not the mechanism that keeps prompts out of logs.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re

# Client keys: "pag_sk_" + token_urlsafe(32) (~43 chars). Match 8+ so a
# truncated key in an error message is still caught.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"pag_sk_[A-Za-z0-9_\-]{8,}"), "[REDACTED-CLIENT-KEY]"),
    (re.compile(r"pag_admin_[A-Za-z0-9_\-]{8,}"), "[REDACTED-ADMIN-KEY]"),
    # Upstream-style keys, incl. "sk-proj-...".
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{8,}"), "[REDACTED-UPSTREAM-KEY]"),
    # Authorization headers that may be echoed in an error string.
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{8,}"), "Bearer [REDACTED]"),
    # password / secret assignments in text, JSON-ish or query form.
    # e.g. password=hunter2, "password": "hunter2", api_key: abc123
    (
        re.compile(
            r"(?i)(password|passwd|pwd|client_secret|api[_-]?key|admin[_-]?key)"
            r"(\s*[\"']?\s*[:=]\s*[\"']?)[^\s\"',}\]]+"
        ),
        r"\1\2[REDACTED]",
    ),
    # Env-style assignments (OPENAI_API_KEY=..., ADMIN_PASSWORD=...).
    (
        re.compile(
            r"(?i)\b[A-Z_]*(PASSWORD|API_KEY|ADMIN_KEY|SESSION_SECRET)\b\s*=\s*[^\s\"']+"
        ),
        "[REDACTED-ENV-SECRET]",
    ),
]


def redact(text: str) -> str:
    """Return `text` with secret-shaped substrings replaced."""
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from every record.

    It redacts the FINAL rendered message (``record.getMessage()``),
    not ``msg`` and ``args`` separately: a secret can straddle the
    boundary between a format string and its arguments (``"Bearer %s"``
    + a token), and redacting the parts separately would miss it.
    The redacted text replaces ``record.msg`` and ``args`` is cleared,
    so every handler renders the safe text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            formatted = record.getMessage()
        except Exception:
            formatted = str(record.msg)
        record.msg = redact(formatted)
        record.args = ()
        return True


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
ROTATE_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB per file
ROTATE_BACKUP_COUNT = 5


def configure_logging(
    logger: logging.Logger, log_file: str | None = None
) -> logging.Logger:
    """Attach the redacting filter; optionally add a rotating file handler.

    Defaults (log_file None) keep the existing stdout behaviour: the
    caller keeps its own basicConfig/handlers. A file handler is added
    only when a path is given, and never removes existing handlers.
    """
    logger.addFilter(RedactingFilter())
    if log_file:
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=ROTATE_MAX_BYTES,
            backupCount=ROTATE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
    return logger


def log_file_from_env() -> str | None:
    return os.environ.get("GATEWAY_LOG_FILE") or None
