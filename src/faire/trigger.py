"""Start the planning pipelines of the datasets directly derived from a dataset."""

from __future__ import annotations

from faire.platform import Platform, PlatformError

DEFAULT_REF = "dev"


def trigger_downstream(
    platform: Platform,
    downstream: list[str],
    upstream: str,
    revision: str,
    sample: str | None = None,
    ref: str = DEFAULT_REF,
    extra: dict[str, str] | None = None,
) -> list[str]:
    """Start a pipeline in each downstream repository (`group/name`); return pipeline ids.

    The pipeline only receives which dataset changed and at which revision; what is due is
    decided by planning from the downstream dataset's state, so a lost trigger is recovered by
    starting that pipeline again by any means.
    """
    platform.require(["trigger_pipeline"])
    variables = {"FAIRE_UPSTREAM": upstream, "FAIRE_REVISION": revision, **(extra or {})}
    if sample:
        variables["FAIRE_SAMPLE"] = sample
    ids = []
    for target in downstream:
        group, _, name = target.rpartition("/")
        repo = platform.get_repository(group, name)
        if repo is None:
            raise PlatformError(f"downstream repository {target!r} does not exist")
        ids.append(platform.trigger_pipeline(repo, ref, variables))
    return ids
