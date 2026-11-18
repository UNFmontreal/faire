"""Instruments the ma-DMP does not declare yet.

A scanner may be swapped before anyone edits the plan. Indexing then still keeps the data: it
creates the instrument's instance, warns, and asks for the instance to be registered as a source
of every dataset derived from the stream, by pull request. Until a derived dataset has merged
that registration the instance is not one of its sources, so nothing is triggered and planning
sees none of its samples; once merged, planning finds them in the ordinary way. Merging
registers the instrument in the study too: `propose_instruments` opens the pull request that adds
it to the ma-DMP.
"""

from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from datalad.api import Dataset, clone

from faire import bootstrap, plan, sites
from faire import validate as validation
from faire.model import Dmp
from faire.platform import Platform, PullRequest

REGISTER = "register"
STUDY_REPO = bootstrap.STUDY_REPO


class UndeclaredError(RuntimeError):
    pass


@dataclass(frozen=True)
class Derived:
    """A dataset the new instance becomes a source of."""

    repo_name: str
    link: dict[str, Any]  # as recorded in `.faire/dataset.yaml`


def with_instrument(dmp: Dmp, stream: str, instrument: str, site: str) -> Dmp:
    """The plan with one more instrument for the stream."""
    document = copy.deepcopy(dmp.document)
    for dataset in document["dmp"]["dataset"]:
        if dataset["dataset_id"]["identifier"] == stream:
            dataset.setdefault("technical_resource", []).append(
                {"name": instrument, "faire": {"instrument_id": instrument, "site": site}}
            )
    return Dmp(document)


def derived_of(dmp: Dmp, site: str, stream: str, instance: str) -> list[Derived]:
    key = f"{stream}/{instance}"
    found = []
    for item in plan.creation_plan(dmp, site):
        for link in item.sources:
            if link.key == key:
                found.append(
                    Derived(item.repo_name, {"path": link.path, "key": link.key, "role": link.role})
                )
    return found


def create_instance(
    dmp: Dmp,
    site: sites.SiteConfig,
    platform: Platform,
    group: str,
    stream: str,
    instrument: str,
    work: Path,
) -> str:
    """Create the instance like bootstrap would have, with the same template and storage."""
    augmented = with_instrument(dmp, stream, instrument, site.site)
    instance = plan.instance_name(site.site, instrument)
    boot = bootstrap.Bootstrap(
        augmented,
        site,
        bootstrap.Workspace(work),
        work / "madmp.json",
        "",
        platform=platform,
        group=group,
    )
    item = boot.items[f"{stream}/{instance}"]
    boot.create_dataset(item)
    boot.publish_new(item)
    boot.configure_remotes(item)
    boot.publish_annex_state(item)
    boot.configure_platform(item)
    if not boot.ws.repo_path(item).exists():
        raise UndeclaredError(f"the instance {instance} could not be created")
    return item.repo_name


def _in_tree(ds: Dataset, ref: str, path: str) -> bool:
    return bool(ds.repo.call_git(["ls-tree", ref, "--", path]).strip())


def propose_registrations(
    dmp: Dmp,
    site: sites.SiteConfig,
    platform: Platform,
    group: str,
    stream: str,
    instrument: str,
    instance_url: str,
    work: Path,
) -> tuple[list[PullRequest], list[str]]:
    """Open a pull request on each derived dataset registering the instance as its source.

    Returns the pull requests, and the derived datasets that have already merged one.
    """
    instance = plan.instance_name(site.site, instrument)
    augmented = with_instrument(dmp, stream, instrument, site.site)
    opened: list[PullRequest] = []
    registered: list[str] = []
    for target in derived_of(augmented, site.site, stream, instance):
        repo = platform.get_repository(group, target.repo_name)
        if repo is None:
            raise UndeclaredError(f"{group}/{target.repo_name}: no such repository")
        ds = clone(source=repo.url, path=str(work / target.repo_name), result_renderer="disabled")
        ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
        if _in_tree(ds, "dev", target.link["path"]):
            registered.append(f"{group}/{target.repo_name}")
            continue
        branch = f"{REGISTER}/{instance}"
        heads = {r.split("/", 1)[1] for r in ds.repo.get_remote_branches() if "/" in r}
        if branch not in heads:
            bootstrap.propose_registration(ds, branch, target.link, instance_url, instance)
            ds.repo.call_git(["push", "origin", f"{branch}:{branch}"])
        opened.append(
            platform.ensure_pull_request(
                repo,
                branch,
                "dev",
                f"Register instrument instance {instance}",
                f"The instrument {instrument} of site {site.site} is not declared in the ma-DMP "
                f"yet. Its instance {instance} holds samples that wait for this registration; "
                f"merging it makes them sources of {target.repo_name}.",
            )
        )
    return opened, registered


# -- after the registration is merged -------------------------------------------------------


def registered_instances(ds: Dataset) -> list[dict[str, str]]:
    """The instrument instances registered as sources of the dataset, with what they record."""
    found = []
    for sub in ds.subdatasets(result_renderer="disabled", return_type="list"):
        rel = Path(sub["path"]).relative_to(ds.path).as_posix()
        parts = rel.split("/")
        if len(parts) != 3 or parts[0] != plan.SOURCEDATA:
            continue
        ds.get(rel, get_data=False, result_renderer="disabled")
        record = Path(sub["path"]) / bootstrap.RECORD
        if not record.exists():
            continue
        data = yaml.safe_load(record.read_text()) or {}
        if data.get("instrument"):
            found.append(
                {
                    "stream": data["stream"],
                    "instance": data["instance"],
                    "site": data["site"],
                    "instrument": data["instrument"],
                }
            )
    return found


def propose_instruments(
    ds: Dataset, platform: Platform, group: str, work: Path | None = None
) -> list[PullRequest]:
    """Open a pull request on the study adding each registered instrument the ma-DMP lacks."""
    work = work or Path(tempfile.mkdtemp(prefix="faire-madmp-"))
    wanted = registered_instances(ds)
    if not wanted:
        return []
    study = platform.get_repository(group, STUDY_REPO)
    if study is None:
        raise UndeclaredError(f"{group}/{STUDY_REPO}: no study superdataset on the platform")
    copy_ = clone(source=study.url, path=str(work / STUDY_REPO), result_renderer="disabled")
    copy_.repo.call_git(["checkout", "-q", "-B", "main", "origin/main"])
    path = Path(copy_.path) / "madmp.json"
    document = json.loads(path.read_text())
    dmp = Dmp(document)
    opened = []
    for entry in wanted:
        declared = {i.instrument_id for i in dmp.dataset(entry["stream"]).instruments}
        if entry["instrument"] in declared:
            continue
        branch = f"instrument/{entry['instrument']}"
        changed = with_instrument(dmp, entry["stream"], entry["instrument"], entry["site"])
        violations = validation.validate(changed.document)
        if violations:
            raise UndeclaredError(
                "adding the instrument would make the ma-DMP invalid: "
                + "; ".join(str(v) for v in violations)
            )
        repo = copy_.repo
        repo.call_git(["checkout", "-q", "-B", branch, "origin/main"])
        path.write_text(json.dumps(changed.document, indent=2) + "\n")
        copy_.save(
            message=f"Add the instrument {entry['instrument']} of site {entry['site']}",
            result_renderer="disabled",
        )
        repo.call_git(["push", "-f", "origin", f"{branch}:{branch}"])
        repo.call_git(["checkout", "-q", "main"])
        opened.append(
            platform.ensure_pull_request(
                study,
                branch,
                "main",
                f"Add the instrument {entry['instrument']} to the ma-DMP",
                f"Samples of the instrument {entry['instrument']} (site {entry['site']}) are "
                f"indexed in {entry['instance']} and registered as sources of "
                f"{Path(ds.path).name}; the ma-DMP does not declare it yet.",
            )
        )
        dmp = Dmp(document)  # each proposal starts from the plan as it is on `main`
    return opened
