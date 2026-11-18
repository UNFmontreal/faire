"""Reference protocol tool: what a sample of this dataset is expected to contain.

    python3 .faire/protocol.py learn    derive the expectations from the pilot samples on the
                                        checked-out branch and write .faire/protocol.yaml
    python3 .faire/protocol.py check    report what the sample under review lacks (the default)

`check` is the `protocol` check of `.faire/rules.yaml`. It only warns: a deviating sample may be
accepted by the curator. Commit protocol.yaml to `dev` once the pilot samples are accepted, and
the production samples that follow are checked against it. Replace this tool with the study's own
(for example one that also compares acquisition parameters).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

EXPECTATIONS = Path(".faire/protocol.yaml")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def sample_of(text):
    return dict(part.split("=", 1) for part in text.split(",") if "=" in part)


def tracked():
    return [p for p in git("ls-files", "-z").split("\0") if p and not p.startswith(".")]


def generalise(path, sample):
    """The path with the sample's entity values as placeholders, when they are folders."""
    parts = path.split("/")
    for name, value in sample.items():
        parts = [f"{{{name}}}" if part == value else part for part in parts]
    return "/".join(parts)


def learn():
    """Patterns every pilot sample satisfies; the samples are those the run records name."""
    log = git("log", "--format=%B")
    samples = [
        sample_of(m) for m in dict.fromkeys(re.findall(r"^faire-output-sample: (.+)$", log, re.M))
    ]
    if not samples:
        print("no sample recorded here: nothing to learn from", file=sys.stderr)
        return 1
    files = tracked()
    per_sample = []
    for sample in samples:
        mine = {
            generalise(f, sample) for f in files if all(v in f.split("/") for v in sample.values())
        }
        per_sample.append({m for m in mine if "{" in m})
    expected = sorted(set.intersection(*per_sample)) if per_sample else []
    EXPECTATIONS.write_text(yaml.safe_dump({"expect": expected}, sort_keys=False))
    print(f"{len(expected)} expectation(s) from {len(samples)} sample(s): {EXPECTATIONS}")
    return 0


def check():
    if not EXPECTATIONS.exists():
        print("no protocol expectations yet: derive them from pilot samples (protocol.py learn)")
        return 0
    sample = sample_of(os.environ.get("FAIRE_SAMPLE", ""))
    expected = (yaml.safe_load(EXPECTATIONS.read_text()) or {}).get("expect") or []
    present = set(tracked())
    missing = []
    for pattern in expected:
        try:
            path = pattern.format(**sample)
        except KeyError:
            continue  # an entity this branch does not tell
        if path not in present:
            missing.append(path)
    for path in missing:
        print(f"warning: the protocol expects {path}, which this sample lacks")
    return 1 if missing else 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    sys.exit({"learn": learn, "check": check}[command]())
