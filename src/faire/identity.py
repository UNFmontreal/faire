"""Automation identity: who pipeline-made commits are attributed to."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from datalad.api import Dataset

ENV_NAME = "FAIRE_AUTOMATION_NAME"
ENV_EMAIL = "FAIRE_AUTOMATION_EMAIL"
DEFAULT = ("faire-automation", "faire-automation@localhost")


@dataclass(frozen=True)
class Identity:
    name: str
    email: str


def from_environment(env: Mapping[str, str] | None = None) -> Identity:
    """The identity set by the platform's CI variables, or the default automation identity."""
    env = os.environ if env is None else env
    return Identity(env.get(ENV_NAME) or DEFAULT[0], env.get(ENV_EMAIL) or DEFAULT[1])


def apply(dataset: Dataset, identity: Identity) -> None:
    """Make commits of this dataset's clone author and committer the automation identity."""
    dataset.config.set("user.name", identity.name, scope="local")
    dataset.config.set("user.email", identity.email, scope="local")
