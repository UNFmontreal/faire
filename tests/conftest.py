import copy
import json
from pathlib import Path

import pytest
import yaml

from faire import model, sites
from faire.bootstrap import Workspace

ROOT = Path(__file__).parent.parent
DATA = Path(__file__).parent / "data"
DATASET_TEMPLATE = ROOT / "templates" / "dataset"
STUDY_TEMPLATE = ROOT / "templates" / "study"


class Project:
    """A ma-DMP whose templates and storage are local, for bootstrap tests."""

    def __init__(self, tmp_path: Path, example: str = "single_site.json", site: str = "a"):
        self.tmp = tmp_path
        self.image = tmp_path / "image.sif"
        self.image.write_bytes(b"image\n")
        self.storage = tmp_path / "storage"
        doc = json.loads((DATA / example).read_text())
        for ds in doc["dmp"]["dataset"]:
            ds["faire"]["template"] = {
                "repository": str(DATASET_TEMPLATE),
                "version": "v1",
                "parameters": {
                    "container_url": str(self.image),
                    "container_version": "test-1",
                    "source_dataset": "dicoms",
                },
            }
        self.doc = doc
        self.madmp = tmp_path / "madmp.json"
        self.sites_dir = tmp_path / "sites"
        self.sites_dir.mkdir()
        self.site = sites.parse(
            {
                "site": site,
                "hosts": {
                    "Site storage": {
                        "type": "directory",
                        "parameters": {"directory": str(self.storage)},
                    }
                },
                "runners": {"tags": [f"site-{site}"]},
            }
        )
        self.ws = Workspace(tmp_path / "ws")
        self.write()

    def write(self) -> None:
        self.madmp.write_text(json.dumps(self.doc, indent=2) + "\n")
        config = {
            "site": self.site.site,
            "hosts": {
                "Site storage": {
                    "type": "directory",
                    "parameters": {"directory": str(self.storage)},
                }
            },
            "runners": {"tags": [f"site-{self.site.site}"]},
        }
        (self.sites_dir / f"{self.site.site}.yaml").write_text(yaml.safe_dump(config))

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
