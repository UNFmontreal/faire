## Why

Research projects that manage their data with DataLad and YODA still wire up datasets, provenance links, execution environments, CI pipelines and publication steps by hand, and the data management plan stays a document nobody executes. Making a machine-actionable DMP (RDA DMP Common Standard) the declarative source for the whole project lets one file bootstrap the datasets, drive continuous data delivery from collection to archival, and stay truthful because the tooling writes facts back to it. The result is meant to satisfy FAIR and the STAMPED principles by construction.

## What Changes

- Define a **profile of the RDA DMP Common Standard v1.3** that adds, in one namespaced extension, what the standard lacks: the template each dataset is created from, the lifecycle stage at which each distribution is fulfilled, file-level include and exclude filters, non-secret host transfer parameters, the entities that identify a sample, site-scoped datasets, the hub and coordinator of a federated study, and a record of dataset releases. Provenance between datasets uses the standard's own `related_identifier` with `IsDerivedFrom`.
- Add a **command-line tool and library** that validates a ma-DMP against the profile and bootstraps a project from it: one DataLad dataset per ma-DMP dataset rendered from its git template (with its containers registered), source datasets installed as subdatasets under `sourcedata/`, and a study superdataset that tracks the ma-DMP and presents all datasets in a user-oriented layout.
- Make bootstrap a **reconcile** operation: re-running it after an additive ma-DMP edit (new derivative dataset, new distribution) converges the project; edits that would alter an existing dataset's specification are reported, not applied.
- Define the **dataset lifecycle** on a DevOps platform: each collected sample arrives as a feature branch and pull request into `dev`; checks and inline processing run in the pull request; merging triggers the directly downstream datasets, which produce their own pull requests for the same sample; a manually pushed tag on the study superdataset releases all datasets together; archival makes the project usable without the platform.
- Define **stage-triggered distribution**: at each lifecycle stage, the distributions bound to it are fulfilled through git-annex transfers where the host allows, honouring the file filters, minting persistent identifiers where the host supports them, and writing dates, sizes and identifiers back to the ma-DMP.
- Define **processing rules**: the ma-DMP says what is derived from what (with triggering and resource-only sources), the dataset template says how, and one `run` command executes a dataset's rule for one sample, in CI or by hand, handling input retrieval, storage credentials, provenance capture, result push and the pull request. Samples lacking a rule's required inputs are skipped silently.
- Add a **pilot stream** separate from production, from which the protocol expectations checked on production samples are established; protocol deviations warn the curator without blocking.
- Define optional **federation**: several sites share one ma-DMP with per-site configuration, keep source and sensitive data local, process their own samples, synchronise non-sensitive datasets in both directions through a hub with defined conflict resolution, and release together under one coordinator.
- Add a generic **indexer**: an `index` command that records newly received instrument data in a site's source dataset, guided by a Python heuristic carried by the dataset template (sample entities, pilot status, file selection, sensitive marking, layout, optional per-sample subdataset), then pushes content and history, which starts the pipeline.
- Define a **platform abstraction** for repository creation, branch protection, CI variables and cross-dataset triggers, with GitLab as the reference implementation.

Out of scope for this change: instrument-specific acquisition and transfer of data to the site (indexing starts from a local directory of received files), scheduled probing of external storage, group-level derivatives triggered by upstream releases, a Forgejo implementation, and domain-specific templates beyond one minimal reference template.

## Capabilities

### New Capabilities

- `madmp-profile`: the extension of the RDA DMP Common Standard and the validation rules a project ma-DMP must satisfy.
- `project-bootstrap`: creating and reconciling the datasets, their provenance subdatasets, their containers and the study superdataset from a ma-DMP.
- `dataset-lifecycle`: the branch model, the lifecycle stages, per-sample cascading through the provenance graph, coordinated study releases and archival.
- `data-distribution`: fulfilling the ma-DMP's distributions at their lifecycle stage, with file filters, identifier minting and write-back of facts.
- `processing-rules`: how a dataset's computation for one sample is declared and executed through a single run command.
- `federation`: multi-site operation through a hub: site configuration, two-way synchronisation, conflict resolution and coordinated release.
- `data-indexing`: bringing received instrument data into a site's source dataset with a heuristic-driven generic indexer.
- `platform-orchestration`: the DevOps platform operations the tool relies on (repositories, protections, CI configuration, cross-dataset triggers), independent of a specific platform.

### Modified Capabilities

None. The project has no existing specs.

## Impact

- **New code**: this repository is empty apart from OpenSpec scaffolding; the change introduces the tool, the profile schema, a reference dataset template and a reference study template.
- **Dependencies**: DataLad, datalad-container, git-annex, a template renderer (copier), a JSON Schema validator, and the GitLab API for the reference platform implementation.
- **External systems**: a DevOps platform with CI runners (optionally on an HPC cluster through SLURM), the storage and repository hosts named in each project's ma-DMP, and identifier services of those hosts.
- **Interoperability**: a profile-conformant ma-DMP remains a valid RDA DMP Common Standard v1.3 document; tools unaware of the extension can still read it.
- **Security and privacy**: host credentials never appear in the ma-DMP; sensitive files are excluded from distributions by filter, and how identifiable content is purged after de-identification is left as an open design question.
