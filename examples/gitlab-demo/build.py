"""Build the files of the GitLab demo: a ma-DMP, a site configuration and a container collection.

    python examples/gitlab-demo/build.py OUTPUT_DIR

The ma-DMP is the single-site example of the tests with its dataset templates pointing at the
templates of this repository. Nothing here contains a credential.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tests" / "data" / "single_site.json"
SITE = "a"


def make_collection(path: Path):
    """A local container collection holding one placeholder image of `tool` 1.0.

    A real study points at a shared collection (such as ReproNim's) that runners can reach.
    """
    from datalad.api import containers_add, create

    path.parent.mkdir(parents=True, exist_ok=True)
    ds = create(str(path), result_renderer="disabled")
    image = path.parent / "tool-1.0.img"
    image.write_bytes(b"demo container image\n")
    containers_add(
        "tool",
        dataset=ds,
        url=str(image),
        image="images/tool--1.0.sif",
        call_fmt="{cmd}",
        result_renderer="disabled",
    )
    return ds, ds.repo.get_hexsha()


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    collection, revision = make_collection(out / "collection")
    doc = json.loads(SOURCE.read_text())
    doc["dmp"]["title"] = "Example single-site study (faire GitLab demo)"
    for dataset in doc["dmp"]["dataset"]:
        dataset["faire"]["template"] = {
            "repository": str(ROOT / "templates" / "dataset"),
            "version": "v1",
            "parameters": {
                "collection_source": str(collection.path),
                "collection_revision": revision,
                "container_version": "1.0",
                "source_dataset": "dicoms",
            },
        }
    (out / "madmp.json").write_text(json.dumps(doc, indent=2) + "\n")
    sites = out / "sites"
    sites.mkdir(exist_ok=True)
    storage = out / "storage"
    (sites / f"{SITE}.yaml").write_text(
        yaml.safe_dump(
            {
                "site": SITE,
                "hosts": {
                    "Site storage": {"type": "directory", "parameters": {"directory": str(storage)}}
                },
                "runners": {"tags": [f"site-{SITE}"]},
            }
        )
    )


if __name__ == "__main__":
    build(Path(sys.argv[1]))
