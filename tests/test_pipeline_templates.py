from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent / "templates" / "dataset" / "template"
ENTRY = ROOT / ".gitlab-ci.yml"
FALLBACK = ROOT / ".faire" / "ci" / "single-job.gitlab-ci.yml"


def scripts(doc):
    for job in doc.values():
        if isinstance(job, dict):
            yield from job.get("script", [])


@pytest.mark.parametrize("path", [ENTRY, FALLBACK])
def test_pipelines_contain_no_logic(path):
    doc = yaml.safe_load(path.read_text())
    lines = list(scripts(doc))
    assert lines
    for line in lines:
        # only invocations of the tool, with at most an output redirection
        assert line.startswith("faire "), line
        assert not any(tok in line for tok in ("&&", "||", ";", "$(", "if ", "for ")), line
    text = path.read_text()
    assert "rules:" not in text.replace("# ", "")  # no conditional job logic


def test_entry_pipeline_plans_renders_and_triggers_child():
    doc = yaml.safe_load(ENTRY.read_text())
    assert doc["plan"]["script"] == [
        "faire plan --json > plan.json",
        "faire ci render --platform gitlab plan.json > child-pipeline.yml",
    ]
    trigger = doc["run"]["trigger"]
    assert trigger["strategy"] == "depend"
    assert trigger["include"][0] == {"artifact": "child-pipeline.yml", "job": "plan"}
    assert doc["plan"]["artifacts"]["when"] == "always"


def test_fallback_runs_everything_in_one_job():
    doc = yaml.safe_load(FALLBACK.read_text())
    assert doc["faire"]["script"] == ["faire run --all", "faire test"]


def test_study_template_validates_madmp_on_merge_requests():
    path = ROOT.parent.parent / "study" / "template" / ".gitlab-ci.yml"
    doc = yaml.safe_load(path.read_text())
    assert doc["validate-madmp"]["script"] == ["faire validate madmp.json"]
