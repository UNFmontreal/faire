"""Build the files of the GitLab demo: a ma-DMP, a site configuration and a container image.

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


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    image = out / "image.sif"
    image.write_bytes(b"demo container image\n")
    doc = json.loads(SOURCE.read_text())
    doc["dmp"]["title"] = "Example single-site study (faire GitLab demo)"
    for dataset in doc["dmp"]["dataset"]:
        dataset["faire"]["template"] = {
            "repository": str(ROOT / "templates" / "dataset"),
            "version": "v1",
            "parameters": {
                "container_url": str(image),
                "container_version": "demo-1",
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
