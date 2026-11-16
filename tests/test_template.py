from pathlib import Path

import pytest
import yaml
from datalad.api import containers_list, create

from faire import containers, templates

TEMPLATE = Path(__file__).parent.parent / "templates" / "dataset"

pytestmark = pytest.mark.integration


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "image.sif"
    path.write_bytes(b"not a real image, only tracked\n")
    return path


def render_dataset(tmp_path, image, **extra):
    ds = create(str(tmp_path / "ds"), result_renderer="disabled")
    data = {
        "dataset_id": "standardized",
        "container_url": str(image),
        "container_version": "test-1",
        "source_dataset": "dicoms",
        **extra,
    }
    templates.render(str(TEMPLATE), ds, data)
    ds.save(message="render template", result_renderer="disabled")
    return ds


def test_render_registers_container(tmp_path, image):
    ds = render_dataset(tmp_path, image)
    assert containers.register(ds) == ["tool"]
    listed = containers_list(dataset=ds, result_renderer="disabled")
    assert [r["name"] for r in listed] == ["tool"]
    assert ds.repo.is_under_annex(".datalad/environments/tool/image")
    assert containers.register(ds) == []  # idempotent


def test_template_content(tmp_path, image):
    ds = render_dataset(tmp_path, image)
    root = Path(ds.path)
    rules = yaml.safe_load((root / ".faire/rules.yaml").read_text())
    assert [r["id"] for r in rules["rules"]] == ["process"]
    assert rules["rules"][0]["container"] == "tool"
    checks = {c["id"]: c["blocking"] for c in rules["checks"]}
    assert checks == {"layout": True, "protocol": False}
    assert "*.tsv merge=union" in (root / ".gitattributes").read_text()
    answers = yaml.safe_load((root / ".copier-answers.yml").read_text())
    assert answers["dataset_id"] == "standardized"
    assert "_src_path" in answers


def test_unpinned_registry_image_rejected():
    spec = containers.ContainerSpec("t", "docker://busybox:latest", "1")
    with pytest.raises(containers.ContainerError, match="digest"):
        containers.check_pinned(spec)
    with pytest.raises(containers.ContainerError, match="version"):
        containers.check_pinned(containers.ContainerSpec("t", "/x/img.sif", ""))
