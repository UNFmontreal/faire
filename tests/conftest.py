import copy
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

from faire import model, sites
from faire.bootstrap import Workspace
from rulefix import Collection


def pytest_configure(config):
    """Tests get their own global git configuration: a default identity (CI runners have none)
    and nothing from the developer's. Repository configuration, such as the automation identity,
    still takes precedence."""
    path = Path(tempfile.mkdtemp(prefix="faire-gitconfig-")) / "gitconfig"
    path.write_text("[user]\n\tname = Test User\n\temail = test@example.org\n")
    os.environ["GIT_CONFIG_GLOBAL"] = str(path)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    _prefer_this_environment()


def _prefer_this_environment() -> None:
    """Run the tools this environment provides, not look-alikes elsewhere on the PATH.

    git-annex starts its special remotes (`git-annex-remote-datalad-archives`) from the PATH:
    those of the project's environment must win over a DataLad installed for the user.
    """
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]])


@pytest.fixture
def native_annex(monkeypatch, tmp_path_factory):
    """The git-annex binary itself, not the wrapper of the `git-annex` package.

    The wrapper points libmagic at a database the system `file` cannot read, and every special
    remote git-annex starts inherits that, which breaks reading archives. The binary alone does
    not, but then it cannot tell text from binary files, so use it only where that is needed.
    """
    import git_annex

    binary = Path(git_annex.__file__).parent / "git-annex"
    shim = tmp_path_factory.mktemp("native-annex")
    (shim / "git-annex").symlink_to(binary)
    monkeypatch.setenv("PATH", os.pathsep.join([str(shim), os.environ["PATH"]]))


def slugify(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower())


ROOT = Path(__file__).parent.parent
DATA = Path(__file__).parent / "data"
DATASET_TEMPLATE = ROOT / "templates" / "dataset"
SOURCE_TEMPLATE = ROOT / "templates" / "source"
STUDY_TEMPLATE = ROOT / "templates" / "study"


class Project:
    """A ma-DMP whose templates and storage are local, for bootstrap tests."""

    def __init__(self, tmp_path: Path, example: str = "single_site.json", site: str = "a"):
        self.tmp = tmp_path
        self.collection = Collection(tmp_path / "collection")
        self.collection.add("tool", "1.0")
        self.storage = tmp_path / "storage"
        doc = json.loads((DATA / example).read_text())
        for ds in doc["dmp"]["dataset"]:
            # a dataset of instruments is a source dataset: its template carries the heuristic
            template = SOURCE_TEMPLATE if ds.get("technical_resource") else DATASET_TEMPLATE
            sources = ds["faire"].get("sources") or {}
            triggering = [
                r["identifier"]
                for r in ds.get("related_identifier") or []
                if r["relation_type"] == "IsDerivedFrom"
                and (sources.get(r["identifier"]) or {}).get("role") != "resource"
            ]
            ds["faire"]["template"] = {
                "repository": str(template),
                "version": "v1",
                "parameters": {
                    **self.collection.parameters("tool", "1.0"),
                    "source_dataset": triggering[0] if triggering else "dicoms",
                },
            }
        self.doc = doc
        self.madmp = tmp_path / "madmp.json"
        self.sites_dir = tmp_path / "sites"
        self.sites_dir.mkdir()
        self.hosts = {
            "Site storage": {"type": "directory", "parameters": {"directory": str(self.storage)}}
        }
        self.ws = Workspace(tmp_path / "ws")
        self.site_name = site
        self.write()

    @property
    def site(self) -> sites.SiteConfig:
        return sites.parse(self.site_config())

    def site_config(self) -> dict:
        config = {
            "site": self.site_name,
            "hosts": copy.deepcopy(self.hosts),
            "runners": {"tags": [f"site-{self.site_name}"]},
        }
        if getattr(self, "hub", None):
            config["hub"] = copy.deepcopy(self.hub)
        return config

    def write(self) -> None:
        self.madmp.write_text(json.dumps(self.doc, indent=2) + "\n")
        (self.sites_dir / f"{self.site_name}.yaml").write_text(yaml.safe_dump(self.site_config()))

    def add_instrument(self, instrument_id: str, site: str, dataset_id: str = "dicoms") -> None:
        """Declare another instrument for a stream, as the ma-DMP's technical resource."""
        dataset = next(
            d for d in self.doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == dataset_id
        )
        dataset["technical_resource"].append(
            {
                "name": instrument_id,
                "faire": {"instrument_id": instrument_id, "site": site},
            }
        )
        self.write()

    def add_external_store(self, dataset_id: str = "dicoms") -> Path:
        """A `collection` storage outside the site (a hub or an external host), taking anything."""
        folder = self.tmp / "storage-external"
        dataset = next(
            d for d in self.doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == dataset_id
        )
        extra = copy.deepcopy(dataset["distribution"][0])
        extra["title"] = "External storage"
        extra["host"] = {
            "title": "External storage",
            "faire": {"method": "directory", "parameters": {"directory": str(folder)}},
        }
        extra["faire"].pop("filter", None)
        dataset["distribution"].append(extra)
        self.write()
        return folder

    def add_stage_distribution(
        self,
        dataset_id: str,
        stage: str,
        title: str,
        filter: str | None = None,
        secrets: dict[str, str] | None = None,
        method: str = "directory",
        long_term: bool = False,
    ) -> Path:
        """Another distribution of a dataset, to a storage outside the site."""
        folder = self.tmp / f"storage-{slugify(title)}"
        dataset = next(
            d for d in self.doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == dataset_id
        )
        extra = copy.deepcopy(dataset["distribution"][0])
        extra["title"] = title
        host = {"method": method, "parameters": {"directory": str(folder)}}
        if secrets:
            host["secrets"] = secrets
        if long_term:
            host["long_term"] = True
        extra["host"] = {"title": title, "faire": host}
        extra["faire"] = {"stage": stage, **({"filter": filter} if filter else {})}
        dataset["distribution"].append(extra)
        self.write()
        return folder

    def add_sensitive_store(self, dataset_id: str = "dicoms") -> Path:
        """A second `collection` storage that takes only sensitive files, beside a general one."""
        folder = self.tmp / "storage-sensitive"
        self.hosts["Sensitive storage"] = {
            "type": "directory",
            "parameters": {"directory": str(folder)},
        }
        dataset = next(
            d for d in self.doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == dataset_id
        )
        general = dataset["distribution"][0]
        general["faire"]["filter"] = "not metadata=distribution-restrictions=sensitive"
        extra = copy.deepcopy(general)
        extra["title"] = "Sensitive working storage"
        extra["host"] = {"title": "Sensitive storage", "faire": {"site_dependent": True}}
        extra["faire"]["filter"] = "metadata=distribution-restrictions=sensitive"
        dataset["distribution"].append(extra)
        self.write()
        return folder

    @property
    def dmp(self) -> model.Dmp:
        return model.Dmp(copy.deepcopy(self.doc))

    def init(self, **kw):
        from faire import bootstrap

        return bootstrap.init(
            self.dmp,
            self.site,
            self.ws,
            self.madmp,
            str(STUDY_TEMPLATE),
            sites_dir=self.sites_dir,
            **kw,
        )


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path)
