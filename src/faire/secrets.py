"""Heuristics keeping secret values out of configuration files."""

from __future__ import annotations

import re

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_KEY = re.compile(r"(token|password|passwd|secret|api[_-]?key|credential)", re.I)


def is_secret_name(value: str) -> bool:
    """True when `value` looks like the name of a secret, not a secret value."""
    return bool(_NAME.match(value))


def looks_like_credential_key(key: str) -> bool:
    return bool(_KEY.search(key))
