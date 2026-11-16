"""Creation plan: what repositories a ma-DMP implies for one site, in provenance order.

A plain dataset is one repository named after its identifier. A dataset that declares
instruments is a *stream*: it has no repository of its own, it is realised by one instance
per instrument, named `<site>_<instrument>`, each its own repository `<stream>-<instance>`.
Derived datasets install every instance of a stream they derive from at
`sourcedata/<stream>/<site>_<instrument>`; any other source at `sourcedata/<source id>`.
"""

from __future__ import annotations

from dataclasses import dataclass

from faire.model import Dataset, Dmp

SOURCEDATA = "sourcedata"


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class SourceLink:
    key: str  # key of the item that is the source
    path: str  # where it is installed in the derived dataset
    role: str  # "triggering" or "resource"

    @property
    def triggering(self) -> bool:
        return self.role == "triggering"


@dataclass(frozen=True)
class Item:
    key: str  # dataset identifier, or `<stream>/<instance>` for an instance
    dataset_id: str  # identifier of the ma-DMP dataset it realises
    repo_name: str
    kind: str  # "dataset" or "instance"
    create: bool  # False for another site's instance, referenced but not created
    sources: tuple[SourceLink, ...] = ()
    stream: str | None = None
    instance: str | None = None
    site: str | None = None
    instrument: str | None = None

    @property
    def is_instance(self) -> bool:
        return self.kind == "instance"


def instance_name(site: str, instrument_id: str) -> str:
    return f"{site}_{instrument_id}"


def _instance_items(dataset: Dataset, site: str) -> list[Item]:
    items = []
    for instrument in dataset.instruments:
        name = instance_name(instrument.site, instrument.instrument_id)
        items.append(
            Item(
                key=f"{dataset.id}/{name}",
                dataset_id=dataset.id,
                repo_name=f"{dataset.id}-{name}",
                kind="instance",
                create=instrument.site == site,
                stream=dataset.id,
                instance=name,
                site=instrument.site,
                instrument=instrument.instrument_id,
            )
        )
    return items


def _topological(dmp: Dmp) -> list[Dataset]:
    datasets = dmp.datasets
    by_id = {d.id: d for d in datasets}
    order: list[Dataset] = []
    state: dict[str, int] = {}

    def visit(ds: Dataset, trail: tuple[str, ...]) -> None:
        if state.get(ds.id) == 2:
            return
        if state.get(ds.id) == 1:
            raise PlanError("provenance cycle: " + " -> ".join((*trail, ds.id)))
        state[ds.id] = 1
        for source in dmp.sources_of(ds):
            visit(by_id[source.dataset_id], (*trail, ds.id))
        state[ds.id] = 2
        order.append(ds)

    for ds in datasets:
        visit(ds, ())
    return order


def creation_plan(dmp: Dmp, site: str) -> list[Item]:
    """Items to realise, every source before anything derived from it."""
    realised: dict[str, list[Item]] = {}
    plan: list[Item] = []
    for ds in _topological(dmp):
        if ds.is_instrument_source:
            items = _instance_items(ds, site)
        else:
            links: list[SourceLink] = []
            for source in dmp.sources_of(ds):
                for item in realised[source.dataset_id]:
                    path = (
                        f"{SOURCEDATA}/{item.stream}/{item.instance}"
                        if item.is_instance
                        else f"{SOURCEDATA}/{item.dataset_id}"
                    )
                    links.append(SourceLink(item.key, path, source.role))
            items = [
                Item(
                    key=ds.id,
                    dataset_id=ds.id,
                    repo_name=ds.id,
                    kind="dataset",
                    create=True,
                    sources=tuple(links),
                )
            ]
        realised[ds.id] = items
        plan.extend(items)
    return plan
