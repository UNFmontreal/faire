## Purpose

Turns a profile-conformant ma-DMP into a working project: one DataLad dataset per planned dataset, linked by provenance, with execution environments registered, gathered under a study superdataset, and kept in step with later additive edits of the ma-DMP.

## ADDED Requirements

### Requirement: Bootstrap from a ma-DMP
The tool SHALL create, from a valid ma-DMP, one DataLad dataset for each dataset in the plan. Bootstrap SHALL refuse to run on a ma-DMP that fails profile validation.

#### Scenario: Fresh project
- **WHEN** bootstrap is run on a valid ma-DMP declaring three datasets
- **THEN** three DataLad datasets exist, each recording the identifier of the ma-DMP dataset it realises

#### Scenario: Invalid plan
- **WHEN** bootstrap is run on a ma-DMP that fails validation
- **THEN** nothing is created and the validation errors are reported

### Requirement: Dataset creation from its template
Each dataset SHALL be created by rendering its declared template at its pinned version with its declared parameters. The dataset SHALL record which template, version and parameters produced it.

#### Scenario: Template rendering
- **WHEN** a dataset declares a template, a pinned version and parameters
- **THEN** the created dataset contains the rendered template content and a record of the template location, version and parameters

#### Scenario: Unreachable template
- **WHEN** a dataset's template cannot be fetched at the pinned version
- **THEN** bootstrap fails for that dataset, names it and the template, and leaves no partially created dataset behind

### Requirement: Execution environments registered as containers
The containers a template declares SHALL be registered in the created dataset as DataLad containers, each pinned to an exact image version and tracked as a subdataset or annexed file, so that computations can be run with `datalad containers-run` without further setup.

#### Scenario: Container available after bootstrap
- **WHEN** a template declares one container
- **THEN** listing the containers of the created dataset shows that container at the pinned version

### Requirement: Source datasets installed as subdatasets
For each `IsDerivedFrom` link, the source dataset SHALL be registered as a subdataset of the derived dataset under `sourcedata/`, at a path named after the source dataset.

#### Scenario: Derivative with two sources
- **WHEN** a dataset declares two source datasets
- **THEN** the created dataset has two subdatasets under `sourcedata/`, one per source

#### Scenario: Root dataset
- **WHEN** a dataset declares no source dataset
- **THEN** the created dataset has no subdataset under `sourcedata/` that refers to a dataset of the plan

### Requirement: Creation in provenance order
Datasets SHALL be created in an order in which every source dataset exists before any dataset derived from it.

#### Scenario: Chain of three
- **WHEN** the plan declares raw, standardized derived from raw, and analysis derived from standardized
- **THEN** raw is created first, standardized second and analysis third

### Requirement: Study superdataset
Bootstrap SHALL create a study superdataset that tracks the ma-DMP file under version control and registers every dataset of the plan as a subdataset in a user-oriented layout defined by a study template. The study superdataset's arrangement SHALL be independent of the provenance links between datasets.

#### Scenario: Whole project from one clone
- **WHEN** a user clones the study superdataset and installs its subdatasets
- **THEN** every dataset of the plan is present at the path the study layout assigns to it, and the ma-DMP file is present

### Requirement: Datasets created on the platform
Bootstrap SHALL create each dataset and the study superdataset as a repository on the configured DevOps platform, with the subdataset references between them pointing at those repositories. A local-only mode SHALL create the same structure without any platform.

#### Scenario: Platform bootstrap
- **WHEN** bootstrap is run with a platform configured
- **THEN** each dataset is reachable as a repository on the platform and cloning the study superdataset from the platform resolves every subdataset

#### Scenario: Local-only bootstrap
- **WHEN** bootstrap is run in local-only mode
- **THEN** the same datasets and links are created on the local filesystem and no platform request is made

### Requirement: Idempotent reconcile
Running bootstrap again on an unchanged ma-DMP SHALL make no change. A dry-run mode SHALL report the changes a run would make without making them.

#### Scenario: Second run
- **WHEN** bootstrap is run twice on the same ma-DMP
- **THEN** the second run reports no change and creates no commit

#### Scenario: Dry run
- **WHEN** bootstrap is run in dry-run mode on a ma-DMP with one dataset not yet created
- **THEN** the planned creation of that dataset is reported and nothing is created

### Requirement: Additive evolution
When a revised ma-DMP adds datasets or distributions, bootstrap SHALL create the new datasets, link them to their sources, register them in the study superdataset and configure the new distributions, without altering existing datasets' content.

#### Scenario: New derivative added
- **WHEN** a dataset derived from an existing dataset is added to the ma-DMP and bootstrap is run
- **THEN** only the new dataset is created and registered, and existing datasets gain no commit other than platform configuration for triggering the new one

#### Scenario: New distribution added
- **WHEN** a distribution is added to an existing dataset and bootstrap is run
- **THEN** the dataset is configured to fulfil that distribution at its stage and its data content is unchanged

### Requirement: Non-additive edits are reported and not applied
When a revised ma-DMP changes the template, template version, parameters or sources of an existing dataset, or removes a dataset, bootstrap SHALL NOT modify or delete the existing dataset. It SHALL report the difference and exit with a non-zero status.

#### Scenario: Changed sources
- **WHEN** an existing dataset's `IsDerivedFrom` links differ from the subdatasets it was created with
- **THEN** bootstrap reports the difference for that dataset and leaves it untouched

#### Scenario: Removed dataset
- **WHEN** a dataset that exists in the project is no longer in the ma-DMP
- **THEN** bootstrap reports it as unplanned and deletes nothing
