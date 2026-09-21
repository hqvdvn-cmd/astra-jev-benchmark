from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(?:token|api[_-]?key|secret|password|cookie|authorization|credential|private[_-]?key)|(?:^|[_-])path$",
    re.IGNORECASE,
)
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")
_DEFAULT_LIMIT = 2048


def redact_state(value: object, *, max_text_bytes: int = _DEFAULT_LIMIT) -> object:
    """Remove credentials and local paths before state is sent to Jev."""
    return _redact(value, max_text_bytes=max_text_bytes, key=None)


def _redact(value: object, *, max_text_bytes: int, key: str | None) -> object:
    if key and _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {
            str(k): _redact(v, max_text_bytes=max_text_bytes, key=str(k))
            for k, v in value.items()
            if not (isinstance(k, str) and _SENSITIVE_KEY.search(k))
        }
    if isinstance(value, str):
        if _WINDOWS_PATH.match(value) or value.startswith("/"):
            return "[local path redacted]"
        encoded = value.encode("utf-8")
        if len(encoded) > max_text_bytes:
            return encoded[:max_text_bytes].decode("utf-8", errors="ignore") + "…"
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_redact(item, max_text_bytes=max_text_bytes, key=None) for item in value]
    return value
