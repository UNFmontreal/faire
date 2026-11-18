"""The cascade: a merged pull request starts the datasets derived from it, one level at a time."""

import copy
import json

import pytest
import yaml
from click.testing import CliRunner

from faire import execute, indexing, planning, rules
from faire.ciplan import CiPlan
from faire.cli import main
from faire.platform.fake import FakePlatform
from faire.render import gitlab
from indexfix import received, request
from lifefix import GROUP, fire_downstream, invoke, merge, runner
from rulefix import make_derived, write_source
from test_captured import CAPTURED

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


# -- 8.1a output samples, not trigger samples --------------------------------------------------


def test_downstream_is_triggered_for_the_output_sample_not_the_trigger_sample(tmp_path):
    src = write_source(tmp_path / "src", {"PAT42/0301/a.txt": "01 01 first\n"})
    ds = make_derived(tmp_path, src, rules=copy.deepcopy(CAPTURED))
    rule_set = rules.load(ds.path)
    outcome = execute.run_task(ds, rule_set, "convert:subject=PAT42,session=0301", env={})
    ds.repo.call_git(["checkout", "dev"])
    before = ds.repo.get_hexsha()
    ds.repo.call_git(["merge", "--no-ff", "-q", "-m", "merge", outcome.branch])

    env = {"FAIRE_DATASET": "derived", "FAIRE_SITE": "a"}
    out = CliRunner().invoke(
        main,
        [
            "plan",
            "--dataset",
            ds.path,
            "--no-update",
            "--downstream",
            "g/analysis",
            "--since",
            before,
        ],
        env=env,
    )
    assert out.exit_code == 0, out.output
    plan = CiPlan.from_json(out.output)
    assert plan.samples == ("subject=01,session=01",)  # what was written, not PAT42
    jobs = yaml.safe_load(gitlab.render_yaml(plan))
    triggers = {n: j for n, j in jobs.items() if isinstance(j, dict) and "trigger" in j}
    assert len(triggers) == 1
    [job] = triggers.values()
    assert job["variables"]["FAIRE_SAMPLE"] == "subject=01,session=01"
    assert "PAT42" not in json.dumps(job)


def test_several_output_samples_start_the_downstream_dataset_once_each():
    plan = CiPlan(
        "raw",
        "dev",
        downstream=("g/std",),
        samples=("subject=01,session=01", "subject=01,session=02"),
    )
    jobs = {n: j for n, j in gitlab.render(plan).items() if n != "stages"}
    assert sorted(j["variables"]["FAIRE_SAMPLE"] for j in jobs.values()) == [
        "subject=01,session=01",
        "subject=01,session=02",
    ]
    assert len(jobs) == 2


def test_pilot_pipelines_start_the_pilot_branch_of_downstream_datasets():
    jobs = gitlab.render(CiPlan("raw", "pilot", downstream=("g/std",)))
    assert jobs["downstream-g-std"]["trigger"]["branch"] == "pilot"
    assert (
        gitlab.render(CiPlan("raw", "dev", downstream=("g/std",)))["downstream-g-std"]["trigger"][
            "branch"
        ]
        == "dev"
    )


# -- 8.2 triggering sources only, one level per merge ------------------------------------------


def test_only_triggering_sources_list_their_downstream_datasets(study, platform):
    def downstream(name):
        return platform.get_variables(platform.get_repository(GROUP, name))["FAIRE_DOWNSTREAM"]

    assert downstream("dicoms-a_PrismaFit16001") == f"{GROUP}/standardized"
    assert downstream("standardized") == f"{GROUP}/analysis"
    assert downstream("atlas") == ""  # a resource of `analysis`: its changes trigger nothing


def test_the_cascade_advances_one_level_per_merge(study, platform, tmp_path, monkeypatch):
    indexing.index(request(study, platform, received(tmp_path, {"01/003/scan.txt": "scan\n"})))
    started = {p[0] for p in platform.pipelines}
    assert started == {f"{GROUP}/standardized"}  # not `analysis`: levels are not skipped

    ds = runner(study, platform, tmp_path, "standardized", "dev")
    [task] = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    out = invoke(
        platform, monkeypatch, "run", "--task", task.id, "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/standardized",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    assert {p[0] for p in platform.pipelines} == started  # a pull request opened: still nothing

    before = merge(ds, planning.branch_of(task.sample))
    pipelines = fire_downstream(platform, monkeypatch, "standardized", ds, before, tmp_path)
    assert [(p, b) for p, b, _ in pipelines] == [(f"{GROUP}/analysis", "dev")]
    assert pipelines[0][2]["FAIRE_SAMPLE"] == "subject=01,session=003"
    assert {p[0] for p in platform.pipelines} == started | {f"{GROUP}/analysis"}
