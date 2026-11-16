## Purpose

Defines the profile of the RDA DMP Common Standard that a project ma-DMP must follow so that tooling can bootstrap, operate and publish the project's datasets from it, while the document stays readable by standard-only tools.

## ADDED Requirements

### Requirement: Conformance to the base standard
A profile-conformant ma-DMP SHALL be a valid document under the RDA DMP Common Standard version 1.3 JSON schema. All profile-specific information SHALL be carried in a single namespaced extension property on the entities it extends, so that removing that property leaves a valid standard document with no other change.

#### Scenario: Standard-only validation
- **WHEN** a profile-conformant ma-DMP is validated against the unmodified RDA DMP Common Standard v1.3 schema
- **THEN** validation succeeds

#### Scenario: Base standard violation
- **WHEN** a ma-DMP is missing a field the base standard requires
- **THEN** profile validation fails and reports the location of the missing field

### Requirement: Dataset identity
Each dataset in the ma-DMP SHALL have an identifier that is unique within the document and stable across ma-DMP revisions. The profile SHALL use this identifier for all references between datasets.

#### Scenario: Duplicate identifier
- **WHEN** two datasets in the ma-DMP carry the same identifier
- **THEN** validation fails and names the duplicated identifier

### Requirement: Dataset template declaration
Each dataset SHALL declare, in the extension, the git template it is created from: the template's repository location, a pinned version of that template, and the parameter values used to render it.

#### Scenario: Missing template
- **WHEN** a dataset has no template declaration
- **THEN** validation fails and names the dataset

#### Scenario: Unpinned template
- **WHEN** a dataset's template declaration gives a repository location without a pinned version
- **THEN** validation fails and names the dataset

### Requirement: License on every dataset
Each dataset SHALL declare a license by a resolvable identifier.

#### Scenario: Missing license
- **WHEN** a dataset declares no license
- **THEN** validation fails and names the dataset

#### Scenario: Unresolvable license
- **WHEN** a dataset's license is given as free text with no resolvable identifier
- **THEN** validation fails and names the dataset

### Requirement: Provenance links between datasets
A dataset derived from other datasets of the project SHALL declare each source with the standard's `related_identifier` using the relation type `IsDerivedFrom` and the source dataset's identifier. The set of all such links in a ma-DMP SHALL form a directed acyclic graph. A dataset with no such link is a root dataset holding collected data.

#### Scenario: Source not in the plan
- **WHEN** a dataset declares `IsDerivedFrom` with an identifier that the project marks as internal but that matches no dataset in the ma-DMP
- **THEN** validation fails and names both the dataset and the unresolved identifier

#### Scenario: Cycle
- **WHEN** the provenance links form a cycle
- **THEN** validation fails and lists the datasets in the cycle

#### Scenario: Multiple sources
- **WHEN** a dataset declares `IsDerivedFrom` links to two datasets of the plan
- **THEN** validation succeeds and both are reported as its sources

### Requirement: Pipeline version is part of dataset identity
A dataset SHALL represent the output of one version of its processing pipeline. Output of a different pipeline version SHALL be declared as a separate dataset with its own identifier.

#### Scenario: New pipeline version
- **WHEN** a project adopts a new version of a pipeline while keeping the output of the previous one
- **THEN** the ma-DMP contains two datasets with the same sources and different identifiers and template versions

### Requirement: Lifecycle stage of a distribution
Each distribution SHALL declare, in the extension, the lifecycle stage at which it is fulfilled. The stage SHALL be one of `collection`, `review`, `accepted`, `release`, `archival`.

#### Scenario: Unknown stage
- **WHEN** a distribution declares a stage outside the allowed values
- **THEN** validation fails and reports the distribution and the invalid value

#### Scenario: Several distributions at different stages
- **WHEN** a dataset declares one distribution at stage `accepted` and another at stage `release`
- **THEN** validation succeeds

### Requirement: Archival distributions target long-term hosts
A distribution bound to `archival` SHALL target a host that the ma-DMP declares as supporting long-term preservation.

#### Scenario: Long-term host
- **WHEN** an `archival` distribution targets a host declared as supporting long-term preservation
- **THEN** validation succeeds

#### Scenario: Ordinary host
- **WHEN** an `archival` distribution targets a host with no long-term preservation declaration
- **THEN** validation fails and names the distribution and the host

### Requirement: File filters of a distribution
A distribution MAY declare, in the extension, include and exclude filters that select files by path pattern and by file metadata. A distribution without filters SHALL cover all files of the dataset.

#### Scenario: Exclusion by metadata
- **WHEN** a distribution declares an exclude filter on files whose metadata marks them as sensitive
- **THEN** validation succeeds and the filter is reported as part of that distribution

#### Scenario: Malformed filter
- **WHEN** a filter expression cannot be parsed
- **THEN** validation fails and reports the distribution and the expression

### Requirement: Host transfer parameters without secrets
A distribution's host MAY declare, in the extension, the transfer method and the parameters needed to reach it. The ma-DMP SHALL NOT contain credentials; a parameter that requires a secret SHALL name the secret instead of holding its value.

#### Scenario: Secret by reference
- **WHEN** a host needs an access token
- **THEN** the ma-DMP holds only the name under which the platform stores that token

#### Scenario: Inline credential
- **WHEN** a host parameter declared as secret holds a literal value instead of a name
- **THEN** validation fails and reports the host

### Requirement: Release records
The extension SHALL allow each dataset to carry a list of releases. Each release record SHALL hold a release identifier, a date, the dataset revision released and the persistent identifiers minted for it. Release records SHALL be written by tooling, and a ma-DMP with no release records SHALL be valid.

#### Scenario: Dataset with two releases
- **WHEN** a dataset has been released twice
- **THEN** its extension lists two release records in release order, each with its own revision and identifiers

### Requirement: Triggering and resource sources
The extension SHALL mark each source of a dataset as either triggering or resource-only. A source with no mark SHALL be triggering. A derived dataset SHALL have at least one triggering source.

#### Scenario: Atlas as a resource
- **WHEN** a dataset declares one triggering source and an atlas dataset marked resource-only
- **THEN** validation succeeds and the atlas is reported as a resource of that dataset

#### Scenario: Only resources
- **WHEN** every source of a derived dataset is marked resource-only
- **THEN** validation fails and names the dataset

### Requirement: Sample entities
The ma-DMP SHALL declare, once for the study, the ordered list of entity names that identify a sample. All datasets of the study SHALL use these names.

#### Scenario: Entities declared
- **WHEN** the ma-DMP declares the sample entities `subject` and `session`
- **THEN** validation succeeds and tooling identifies every sample by a value for each of the two

#### Scenario: No entities
- **WHEN** the ma-DMP declares no sample entity
- **THEN** validation fails

### Requirement: Site-scoped datasets
The extension SHALL allow a dataset to be marked as site-scoped, meaning one instance of it exists per site. A site-scoped dataset SHALL NOT have a distribution to the hub or to any `release`-stage host. A dataset derived from a site-scoped dataset has every site's instance as a source.

#### Scenario: Instrument source data
- **WHEN** a root dataset is marked site-scoped and has only distributions to site storage
- **THEN** validation succeeds

#### Scenario: Site-scoped dataset with an external distribution
- **WHEN** a site-scoped dataset declares a distribution bound to `release`
- **THEN** validation fails and names the dataset and the distribution

### Requirement: Site-dependent hosts
The extension SHALL allow a distribution's host to be declared as site-dependent, in which case the ma-DMP gives only a host name and each site's configuration supplies the actual storage.

#### Scenario: Working storage per site
- **WHEN** a distribution bound to `review` names a site-dependent host
- **THEN** validation of the ma-DMP succeeds without any storage location for that host

### Requirement: Hub and two-way distributions
The ma-DMP MAY declare one hub and one coordinator for the study. A distribution MAY be declared two-way, and a two-way distribution SHALL target the hub. A study that declares a hub SHALL declare a coordinator.

#### Scenario: Federated dataset
- **WHEN** a dataset declares a two-way distribution to the declared hub with a filter excluding sensitive files
- **THEN** validation succeeds and the dataset is reported as federated

#### Scenario: Two-way distribution elsewhere
- **WHEN** a distribution to a host other than the hub is declared two-way
- **THEN** validation fails and names the distribution

#### Scenario: Hub without coordinator
- **WHEN** the ma-DMP declares a hub and no coordinator
- **THEN** validation fails

### Requirement: Validation command
The tool SHALL provide a command that validates a ma-DMP against the base standard and the profile, reports every violation with its location in the document, and exits with a non-zero status when any violation exists.

#### Scenario: Valid document
- **WHEN** the command is run on a profile-conformant ma-DMP
- **THEN** it reports success and exits with status zero

#### Scenario: Several violations
- **WHEN** the command is run on a ma-DMP with three independent violations
- **THEN** all three are reported in a single run
