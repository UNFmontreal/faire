"""Authenticate git against a platform without writing the token anywhere.

The token lives only in the environment of this process and of the git processes it starts.
Git reads it through an inline credential helper that echoes an environment variable, so the
token is in no configuration file, remote URL or command line.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

PASSWORD_ENV = "FAIRE_GIT_PASSWORD"
USERNAME = "oauth2"  # accepted by GitLab for personal, group, project and OAuth tokens

HELPER = (
    '!f() { test "$1" = get || exit 0; '
    f'echo username={USERNAME}; echo "password=${PASSWORD_ENV}"; }}; f'
)


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def config_entries(url: str) -> list[tuple[str, str]]:
    key = f"credential.{origin(url)}.helper"
    return [(key, ""), (key, HELPER)]  # the empty value drops helpers configured elsewhere


@contextmanager
def git_auth(url: str | None, token: str | None) -> Iterator[None]:
    """Make every git process started inside the block authenticate to `url` with `token`.

    Without a token or URL nothing changes, so git's own credential helpers apply.
    """
    if not url or not token:
        yield
        return
    names = [PASSWORD_ENV, "GIT_TERMINAL_PROMPT", "GIT_CONFIG_COUNT"]
    saved = {name: os.environ.get(name) for name in names}
    entries = config_entries(url)
    start = int(saved["GIT_CONFIG_COUNT"] or 0)
    added = []
    try:
        os.environ[PASSWORD_ENV] = token
        os.environ["GIT_TERMINAL_PROMPT"] = "0"  # fail at once instead of asking
        for offset, (key, value) in enumerate(entries):
            os.environ[f"GIT_CONFIG_KEY_{start + offset}"] = key
            os.environ[f"GIT_CONFIG_VALUE_{start + offset}"] = value
            added += [f"GIT_CONFIG_KEY_{start + offset}", f"GIT_CONFIG_VALUE_{start + offset}"]
        os.environ["GIT_CONFIG_COUNT"] = str(start + len(entries))
        yield
    finally:
        for name in added:
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
