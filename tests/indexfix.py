"""Helpers shared by the indexing tests."""

import subprocess
from pathlib import Path

from datalad.api import clone

from faire import indexing

GROUP = "example-study"
REPO = "dicoms-a_PrismaFit16001"


def received(tmp_path, files, name="incoming"):
    root = tmp_path / name
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def request(study, platform, incoming, **kw):
    return indexing.Request(
        incoming,
        "dicoms",
        study.dmp,
        study.site,
        indexing.locator(platform, GROUP, None),
        **kw,
    )


def git(url, *args):
    out = subprocess.run(["git", *args], cwd=url, capture_output=True, text=True)
    return out.stdout.strip()


def remote_head(platform, branch="dev", repo=REPO):
    return git(platform.get_repository(GROUP, repo).url, "rev-parse", branch)


def set_heuristic(platform, tmp_path, body, repo=REPO, name="edit"):
    """Replace the heuristic in the instance's `dev`, as a study would by a merged change."""
    url = platform.get_repository(GROUP, repo).url
    work = clone(url, str(tmp_path / name), result_renderer="disabled")
    work.repo.call_git(["checkout", "dev"])
    (Path(work.path) / ".faire/heuristic.py").write_text(body)
    work.save(message="heuristic for the test", result_renderer="disabled")
    work.push(to="origin", data="nothing", result_renderer="disabled")
