from pathlib import Path

import pytest
import yaml
from datalad.api import containers_list, create

from faire import containers, templates
from rulefix import Collection

TEMPLATE = Path(__file__).parent.parent / "templates" / "dataset"

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(tmp_path):
    col = Collection(tmp_path / "collection")
    col.add("tool", "1.0")
    return col


def render_dataset(tmp_path, collection, **extra):
    ds = create(str(tmp_path / "ds"), result_renderer="disabled")
    data = {
        "dataset_id": "standardized",
        **collection.parameters("tool", "1.0"),
        "source_dataset": "dicoms",
        **extra,
    }
    templates.render(str(TEMPLATE), ds, data)
    ds.save(message="render template", result_renderer="disabled")
    return ds


def test_render_registers_container(tmp_path, collection):
    ds = render_dataset(tmp_path, collection)
    assert containers.register(ds) == ["tool"]
    listed = containers_list(dataset=ds, result_renderer="disabled")
    assert [r["name"] for r in listed] == ["tool"]
    assert listed[0]["path"].endswith("code/containers/images/tool--1.0.sif")
    assert containers.register(ds) == []  # idempotent


def test_template_content(tmp_path, collection):
    ds = render_dataset(tmp_path, collection)
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
