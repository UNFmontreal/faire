"""Helpers for the lifecycle tests: what a runner at the site does around the tool."""

from pathlib import Path

from click.testing import CliRunner
from datalad.api import Dataset, clone

from faire import remotes
from faire.cli import main
from faire.platform import factory

GROUP = "example-study"


def enable_site_remotes(ds, project) -> None:
    """Reach the site's storage for the dataset and for the sources installed under it."""
    dmp = project.dmp

    def enable(target, dataset_id, repo_name):
        known = remotes.names(target)
        for spec in remotes.specs(dmp.dataset(dataset_id), repo_name, project.site):
            if spec.name in known:
                remotes.enable(target, spec)

    own = _id_of(ds)
    enable(ds, own, own)
    for sub in ds.subdatasets(result_renderer="disabled", return_type="list"):
        rel = Path(sub["path"]).relative_to(ds.path).parts
        if rel[0] != "sourcedata":
            continue
        target = Dataset(sub["path"])
        if not target.is_installed():
            continue
        if len(rel) == 3:  # <stream>/<instance>
            enable(target, rel[1], f"{rel[1]}-{rel[2]}")
        else:
            enable(target, rel[1], rel[1])


def _id_of(ds) -> str:
    import yaml

    return yaml.safe_load((Path(ds.path) / ".faire/dataset.yaml").read_text())["dataset_id"]


def runner(project, platform, tmp_path, repo_name, branch, name=None):
    """A clone of a dataset at `branch`, with its sources and the site's storage ready."""
    repo = platform.get_repository(GROUP, repo_name)
    ds = clone(
        repo.url, str(tmp_path / (name or f"runner-{repo_name}")), result_renderer="disabled"
    )
    ds.repo.call_git(["checkout", "-q", "-B", branch, f"origin/{branch}"])
    ds.get("sourcedata", get_data=False, recursive=True, result_renderer="disabled")
    enable_site_remotes(ds, project)
    return ds


def invoke(platform, monkeypatch, *args, env=None):
    """Run a `faire` command with the platform standing for the one the CI is on."""
    monkeypatch.setattr(factory, "connect", lambda name, url, token=None: platform)
    return CliRunner().invoke(main, list(args), env=env)


def merge(ds, feature: str, into: str = "dev") -> str:
    """Accept a pull request: merge the sample branch into `into` and push; returns the old tip."""
    ds.repo.call_git(["fetch", "origin"])
    ds.repo.call_git(["checkout", "-q", "-B", into, f"origin/{into}"])
    before = ds.repo.get_hexsha()
    ds.repo.call_git(["merge", "--no-ff", "-q", "-m", f"Merge {feature}", f"origin/{feature}"])
    ds.repo.call_git(["push", "origin", into])
    return before


def fire_downstream(platform, monkeypatch, repo_name, ds, since, tmp_path):
    """The pipeline of a protected branch: plan, render, and the trigger jobs it contains.

    Returns the pipelines started, as (project, branch, variables).
    """
    import yaml

    repo = platform.get_repository(GROUP, repo_name)
    variables = platform.get_variables(repo)
    env = {
        "FAIRE_DATASET": variables["FAIRE_DATASET"],
        "FAIRE_DOWNSTREAM": variables["FAIRE_DOWNSTREAM"],
        "FAIRE_SITE": "a",
    }
    out = invoke(
        platform, monkeypatch, "plan", "--dataset", ds.path, "--no-update", "--since", since,
        env=env,
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    plan_file = tmp_path / f"plan-{repo_name}.json"
    plan_file.write_text(out.output)
    out = invoke(platform, monkeypatch, "ci", "render", "--platform", "gitlab", str(plan_file))
    assert out.exit_code == 0, out.output
    started = []
    for job in yaml.safe_load(out.output).values():
        if isinstance(job, dict) and "trigger" in job:
            target = job["trigger"]["project"]
            group, _, name = target.rpartition("/")
            sent = {
                k: ds.repo.get_hexsha() if v == "$CI_COMMIT_SHA" else v
                for k, v in job["variables"].items()
            }
            platform.trigger_pipeline(
                platform.get_repository(group, name), job["trigger"]["branch"], sent
            )
            started.append((target, job["trigger"]["branch"], sent))
    return started


def accept_through_chain(project, platform, monkeypatch, tmp_path) -> None:
    """The indexed sample is processed and accepted in `standardized`, then in `analysis`."""
    from faire import planning, rules

    args = ["--platform-url", "https://x"]
    for name in ("standardized", "analysis"):
        ds = runner(project, platform, tmp_path, name, "dev", name=f"chain-{name}")
        [task] = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
        invoke(
            platform, monkeypatch, "run", "--task", task.id, "--dataset", ds.path, *args,
            "--project", f"{GROUP}/{name}",
        )  # fmt: skip
        before = merge(ds, planning.branch_of(task.sample))
        if name == "standardized":
            fire_downstream(platform, monkeypatch, name, ds, before, tmp_path)
