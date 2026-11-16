from pathlib import Path

import pytest
from datalad.api import create

from faire import study, templates

TEMPLATE = Path(__file__).parent.parent / "templates" / "study"

pytestmark = pytest.mark.integration


def test_render_yields_valid_datalad_dataset(tmp_path):
    ds = create(str(tmp_path / "study"), result_renderer="disabled")
    templates.render(str(TEMPLATE), ds, {"study_name": "Demo"})
    ds.save(message="render study template", result_renderer="disabled")
    assert ds.is_installed() and not ds.repo.dirty
    root = Path(ds.path)
    assert (root / "sites" / "README.md").exists()
    assert (root / ".copier-answers.yml").exists()
    layout = study.load(root)
    assert layout.name == "Demo"
    assert (layout.madmp, layout.sites) == ("madmp.json", "sites")
    assert layout.path_of("standardized") == "standardized"


def test_layout_pattern_and_override(tmp_path):
    ds = create(str(tmp_path / "study"), result_renderer="disabled")
    templates.render(
        str(TEMPLATE), ds, {"study_name": "Demo", "layout_pattern": "derivatives/{id}"}
    )
    layout = study.load(ds.path)
    assert layout.path_of("x") == "derivatives/x"
    assert study.StudyLayout("d", "m", "s", overrides={"x": "sourcedata/x"}).path_of("x") == (
        "sourcedata/x"
    )
