"""Processing rules and checks a dataset carries in `.faire/rules.yaml`.

rules:
  - id: process
    trigger: {source: dicoms}        # or {paths: ["{subject}/anat/*.nii.gz"]} (content-triggered)
    container: tool
    command: "sh -c 'cat {inputs} > {outputs}'"   # {inputs}/{outputs}: datalad placeholders
    inputs: [{pattern: "sourcedata/dicoms/{subject}/*.txt", required: true}]
    outputs: ["{subject}/processed.txt"]
    artifacts: [".faire/logs/"]
    listing: ["{subject}/report.html"]
checks:
  - {id: layout, command: "test -f README.md", blocking: true}

Rules are ordered as listed. Entity placeholders (`{subject}`) are substituted by the tool; the
placeholders `{inputs}`, `{outputs}`, `{pwd}` and `{dspath}` are left to `datalad run`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RULES_FILE = ".faire/rules.yaml"
DATALAD_PLACEHOLDERS = frozenset({"inputs", "outputs", "pwd", "dspath", "img", "img_dspath"})
_FIELD = re.compile(r"\{([A-Za-z0-9_]+)\}")


class RuleError(ValueError):
    pass


class MissingEntity(RuleError):
    pass


@dataclass(frozen=True)
class Input:
    pattern: str
    required: bool = False


@dataclass(frozen=True)
class Trigger:
    source: str | None = None
    paths: tuple[str, ...] = ()

    @property
    def content(self) -> bool:
        return self.source is None


@dataclass(frozen=True)
class Rule:
    id: str
    trigger: Trigger
    container: str
    command: str
    inputs: tuple[Input, ...] = ()
    outputs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    listing: tuple[str, ...] = ()
    optional: bool = False

    def trigger_patterns(self) -> tuple[str, ...]:
        """Patterns whose files' state decides whether the rule is due."""
        if self.trigger.source is not None:
            prefix = f"sourcedata/{self.trigger.source}/"
            return tuple(i.pattern for i in self.inputs if i.pattern.startswith(prefix))
        return self.trigger.paths or tuple(i.pattern for i in self.inputs)

    def entities(self) -> list[str]:
        """Entity names used by the rule's trigger patterns, in first-use order."""
        return entities_of(self.trigger_patterns())


@dataclass(frozen=True)
class Check:
    id: str
    command: str
    blocking: bool = True


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...] = ()
    checks: tuple[Check, ...] = ()
    version: str = ""  # identifies the rule file's content

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise RuleError(f"no rule {rule_id!r}")

    def order(self, rule_id: str) -> int:
        return [r.id for r in self.rules].index(rule_id)


def entities_of(patterns: tuple[str, ...] | list[str]) -> list[str]:
    names: list[str] = []
    for pattern in patterns:
        for name in _FIELD.findall(pattern):
            if name not in DATALAD_PLACEHOLDERS and name not in names:
                names.append(name)
    return names


def resolve(pattern: str, sample: dict[str, str]) -> str:
    """Substitute a sample's entity values into a pattern."""

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in DATALAD_PLACEHOLDERS:
            return match.group(0)
        if name not in sample:
            raise MissingEntity(f"pattern {pattern!r} uses entity {name!r}, which the sample lacks")
        return sample[name]

    return _FIELD.sub(sub, pattern)


def _glob_regex(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif text.startswith("**", i):
            out.append(".*")
            i += 2
        elif text[i] == "*":
            out.append("[^/]*")
            i += 1
        elif text[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(text[i]))
            i += 1
    return "".join(out)


def matcher(pattern: str) -> re.Pattern[str]:
    """Regex for a pattern whose entity placeholders capture values by name."""
    parts, last = [], 0
    for match in _FIELD.finditer(pattern):
        name = match.group(1)
        if name in DATALAD_PLACEHOLDERS:
            continue
        parts.append(_glob_regex(pattern[last : match.start()]))
        parts.append(f"(?P<{name}>[^/]+)")
        last = match.end()
    parts.append(_glob_regex(pattern[last:]))
    return re.compile("".join(parts) + r"\Z")


def glob_match(pattern: str, path: str) -> bool:
    """Whether a resolved glob (no entity placeholders) matches a path or a directory prefix."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return re.match(_glob_regex(pattern) + r"\Z", path) is not None


def parse(raw: dict[str, Any], version: str = "") -> RuleSet:
    rules, seen = [], set()
    for entry in raw.get("rules") or []:
        rule_id = entry.get("id")
        if not rule_id:
            raise RuleError("a rule has no `id`")
        if rule_id in seen:
            raise RuleError(f"duplicate rule id {rule_id!r}")
        seen.add(rule_id)
        trigger = entry.get("trigger") or {}
        if bool(trigger.get("source")) == bool(trigger.get("paths")):
            raise RuleError(f"rule {rule_id!r}: trigger needs exactly one of `source` or `paths`")
        if not entry.get("container") or not entry.get("command"):
            raise RuleError(f"rule {rule_id!r}: `container` and `command` are required")
        inputs = tuple(
            Input(i, False) if isinstance(i, str) else Input(i["pattern"], bool(i.get("required")))
            for i in entry.get("inputs") or []
        )
        rule = Rule(
            rule_id,
            Trigger(trigger.get("source"), tuple(trigger.get("paths") or ())),
            entry["container"],
            entry["command"],
            inputs,
            tuple(entry.get("outputs") or ()),
            tuple(entry.get("artifacts") or ()),
            tuple(entry.get("listing") or ()),
            bool(entry.get("optional")),
        )
        if not rule.trigger_patterns():
            raise RuleError(f"rule {rule_id!r}: nothing declares what triggers it")
        rules.append(rule)
    checks, seen = [], set()
    for entry in raw.get("checks") or []:
        if not entry.get("id") or not entry.get("command"):
            raise RuleError("a check needs `id` and `command`")
        if entry["id"] in seen:
            raise RuleError(f"duplicate check id {entry['id']!r}")
        seen.add(entry["id"])
        checks.append(Check(entry["id"], entry["command"], bool(entry.get("blocking", True))))
    return RuleSet(tuple(rules), tuple(checks), version)


def load(root: str | Path) -> RuleSet:
    path = Path(root) / RULES_FILE
    if not path.exists():
        return RuleSet()
    text = path.read_text()
    from hashlib import sha1

    version = sha1(text.encode()).hexdigest()  # noqa: S324 - content id, not security
    try:
        return parse(yaml.safe_load(text) or {}, version)
    except yaml.YAMLError as exc:
        raise RuleError(f"{RULES_FILE}: {exc}") from exc


def check_containers(rules: RuleSet, registered: set[str]) -> None:
    """Planning fails before executing anything when a rule names an unregistered container."""
    for rule in rules.rules:
        if rule.container not in registered:
            raise RuleError(
                f"rule {rule.id!r} names container {rule.container!r}, which is not "
                f"registered in this dataset"
            )


@dataclass
class Sample:
    """One sample: values for the entities its rules use."""

    values: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return ",".join(f"{k}={v}" for k, v in self.values.items())

    @property
    def slug(self) -> str:
        return "_".join(f"{k}-{v}" for k, v in self.values.items())
