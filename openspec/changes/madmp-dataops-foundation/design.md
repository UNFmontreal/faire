## Context

The repository is empty apart from OpenSpec scaffolding, so this is a greenfield design. Motivation and scope are in `proposal.md`; required behaviour is in `specs/`. Constraints that shape the approach:

- The RDA DMP Common Standard v1.3 schema allows additional properties but defines no extension mechanism, no dataset versions and no lifecycle stages. Its only native link between datasets is `dataset.related_identifier` with a DataCite relation type.
- Datasets are DataLad datasets following YODA: inputs are subdatasets, computations are `datalad run` / `datalad containers-run` records.
- Orchestration happens on a DevOps platform with CI runners. A neuroimaging proof of concept exists as GitLab CI templates (`ni-dataops/ci-pipelines`, branch `dev`). Its shared templates, BIDS and derivative pipelines and federation job were read; about half of the per-pipeline files were not. This design generalises it: pipeline logic moves from platform YAML into the tool, the heuristic `.derivatives` list is replaced by the ma-DMP, and its federation job (merge from the federated sibling, resolve, push) becomes the sync command.
- The STAMPED paper's normative requirements (S.1 to D.3) were read and are mapped in D26; the interactive checklist items were not.

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

- Acquisition and transfer of instrument data to the site. `faire index` starts from a local directory of received files. Scheduled probing of external storage and cross-modality fetches are later work, though a scheduled job can call `index` after its own fetch.
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
A site is an identifier plus runners, storage and secrets. Site files live in the study superdataset (`sites/<site>` as a working layout) and map site-dependent host names to concrete remotes and runner tags. Every command takes the site from its environment. Source data is organised per instrument, not per site (D28). The same model covers the hub-orchestrated deployment, where only job routing and storage differ per site.

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
Archival reuses the release machinery (first-use remote creation, per-site delivery, coordinator completion) for distributions bound to `archival`, whose hosts must be declared long-term in the ma-DMP: the standard's `host.certified_with` (CoreTrustSeal, ISO 16363 and others) counts, and an extension flag covers long-term hosts without certification. The only extra step is making subdataset references resolvable without the platform (D13).

### D25. The ma-DMP is edited by pull request
The study superdataset runs `faire validate` on pull requests touching the ma-DMP. In a federated study the hub's study superdataset is authoritative; sites install it and receive revisions by sync. In the hub-orchestrated deployment sites deploy only ingestion services and runners.

### D26. STAMPED conformance
Mapping of the paper's requirements to this change:

| Req. | Met by |
|---|---|
| S.1 | Sources, resources and containers are subdatasets of each dataset; the study superdataset gathers everything |
| S.2, D.3 | Bootstrap writes the ma-DMP license into each dataset with its SPDX identifier (REUSE-style) |
| T.1, T.2 | git and git-annex content addressing for every component |
| T.3, T.4 | `datalad run` / `containers-run` records; pinned sources, containers and template version. Indexing commits record the heuristic revision and sample entities; what happens before files reach the site is left to each ingestion tool |
| A.1 | Generated entry-point README per dataset; accepted results must be re-executable (`datalad rerun`) |
| A.2 | ma-DMP, rule file and `faire run` are executable specifications |
| M.1, M.2 | One dataset per ma-DMP dataset, linked as subdatasets |
| M.3 | License declared per dataset; compatibility is reported at release for human review, not checked automatically |
| M.4 | Partial by choice: source data is in separate per-instrument modules that stay at their site, but sensitive files inside a standardized dataset are separated by file-level filters and a sensitive-only remote, not by a separate module |
| P.1 to P.3 | Registered, digest-pinned containers; host specifics confined to site configuration |
| E.1 | `faire run` works in a throwaway clone on a runner |
| D.1 | Release check on every referenced component: in the release, declared restricted, or externally managed and answering at its pinned revision |
| D.2 | Not addressed: reproducible builds of container images belong to the container collections |

Containers are not copied at release: collections such as ReproNim containers, or collections shared across studies, have their own archival and persistence plans.
*Alternative:* pushing used container images with each release. Rejected per discussion: it duplicates shared collections and blurs who is responsible for them.

### D27. Generic indexer with a Python heuristic
`faire index <dir>` clones the site's source dataset, imports the heuristic module from that clone, and applies its optional functions (entities, pilot, keep, sensitive, placement, subdataset name, subdataset setup). The setup callback receives the freshly created subdataset and runs before any file is added, typically to write `.gitattributes`; its result is saved as its own commit. Without it the parent's `.gitattributes` is copied. It then saves with DataLad, optionally through git-annex's archive special remotes so that thousands of small files become a few bulk archives on storage while individual paths stay addressable (the setup callback configures it per source dataset; source streams are stored once and read once, when converted to standard data, so they are mostly dormant and archive bulk suits them), sets annex metadata for sensitive and pilot content before any copy, pushes content, then the subdataset, then the parent. Per-sample subdatasets are created with the same remote setup code as bootstrap, which is the main reuse argument. Indexed samples go straight to `dev` or `pilot` of the source dataset, as in the proof of concept where review happens on the standardized dataset; the push event carries the sample entities to the downstream trigger. The heuristic interface is expected to grow with new modalities, so every function is optional with a default.
*Alternatives:* leaving ingestion entirely to external tools (duplicates git, storage and platform handling in each); a declarative mapping file instead of Python (too weak for metadata extraction from instrument formats).

### D28. Instruments anchored on `technical_resource`
The standard's `dataset.technical_resource` ("equipment needed/used to create or process the data") holds each instrument: `name`, optional `technical_resource_id` for a persistent instrument identifier, and in the `faire` extension the instrument identifier and its site. The standard has no instrument type, model or site, hence the extension. All instruments of all sites are listed in the ma-DMP, since sites are fixed early in a study while instruments may be replaced.
A source dataset declaring instruments is one stream type (`dicoms`, `mri_raw`, `physio`, `eeg`): the data that one heuristic indexes and one tool converts (heudiconv, spec2nii, phys2bids and so on). One instrument may feed several streams. Each stream is realised as one repository per instrument, `<site>_<instrument>`, installed in derived datasets at `sourcedata/<stream type>/<site>_<instrument>` with only the last level a subdataset (which may itself hold per-sample subdatasets). A replaced scanner therefore gets its own dataset and history. Identity is the physical device; software versions are per-sample metadata written by the heuristic.
An undeclared instrument does not block indexing: the indexer creates the instance and opens a pull request on the derived (standardized) dataset to register it. Until that is merged the instance is not a source of anything, so its samples, pilot or production, trigger nothing; on merge they are triggered and a ma-DMP pull request is opened. This replaces the earlier per-site source dataset concept; sites remain only as storage mapping, runners and secrets.
Listing the containers a derived dataset uses as technical resources, written back by the tool, is a natural follow-up and is not part of this change.
*Alternatives:* concrete devices in site configuration with only a role in the ma-DMP (keeps the ma-DMP stable but hides the instruments from the plan); refusing undeclared instruments outright (cleaner but cumbersome when a scanner is swapped).

### D29. Plan, render, run
CI integration is three layers, only the second being platform-specific:

```
faire plan              -> neutral task list (JSON): id, rule, sample, site, order, artifacts
faire ci render         -> platform pipeline from the list
faire run --task <id>   -> one task in one job; `faire run --all` runs the list in-process
faire test --list / --check <id>, faire trigger
```

- **State-based planning.** A task is due when the inputs recorded in the rule's last run record for that sample differ from the current ones (make-like). This avoids depending on push events (unknown previous commit on new branches and force pushes, missed events), makes reprocessing and "waiting samples" ordinary cases, and stops loops: after a task commits, the next plan finds it up to date.
- **Rules.** Each dataset has a list of rules. Source-triggered rules produce a sample branch and pull request; content-triggered rules (t2wrecon, defacing, gradient unwarping in the proof of concept) commit to the pull request branch. Order on a branch is explicit in the rule file; tasks run consecutively and each sees the previous state. Optional steps simply drop out of the plan, so no rule keys on another's outputs. To prevent re-triggering, a rule's recorded inputs are compared ignoring changes made by itself or by rules ordered after it.
- **GitLab renderer.** A planning job writes a child pipeline as an artifact and triggers it (`strategy: depend`) so jobs appear in the branch or merge request pipeline. Order uses `needs`, serialisation on a branch uses `resource_group`, site routing uses runner tags, declared artifact paths become `artifacts:paths` with `when: always`, advisory checks use `allow_failure`. Downstream datasets are started with native multi-project trigger jobs. Child pipelines nest two levels, which plan, tasks and downstream trigger fit within.
- **Actions-style renderer (later).** GitHub, Forgejo and Gitea share the Actions workflow syntax, so one further renderer would cover all three: a planning job outputs the list and a matrix job fans out over it. A matrix cannot order its entries, so ordered tasks of one branch run inside one job; GitHub caps a matrix at 256 entries; downstream triggering uses `faire trigger` through the API.
- **Fallback.** One static job running `faire run --all` then `faire test`, for any platform. No parallelism, per-task logs or retries.
- **Pull request listing.** Paths a rule declares for listing are written by `faire run` into a pull request comment it owns and updates, linking to the job artifact or to the file on the branch.
- **Platform-native reporting (later).** The comment is the portable baseline; richer integration such as GitLab report artifacts or the Actions job summary can be added per renderer without changing the rule file.
- **Secrets on sample branches.** GitLab exposes protected variables only on protected branches, so `init` protects the tool's branch name patterns.
*Alternative:* one hand-written job per rule in each template. Rejected: duplication across templates and no fan-out per sample.

### D31. One `sync` command
`faire sync --stage <stage>` fulfils every distribution bound to the stage: `datalad push` / `git annex copy` for one-way hosts, and the merge, resolve, push exchange of D19 for the hub. One command keeps the mental model simple (a distribution is a distribution) and gives indexing, CI jobs and people the same entry point; `--distribution` narrows a run.

### D32. Human approval of merges
A pull request is merged only after a human approval, in addition to passing blocking checks; the platform configuration requires at least one approval on `dev` and `main`. Automatic merging when checks and quality metrics pass and there are no conflicts is a possible later policy and is not part of this change.
*Alternative:* automatic merge on green checks now. Deferred: quality metrics and their thresholds are not yet defined.

### D30. Native CI engines, not an external one
Considered using one external CI engine across all platforms (Woodpecker, Jenkins, Buildkite, or a portable pipeline engine such as Dagger inside any CI). Not adopted: it would move logs, artifacts and status away from the pull request, add a service and a second secret store to operate at each site, and none of them is better suited to HPC runners than the platforms' own. Because the plan is neutral, an external engine would only be one more renderer if that changes. This assessment is from general knowledge and was not verified against current versions of those tools.

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
- [The heuristic is arbitrary Python executed with storage and platform credentials] → it is only loaded from the source dataset's own versioned content, changes to it go through pull requests, and dry-run mode shows its decisions.
- [Indexed data enters `dev` of the source dataset without review] → accepted; source data is site-local and review takes place on the first derived dataset.
- [A wrong instrument identifier from the heuristic silently creates a spurious instance] → an undeclared instrument always produces a visible pull request and a warning, and its samples trigger nothing until that pull request is reviewed and merged.
- [State-based planning must read run records for every sample on each update, which may be slow on large datasets] → cache the per-sample state in the dataset and restrict planning to samples touched since the cached revision.
- [Ignoring changes by later rules could hide a real need to rerun an earlier rule] → manual reprocessing remains available for that case.
- [STAMPED conformance is by design, not measured] → D26 records the mapping; running the STAMPED checklist against the example project is a documentation task.
- [Externally managed containers may disappear after a release] → their persistence is their owners' responsibility; the release check only proves they were retrievable at release time and the report records location and revision.

## Migration Plan

Not applicable: nothing exists to migrate. The existing GitLab proof of concept is not converted by this change.

## Open Questions

- Later: the policy, quality metrics and thresholds under which pull requests could be merged automatically (D32).
- Whether Forgejo and Gitea Actions support a matrix computed by a previous job, to be checked before an Actions-style renderer is planned.
- The exact signature of the heuristic functions, to be refined with each new modality.
- The exact format of the protocol expectations derived from pilots, which is left to each template's protocol tool.
- Which long-term hosts to support first for archival.
