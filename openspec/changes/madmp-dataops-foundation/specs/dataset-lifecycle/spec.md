## Purpose

Defines how data moves through each dataset and across the provenance graph for continuous data delivery: sample by sample through reviewed pull requests, cascading to downstream datasets, then released together and finally archived.

## ADDED Requirements

### Requirement: Branch model
Every dataset SHALL have a `dev` branch that accumulates accepted samples and a `main` branch that holds released states. Changes SHALL reach `dev` only through merged pull requests or, in a federated study, through synchronisation with the hub, and `main` only through the release process.

#### Scenario: Direct push refused
- **WHEN** a contributor pushes a commit directly to `dev` or `main` of a dataset
- **THEN** the platform rejects the push

### Requirement: Lifecycle stages
The lifecycle of a sample in a dataset SHALL consist of the stages `collection` (the sample exists on a feature branch), `review` (a pull request for it is open against `dev`), `accepted` (the pull request is merged), `release` (the sample is part of a tagged state of `main`) and `archival` (the project has been archived). The tool SHALL be able to report the current stage of any sample in any dataset.

#### Scenario: Stage query
- **WHEN** a sample has an open pull request against `dev` in a dataset
- **THEN** the tool reports that sample's stage in that dataset as `review`

### Requirement: Sample branch interface
A sample SHALL enter a root dataset as a feature branch carrying the sample's identifier, pushed by an ingestion process outside the scope of this tool, together with the annexed content reachable from a storage the CI runners can read. Pushing such a branch SHALL result in an open pull request against `dev`.

#### Scenario: New sample pushed
- **WHEN** an ingestion process pushes a feature branch for sample `S` to a root dataset
- **THEN** a pull request from that branch to `dev` is open and identifies sample `S`

### Requirement: Review checks and inline processing
An open pull request SHALL run the checks and inline processing steps defined by the dataset's template, such as compliance checks, quality control and de-identification. Inline processing results SHALL be committed to the pull request's branch with their provenance recorded. The pull request SHALL NOT be mergeable while a required check fails.

#### Scenario: Failed compliance check
- **WHEN** a required check fails on a pull request
- **THEN** the pull request cannot be merged and the failure is visible on it

#### Scenario: Inline processing
- **WHEN** a template defines a de-identification step and a pull request is opened
- **THEN** the branch gains a commit with the processed files and a machine-readable record of the command and container that produced them

### Requirement: Identifiable originals retained locally
When inline processing replaces a file with a de-identified version, the original SHALL be kept as annexed content marked sensitive, retrievable from the dataset history at the site that acquired it, and SHALL NOT be purged. Dataset templates SHALL ensure that files which may hold identifiable content are annexed and never stored directly in version history.

#### Scenario: Going back to the original
- **WHEN** a file was de-identified in a pull request and a site operator later checks out the revision before de-identification
- **THEN** the original content can be retrieved from that site's sensitive storage

#### Scenario: Original not shared
- **WHEN** the dataset is synchronised with the hub or released
- **THEN** the original content is not transferred

### Requirement: Protocol conformance is advisory
A check that a sample contains the files and metadata the study protocol expects SHALL report each deviation on the pull request as a warning and SHALL NOT prevent merging. The decision to accept a deviating sample belongs to the data curator.

#### Scenario: Missing acquisition
- **WHEN** a sample lacks a file the protocol expects
- **THEN** the pull request shows a warning naming the missing file and can still be merged

#### Scenario: Deviating sample accepted
- **WHEN** a curator merges a sample lacking the inputs a downstream dataset requires
- **THEN** that downstream dataset opens no pull request for the sample and reports no failure

### Requirement: Pilot stream
Every dataset SHALL have a `pilot` branch separate from `dev`. A sample marked as pilot at ingestion SHALL be proposed by pull request to `pilot` and SHALL cascade to the `pilot` branches of downstream datasets. Pilot samples SHALL NOT enter `dev` or `main` and SHALL NOT be part of any release. The annexed content of pilot samples SHALL stay on the storage of the site that acquired it and SHALL NOT be transferred to the hub, to another site or to any external host; the version history of `pilot` MAY be shared. The protocol expectations used to check production samples SHALL be established from accepted pilot samples and kept in the dataset under version control.

#### Scenario: Pilot sample
- **WHEN** an ingestion process pushes a feature branch for a sample marked as pilot
- **THEN** the pull request targets `pilot`, and after merge the downstream pull request for that sample also targets `pilot`

#### Scenario: Pilot content stays local
- **WHEN** a site synchronises a dataset holding pilot samples with the hub
- **THEN** the hub receives the `pilot` branch history and no annexed content of the pilot samples

#### Scenario: Protocol from pilots
- **WHEN** a pilot sample has been accepted and the protocol expectations derived from it are committed
- **THEN** subsequent production samples are checked against those expectations

#### Scenario: Pilot excluded from release
- **WHEN** a study is released
- **THEN** no pilot sample is contained in any dataset's tagged revision

### Requirement: Computations recorded with provenance
Every computation that produces or changes dataset content SHALL be executed through `datalad run` or `datalad containers-run`, so that its command, inputs, outputs and container are recorded in the dataset history.

#### Scenario: Pipeline output
- **WHEN** a pipeline job produces derivative files for a sample
- **THEN** the commit that adds them carries a run record from which the computation can be re-executed

### Requirement: Per-sample cascade to direct downstream datasets
When a sample's pull request is merged into `dev` of a dataset, each dataset for which it is a triggering source SHALL be triggered for that sample. The triggered dataset SHALL run its processing rule for that sample, as specified by the processing-rules capability, resulting in a pull request against its own `dev` whose `sourcedata/` reference is the merged state. Datasets further downstream SHALL be triggered only when that pull request is merged in turn.

#### Scenario: One level
- **WHEN** the pull request for sample `S` is merged in dataset `raw`, and `standardized` is derived from `raw`
- **THEN** `standardized` has an open pull request for sample `S` whose `sourcedata/raw` reference is the merged state of `raw`

#### Scenario: No skipping of levels
- **WHEN** the pull request for sample `S` is merged in `raw`, and `analysis` is derived from `standardized` only
- **THEN** `analysis` is not triggered until the pull request for `S` is merged in `standardized`

### Requirement: One open pull request per sample per dataset
A dataset SHALL have at most one open pull request per sample. A trigger for a sample that already has an open pull request in the dataset SHALL update that pull request instead of opening another.

#### Scenario: Second source arrives
- **WHEN** a dataset with two sources is triggered for sample `S` by the second source while its pull request for `S` from the first source is still open
- **THEN** the existing pull request is updated with the second source's merged state and the processing rule runs again on it

### Requirement: Upstream correction retriggers downstream
When a correction to an already accepted sample is merged into `dev` of a dataset, the directly derived datasets SHALL be triggered for that sample again and SHALL open a new pull request replacing the sample's previous results.

#### Scenario: Corrected sample
- **WHEN** a fix for accepted sample `S` is merged in `raw`
- **THEN** `standardized` opens a new pull request for `S` computed from the corrected state

### Requirement: Manual reprocessing
The tool SHALL provide a way for a maintainer to trigger a dataset's pipeline for one or more named samples, producing pull requests in the same way as an upstream merge.

#### Scenario: Bug-fix reprocessing
- **WHEN** a maintainer requests reprocessing of samples `S1` and `S2` in a dataset
- **THEN** that dataset has one open pull request for each of the two samples

### Requirement: Coordinated study release
A release SHALL be started manually by pushing a release tag to the study superdataset; in a federated study only the coordinator may do so. The release SHALL bring `dev` into `main` in every dataset, tag every dataset with the release identifier, and record in the study superdataset the released revision of each dataset. No release SHALL be started automatically.

#### Scenario: Release of the whole study
- **WHEN** a maintainer pushes release tag `R` to the study superdataset and all release conditions hold
- **THEN** every dataset has tag `R` on `main`, and the study superdataset at `R` references exactly those tagged revisions

### Requirement: Release consistency conditions
A release SHALL be refused, with no dataset tagged, unless every derived dataset's `sourcedata/` references equal the revisions of its source datasets being released. The refusal SHALL list every dataset that is behind its sources.

#### Scenario: Downstream behind
- **WHEN** a release is started while `standardized` references an older state of `raw` than the one being released
- **THEN** no dataset is tagged and the report names `standardized` and `raw`

#### Scenario: Consistent graph
- **WHEN** every derived dataset references the current `dev` state of each of its sources
- **THEN** the release proceeds

### Requirement: Multiple releases
A dataset SHALL support any number of successive releases. Each release SHALL be recorded in the ma-DMP as a release record for each dataset, and earlier releases SHALL remain retrievable by their release identifier.

#### Scenario: Second release
- **WHEN** a second release is completed
- **THEN** each dataset's ma-DMP entry lists two release records and both tagged revisions can be checked out

### Requirement: Archival independent of the platform
Archival SHALL be started manually for the whole study and SHALL proceed like a release, fulfilling the distributions bound to `archival`. After archival, the study superdataset and every dataset SHALL be retrievable from the archival hosts, with full history, released content and the ma-DMP, and with references between datasets that resolve without access to the DevOps platform.

#### Scenario: Platform gone
- **WHEN** the archived study superdataset is cloned from the archival host on a machine with no access to the DevOps platform
- **THEN** every subdataset can be installed and the content of every release can be retrieved
