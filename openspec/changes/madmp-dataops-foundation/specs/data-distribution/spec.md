## Purpose

Fulfils the distributions declared in the ma-DMP at the lifecycle stage they are bound to, so that data reaches each storage or repository when planned, its location stays tracked, and the ma-DMP reflects what was actually delivered.

## ADDED Requirements

### Requirement: Stage-triggered fulfilment
When data in a dataset enters a lifecycle stage, every distribution of that dataset bound to that stage SHALL be fulfilled for that data. Distributions bound to other stages SHALL NOT be fulfilled by that event.

#### Scenario: Release-stage distribution
- **WHEN** a dataset is released and has one distribution bound to `release` and one bound to `archival`
- **THEN** the released content is transferred to the host of the `release` distribution only

#### Scenario: Accepted-stage distribution
- **WHEN** a sample's pull request is merged and the dataset has a distribution bound to `accepted`
- **THEN** that sample's content is transferred to that distribution's host

### Requirement: Fulfilment command
The tool SHALL provide a command that fulfils the distributions of a dataset for a named stage, usable by CI jobs and by processes outside the platform such as ingestion.

#### Scenario: Ingestion uses the command
- **WHEN** an ingestion process runs the command for stage `collection` on a sample branch
- **THEN** the sample's content is transferred to the hosts of the `collection` distributions

### Requirement: Transfers tracked by git-annex
Where the host can be reached as a git-annex remote, content SHALL be transferred through git-annex so that the dataset records the presence of each file on that host. After a successful transfer, that record SHALL be available to every clone of the dataset.

#### Scenario: Location known after transfer
- **WHEN** a distribution to an annex-reachable host has been fulfilled
- **THEN** a fresh clone of the dataset reports that host as holding the transferred files and can retrieve them from it

### Requirement: Hosts without git-annex support
Where a host cannot be reached as a git-annex remote, the distribution SHALL be fulfilled by the host's own deposit method, and the resulting access location SHALL be recorded in the ma-DMP for that distribution.

#### Scenario: Deposit-only host
- **WHEN** a distribution targets a host with no git-annex support
- **THEN** the content is deposited and the distribution's access location in the ma-DMP points at the deposit

### Requirement: File filters honoured
A distribution's include and exclude filters SHALL be applied at file level. A file excluded by the filters SHALL NOT be transferred to that distribution's host by any fulfilment, including later ones.

#### Scenario: Sensitive files withheld
- **WHEN** a distribution excludes files whose metadata marks them as sensitive and the dataset contains such a file
- **THEN** after fulfilment the host holds the other files and does not hold the sensitive file

#### Scenario: File becomes sensitive later
- **WHEN** a file not yet transferred is marked sensitive before the next fulfilment
- **THEN** the next fulfilment does not transfer it

### Requirement: Credentials from the platform
Fulfilment SHALL obtain host credentials from the secrets named in the ma-DMP and stored outside it. A missing secret SHALL fail the fulfilment of that distribution with a message naming the secret, without printing any secret value.

#### Scenario: Missing secret
- **WHEN** a distribution's host names a secret that is not available to the job
- **THEN** that distribution's fulfilment fails, the message names the missing secret, and other distributions are still attempted

### Requirement: Persistent identifiers at release
When a release-stage distribution targets a host that provides a persistent identifier system, fulfilment SHALL obtain an identifier for the released dataset version and record it in that release's record in the ma-DMP.

#### Scenario: DOI minted
- **WHEN** a dataset is released to a host that mints DOIs
- **THEN** the dataset's release record in the ma-DMP contains the DOI of that release

### Requirement: Facts written back to the ma-DMP
After fulfilment, the tool SHALL update the ma-DMP in the study superdataset with the facts it established: the issue date of the distribution, its size, its access location and, for releases, the release record. Each update SHALL be a version-controlled change attributed to an automation identity, and the updated ma-DMP SHALL remain profile-conformant.

#### Scenario: Release recorded
- **WHEN** a release has been fulfilled for a dataset
- **THEN** the ma-DMP in the study superdataset has a new commit adding the release record and the distribution's issue date and size

### Requirement: Repeatable and resumable fulfilment
Fulfilling a distribution again SHALL transfer only content not yet present on the host and SHALL NOT duplicate identifiers or release records. A fulfilment interrupted part-way SHALL be completable by running it again.

#### Scenario: Re-run after interruption
- **WHEN** a fulfilment stopped after transferring half of the files is run again
- **THEN** only the remaining files are transferred and the ma-DMP holds a single record for the event

### Requirement: Archival distribution is self-sufficient
An archival-stage distribution SHALL deliver the dataset's complete version history, the content of every release subject to the distribution's filters, and the information needed to retrieve that content from the archival host alone.

#### Scenario: Restore from archive
- **WHEN** a dataset is restored from its archival host only
- **THEN** every released revision can be checked out and its unfiltered content retrieved
