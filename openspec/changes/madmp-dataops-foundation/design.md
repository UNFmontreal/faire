## Context

The repository is empty apart from OpenSpec scaffolding, so this is a greenfield design. Motivation and scope are in `proposal.md`; required behaviour is in `specs/`. Constraints that shape the approach:

- The RDA DMP Common Standard v1.3 schema allows additional properties but defines no extension mechanism, no dataset versions and no lifecycle stages. Its only native link between datasets is `dataset.related_identifier` with a DataCite relation type.
- Datasets are DataLad datasets following YODA: inputs are subdatasets, computations are `datalad run` / `datalad containers-run` records.
- Orchestration happens on a DevOps platform with CI runners. A neuroimaging proof of concept exists as GitLab CI templates (`ni-dataops/ci-pipelines`, branch `dev`). Its shared templates, BIDS and derivative pipelines and federation job were read; about half of the per-pipeline files were not. This design generalises it: pipeline logic moves from platform YAML into the tool, the heuristic `.derivatives` list is replaced by the ma-DMP, and its federation job (merge from the federated sibling, resolve, push) becomes the sync command.
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
The tool is named `faire` ("doing" in French, echoing FAIR). Profile data lives under a single property named `faire` on `dmp`, `dataset`, `distribution` and `host`. Removing it yields a plain standard document, which is easy to test.
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
For datasets with several sources, each triggering source's merge triggers the same sample branch; the rule's required inputs (D15) decide whether it runs, so the run is skipped until the last needed source arrives.
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

### D15. Processing rule file plus a `run` command
The template renders a rule file in each derived dataset: container name, command, per-source input patterns, required inputs, output patterns, all parameterised by the study's sample entities. `run --sample <entities>` does everything a proof-of-concept job did in YAML: sample branch, pointer update, `datalad get` of resolved inputs only, `datalad containers-run`, push to working storage and origin, pull request. CI definitions shrink to one call, which is what makes a second platform cheap. Required inputs that match nothing end the run with status zero and no change; this replaces the per-sample `.derivatives` heuristics.
*Alternative:* rules in the ma-DMP. Rejected: the ma-DMP should say what is derived from what, and commands and patterns change with the template version, which is already pinned per dataset.

### D16. Triggering versus resource sources
Marked in the extension per source. Both are `sourcedata/` subdatasets; only triggering sources appear in the upstream's downstream-trigger configuration.

### D17. Pilot stream
A long-lived `pilot` branch per dataset, never merged into `dev`. Ingestion marks pilot samples; the pull request target follows the mark. The template's protocol tool (forbids for MRI in the proof of concept) derives the expectations from pilot data and commits them; on production pull requests the same tool runs as a non-blocking check. Blocking checks and advisory checks are distinguished in the template.

### D18. Sites and site configuration
A site is an identifier plus runners, storage and secrets. Site files live in the study superdataset (`sites/<site>` as a working layout) and map site-dependent host names to concrete remotes and runner tags. Every command takes the site from its environment. Site-scoped datasets are instantiated as `<dataset>_<site>`. The same model covers the hub-orchestrated deployment, where only job routing and storage differ per site.

### D19. Federation as a two-way distribution with a sync command
`sync` walks federated datasets in provenance order and, per branch (`dev`, `main`, `pilot`): merges from the hub, resolves, pushes to the hub. Union merges come from the template's `.gitattributes`. Subdataset pointer conflicts are resolved by ancestry, never by date: the descendant wins, and for diverged pointers the already-synchronised source head is used. Anything else aborts that dataset's sync without pushing. git-annex location tracking travels with the `git-annex` branch, so sites learn where content is even when the hub is git-only. Received samples are not reprocessed because downstream triggers fire on pull request merges, not on sync merges.
*Alternative:* resolve pointer conflicts by commit date, as "most recent" might suggest. Rejected: dates are unreliable across sites, ancestry is not.

### D20. Federated release
The ma-DMP names the coordinator (a site, or the hub in the hub-orchestrated deployment). The coordinator's release pipeline checks that the hub holds every site's accepted work, tags, and pushes to the hub. Each site's sync picks up the tag and runs release-stage fulfilment for the files it holds. The coordinator polls completeness through git-annex location tracking (`git annex find` on the tag with the distribution's filter, not present on the release remote), then creates or finalises the external repository, obtains identifiers and writes the ma-DMP. Only the coordinator writes the ma-DMP, which removes cross-site conflicts on that file.

### D21. Remotes created per stage
Bootstrap creates remotes for `collection`, `review` and `accepted` distributions with `git annex wanted` set from the filters (for example a general store with `not metadata=...sensitive` and a sensitive-only store, as in the proof of concept). `release` and `archival` remotes are created by the first fulfilment at that stage.

### D22. Identifiable content is annexed, kept local, never purged
Templates route every file that may hold identifiable content to the annex through `.gitattributes`, so nothing identifiable enters git history. De-identification commits a new version; the original key is tagged sensitive and lives only on the site's sensitive-only remote, so it remains retrievable locally (for example to return to non-defaced images) while wanted rules keep it off every shared or external remote.

### D23. Pilot content is local
`pilot` history is synchronised, but pilot content is excluded from the hub and all external remotes, since pilots may be acquired under separate ethics. Implemented by tagging pilot keys at ingestion and in pilot runs, and adding that tag to the exclusion of every non-site remote.

### D24. Archival is a release to long-term hosts
Archival reuses the release machinery (first-use remote creation, per-site delivery, coordinator completion) for distributions bound to `archival`, whose hosts must be declared long-term in the ma-DMP. The only extra step is making subdataset references resolvable without the platform (D13).

### D25. The ma-DMP is edited by pull request
The study superdataset runs `faire validate` on pull requests touching the ma-DMP. In a federated study the hub's study superdataset is authoritative; sites install it and receive revisions by sync. In the hub-orchestrated deployment sites deploy only ingestion services and runners.

## Risks / Trade-offs

- [The profile depends on fields of v1.3 that were read from the README, not the schema files] → the first task checks `dataset.related_identifier` and additional-property rules against the published schema before the profile schema is written.
- [Concurrent write-backs to the ma-DMP conflict] → serialise write-back jobs and retry on non-fast-forward.
- [Many samples produce many pull requests and pipelines] → accepted for now; batching several samples in one pull request is compatible with the branch interface and can be added later.
- [Study-wide release is blocked by any single lagging dataset] → the refusal lists exactly which datasets are behind; a partial release is deliberately not offered.
- [Platform neutrality limited by GitLab-only features such as nested groups and multi-project pipelines] → the interface asks for a "grouping" and a "trigger pipeline in another repository" operation; a platform lacking them fails the capability check instead of degrading silently.
- [A site's storage is usually reachable only from its own network, so off-site runners may fail to fetch inputs] → stated as a deployment condition; the run command fails early naming the unreachable storage.
- [A federated release stalls if one site never delivers its files] → release status names the sites owing files; the coordinator does not mint identifiers until complete.
- [A sync conflict outside the declared rules blocks a dataset at one site] → the hub and protected branches are left untouched and the conflict is reported for manual resolution.
- [Sensitive file names and history still reach other sites even though content does not] → accepted; templates must keep sensitive information out of file names and tracked text files.
- [STAMPED conformance is asserted, not checked] → mapping the checklist to requirements is deferred until its item text is available.

## Migration Plan

Not applicable: nothing exists to migrate. The existing GitLab proof of concept is not converted by this change.

## Open Questions

- Whether merging a pull request needs human approval in addition to passing checks, or whether that is a per-template policy.
- The exact format of the protocol expectations derived from pilots, which is left to each template's protocol tool.
- Which long-term hosts to support first for archival.
- Mapping of the STAMPED checklist items to requirements once the checklist text is available.
