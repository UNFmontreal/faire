"""Two sites and a hub, for the federation tests."""

import subprocess
from pathlib import Path

from datalad.api import Dataset

from conftest import Project
from faire import federation

GROUP = "example-study"


def git(where, *args):
    out = subprocess.run(["git", *args], cwd=where, capture_output=True, text=True)
    return out.stdout.strip()


class Site:
    def __init__(self, tmp_path: Path, name: str, hub: Path | None, storage: Path | None = None):
        root = tmp_path / name
        root.mkdir()
        self.project = Project(root, "federated.json", name)
        self.project.hub = {"url": str(hub)} if hub else None
        if storage and hub:
            self.project.hub["storage"] = {
                "type": "directory",
                "parameters": {"directory": str(storage)},
            }
        self.project.write()
        self.name = name

    def release_to(self, release: Path, archive: Path | None = None):
        """Replace the example's external hosts by directories every site reaches."""
        project = self.project
        standardized = next(
            d
            for d in project.doc["dmp"]["dataset"]
            if d["dataset_id"]["identifier"] == "standardized"
        )
        standardized["distribution"] = [
            d
            for d in standardized["distribution"]
            if d["faire"]["stage"] not in ("release", "archival")
        ]
        for stage, title, where, term in (
            ("release", "Release store", release, False),
            ("archival", "Archive", archive, True),
        ):
            if where is None:
                continue
            project.add_stage_distribution("standardized", stage, title, long_term=term)
            dist = standardized["distribution"][-1]
            dist["host"]["faire"]["parameters"]["directory"] = str(where)
        project.write()

    def init(self, **kw):
        return self.project.init(**kw)

    @property
    def root(self) -> Path:
        return self.project.ws.root

    def repo(self, name: str) -> Dataset:
        path = self.project.ws.repos / name if name != "study" else self.project.ws.study
        return Dataset(path)

    def sync(self, only=None):
        return federation.sync_all(self.root, self.project.dmp, self.project.site, only)

    def annexed(self, name: str, text: str, repo: str = "standardized"):
        """An accepted file kept in the annex, with its content in the site's review storage."""
        self.commit(repo, "dev", name, text)
        ds = self.repo(repo)
        git(ds.path, "annex", "copy", "--to", "review-site-storage", name)

    def commit(self, repo: str, branch: str, name: str, text: str):
        """An accepted sample: a file committed on `branch`."""
        ds = self.repo(repo)
        ds.repo.call_git(["checkout", "-q", branch])
        (Path(ds.path) / name).write_text(text)
        ds.save(message=f"accept {name}", result_renderer="disabled")


def make_hub(tmp_path: Path, names=("standardized", "study")) -> Path:
    hub = tmp_path / "hub"
    for name in names:
        subprocess.run(["git", "init", "-q", "--bare", str(hub / f"{name}.git")], check=True)
    return hub


def share_site_configurations(*all_sites: "Site") -> None:
    """Every site's configuration is readable by all: they live in the study superdataset."""
    for one in all_sites:
        for other in all_sites:
            if one is not other:
                text = (other.project.sites_dir / f"{other.name}.yaml").read_text()
                (one.project.sites_dir / f"{other.name}.yaml").write_text(text)
