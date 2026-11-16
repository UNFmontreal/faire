## Context

The repository is empty apart from OpenSpec scaffolding, so this is a greenfield design. Motivation and scope are in `proposal.md`; required behaviour is in `specs/`. Constraints that shape the approach:

- The RDA DMP Common Standard v1.3 schema allows additional properties but defines no extension mechanism, no dataset versions and no lifecycle stages. Its only native link between datasets is `dataset.related_identifier` with a DataCite relation type.
- Datasets are DataLad datasets following YODA: inputs are subdatasets, computations are `datalad run` / `datalad containers-run` records.
- Orchestration happens on a DevOps platform with CI runners. A GitLab proof of concept exists outside this repository (nested groups, multi-project pipelines); it was not inspected for this design.
- STAMPED was read only at the level of its seven one-line definitions; its MUST/SHOULD/MAY checklist was not retrievable and is not yet mapped to requirements.

```
                 study superdataset  (ma-DMP + user-oriented layout)
                 /        |         \
              raw   standardized   analysis        <- registered subdatasets
               ^          |  ^          |
               +----------+  +----------+           <- sourcedata/ subdatasets
              IsDerivedFrom  IsDerivedFrom             (provenance graph)

 sample S:  raw: feature/S -PR-> dev --merge--> triggers standardized
            standardized: feature/S -PR-> dev --merge--> triggers analysis
 release:   tag R on study superdataset -> dev->main + tag R in every dataset
```

## Goals / Non-Goals

**Goals:**

- One Python package providing a library and a command-line tool; CI jobs call the same commands a person would.
- The ma-DMP stays a valid standard document; the profile is a strict superset.
- Platform specifics isolated behind one interface, with GitLab implemented first.
- Everything testable locally without a platform (local-only bootstrap, bare repositories as hosts).

**Non-Goals:**

- Ingestion of instrument data. Only the sample branch interface is fixed. Scheduled probing of external storage and cross-modality fetches are later work.
- Derivatives triggered by an upstream release (group-level analyses). The trigger model leaves room for it; nothing is built.
- Forgejo or GitHub implementations.
- Domain templates (BIDS, heudiconv, and so on). One minimal reference dataset template and one study template are delivered to exercise the system.
- Propagating template updates into existing datasets.
- A graphical interface or a DMP authoring tool.

## Decisions

### D1. Extension carried in one namespaced property
Profile data lives under a single property (working name `dataops`) on `dataset`, `distribution` and `host`. Removing it yields a plain standard document, which is easy to test.
*Alternatives:* top-level prefixed fields on each entity (noisier, harder to strip); a sidecar file (two sources of truth, breaks "bootstrap from the ma-DMP").

### D2. Provenance uses the standard's `related_identifier`
`relation_type: IsDerivedFrom` with the source's `dataset_id`. Links to datasets of the same plan use the same identifier type as the plan's own `dataset_id` values; an `IsDerivedFrom` of that type that resolves to nothing is an error, while links with external identifier types (a DOI of a reused public dataset) are ignored by bootstrap.
*Alternative:* a `sources` list in the extension. Rejected because standard-only tools would lose the provenance graph.

### D3. Pipeline version is dataset identity
A new pipeline version is a new dataset entry, so a study keeps one processing version per dataset and additive evolution covers upgrades. Bug fixes inside a dataset are handled by manual reprocessing, not by a new entry.

### D4. Fixed stage vocabulary
`collection`, `review`, `accepted`, `release`, `archival`. A fixed list lets templates, pipelines and validators rely on stage names. This was left undecided in discussion and is a proposed default; making it extensible later would be a compatible change (a wider enumeration).
*Alternative:* stages defined per ma-DMP. Rejected for now: every template would need to adapt to arbitrary stage names.

### D5. Templates rendered once with copier
Each dataset is rendered with copier from a git repository at a pinned tag or commit. Copier records its answers file in the dataset, which gives the required record of template, version and parameters and keeps the door open for `copier update` in the edge cases where template updates are wanted.
*Alternative:* cookiecutter (no update path, no answers file by default); cloning a template repository and keeping shared history (merges across unrelated datasets become confusing).

### D6. Containers come with the template
The template declares its containers; rendering registers them with datalad-container, pinned by digest, as subdatasets of container repositories. Bootstrap verifies with `datalad containers-list`.

### D7. Two independent structures
The provenance graph is realised by `sourcedata/<source-id>` subdatasets inside each derived dataset. The study superdataset registers all datasets flat or nested according to a study template (BIDS-study-like layouts fit here) and holds the ma-DMP. A dataset therefore appears both under the study superdataset and under each consumer's `sourcedata/`; all point at the same platform repository.

### D8. Reconcile by comparing recorded facts
Each dataset stores a small machine-readable record of the ma-DMP entry it was created from (identifier, template, version, parameters, sources). Reconcile computes the plan from the ma-DMP, compares with those records and the platform state, and applies only additions. Differences on existing datasets are reported with a non-zero exit.

### D9. Cascade driven by merge events, one level at a time
A merge into `dev` runs a job in the upstream repository that triggers each direct downstream pipeline with `sample` and `revision` variables. The downstream job creates or updates `feature/<sample>`, bumps the `sourcedata/` pointer, runs the template's pipeline through `datalad containers-run`, pushes, and opens or updates the pull request. The list of downstream datasets is derived from the ma-DMP and set as CI configuration by bootstrap, so adding a derivative needs no change to upstream templates.
For datasets with several sources, each source's merge triggers the same sample branch; whether the inputs are complete enough to run is decided by the dataset's pipeline, which may end without results until the last source arrives.
*Alternative:* a central orchestrator service watching all repositories. Rejected: more to operate, and platform pipelines already provide this.

### D10. Release is study-wide and manual
A tag pushed on the study superdataset starts a release pipeline that (1) checks consistency: every `sourcedata/` pointer equals the source's `dev` head being released; (2) merges `dev` into `main` and tags each dataset in provenance order; (3) updates the study superdataset's subdataset pointers; (4) starts release-stage distributions; (5) writes release records to the ma-DMP. Step 1 failing stops everything before any tag. Because all datasets are tagged together from consistent pointers, every released derivative references released inputs without a separate pinning rule.
*Alternative:* per-dataset release tags with a rule that sources be released first. Rejected per discussion: releasing all assets at once is simpler to reason about.

### D11. Distribution through git-annex first
Hosts reachable as special remotes or siblings are configured at bootstrap; fulfilment is `datalad push` / `git annex copy` with the filter translated to a git-annex matching expression (path globs and `metadata=` terms) and also set as the remote's wanted content, so later pushes cannot leak excluded files. Hosts without annex support get a small deposit adapter interface; none is implemented in this change beyond what the reference tests need.

### D12. Write-back by the automation identity
Fulfilment jobs commit ma-DMP updates to the study superdataset on `dev` through the automation identity, serialised by the platform (one write-back job at a time) to avoid conflicting edits. The file is re-validated before commit.

### D13. Archival exports a platform-free copy
Archival pushes each repository and its annexed content to the archival hosts and rewrites subdataset URLs to relative ones in the archived copy, so the tree resolves from the archive alone.

### D14. Platform interface
One interface with the operations listed in `specs/platform-orchestration`, a GitLab implementation, and an in-memory fake used by tests. Capability checks happen before any change is made.

## Risks / Trade-offs

- [The profile depends on fields of v1.3 that were read from the README, not the schema files] → the first task checks `dataset.related_identifier` and additional-property rules against the published schema before the profile schema is written.
- [Concurrent write-backs to the ma-DMP conflict] → serialise write-back jobs and retry on non-fast-forward.
- [Many samples produce many pull requests and pipelines] → accepted for now; batching several samples in one pull request is compatible with the branch interface and can be added later.
- [De-identification in a pull request leaves identifiable content reachable through earlier commits or annex keys] → not solved here; see Open Questions. Until then, templates should keep identifiable content out of platform-visible storage or drop the keys explicitly.
- [Study-wide release is blocked by any single lagging dataset] → the refusal lists exactly which datasets are behind; a partial release is deliberately not offered.
- [Platform neutrality limited by GitLab-only features such as nested groups and multi-project pipelines] → the interface asks for a "grouping" and a "trigger pipeline in another repository" operation; a platform lacking them fails the capability check instead of degrading silently.
- [STAMPED conformance is asserted, not checked] → mapping the checklist to requirements is deferred until its item text is available.

## Migration Plan

Not applicable: nothing exists to migrate. The existing GitLab proof of concept is not converted by this change.

## Open Questions

- Final name of the tool and of the extension namespace (`dataops` is a working name).
- How identifiable content is purged after de-identification (dropping annex keys, rewriting the feature branch before merge, or keeping raw content in a restricted dataset upstream).
- Whether merging a pull request needs human approval in addition to passing checks, or whether that is a per-template policy.
- Which archival hosts and formats to support first.
- Mapping of the STAMPED checklist items to requirements once the checklist text is available.
