"""Build a platform from command-line or CI settings."""

from __future__ import annotations

import os

from faire.platform import Platform, PlatformError

TOKEN_ENV = "FAIRE_PLATFORM_TOKEN"


def connect(name: str, url: str, token: str | None = None) -> Platform:
    token = token or os.environ.get(TOKEN_ENV)
    if not token:
        raise PlatformError(f"no platform token: set {TOKEN_ENV}")
    if name == "gitlab":
        from faire.platform.gitlab import GitLabPlatform

        return GitLabPlatform(url, token)
    raise PlatformError(f"unsupported platform {name!r}")
