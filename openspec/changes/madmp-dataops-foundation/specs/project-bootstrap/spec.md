## Purpose

Turns a profile-conformant ma-DMP into a working project: one DataLad dataset per planned dataset, linked by provenance, with execution environments registered, gathered under a study superdataset, and kept in step with later additive edits of the ma-DMP.

## ADDED Requirements

### Requirement: Bootstrap from a ma-DMP
The tool SHALL provide an `init` command, referred to in this specification as bootstrap, that creates, from a valid ma-DMP, one DataLad dataset for each dataset in the plan. Bootstrap SHALL refuse to run on a ma-DMP that fails profile validation.

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

### Requirement: License and entry point carried by each dataset
Each created dataset SHALL contain its license, as declared in the ma-DMP, in a machine-readable form with its identifier, and a human-readable entry point stating what the dataset is, what it is derived from, and how to obtain its content and re-execute its results.

#### Scenario: License travels with the dataset
- **WHEN** a dataset is cloned without the study superdataset or the ma-DMP
- **THEN** its license identifier and its entry-point documentation are present in the clone

### Requirement: Execution environments registered as containers
The containers a template declares SHALL be registered in the created dataset as DataLad containers, each pinned to an exact image version and tracked as a subdataset or annexed file, so that computations can be run with `datalad containers-run` without further setup.

#### Scenario: Container available after bootstrap
- **WHEN** a template declares one container
- **THEN** listing the containers of the created dataset shows that container at the pinned version

### Requirement: Source datasets installed as subdatasets
For each `IsDerivedFrom` link, the source dataset SHALL be registered as a subdataset of the derived dataset under `sourcedata/`, at a path named after the source dataset. For an instrument source dataset, each instance SHALL be registered at `sourcedata/<stream type>/<site identifier>_<instrument identifier>`, where the stream type is the source dataset's name and only the last level is a subdataset.

#### Scenario: Derivative with two sources
- **WHEN** a dataset declares two source datasets
- **THEN** the created dataset has two subdatasets under `sourcedata/`, one per source

#### Scenario: Instrument source dataset
- **WHEN** a dataset is derived from the instrument source dataset `dicoms` with instances `a_PrismaFit16001` and `b_Skyra45012`
- **THEN** the created dataset has the subdatasets `sourcedata/dicoms/a_PrismaFit16001` and `sourcedata/dicoms/b_Skyra45012`, and `sourcedata/dicoms` itself is a plain directory

#### Scenario: Root dataset
- **WHEN** a dataset declares no source dataset
- **THEN** the created dataset has no subdataset under `sourcedata/` that refers to a dataset of the plan

#### Scenario: Resource source
- **WHEN** a dataset declares a resource-only source
- **THEN** that source is also registered under `sourcedata/` at a pinned revision

### Requirement: Bootstrap for a site
Bootstrap SHALL run on behalf of one site, using that site's configuration from the study superdataset to resolve site-dependent hosts. It SHALL create the instances of instrument source datasets for the instruments of that site, and SHALL register the instances of every site's instruments as sources of the datasets derived from them, by reference for those of other sites.

#### Scenario: Site's own instrument
- **WHEN** bootstrap runs for site `a` on a plan where `dicoms` declares instrument `PrismaFit16001` at site `a`
- **THEN** the instance `a_PrismaFit16001` exists with site `a`'s storage remotes and is registered under `sourcedata/dicoms/` of the datasets derived from `dicoms`

#### Scenario: Another site's instrument
- **WHEN** bootstrap runs for site `a` on a plan where `dicoms` also declares instrument `Skyra45012` at site `b`
- **THEN** site `a` creates no repository or storage for `b_Skyra45012` and derived datasets reference it under `sourcedata/dicoms/`

#### Scenario: Unmapped host
- **WHEN** the site configuration does not map a site-dependent host used by the plan
- **THEN** bootstrap fails before creating anything and names the host

### Requirement: Storage remotes for the early stages
Bootstrap SHALL create and configure, in each dataset, the storage remotes for its distributions bound to `collection`, `review` and `accepted`, and SHALL set on each remote the content rules derived from the distribution's filters. Bootstrap SHALL NOT create remotes or external repositories for distributions bound to `release` or `archival`.

#### Scenario: Working storage ready
- **WHEN** a dataset has a `review` distribution excluding sensitive files and a `release` distribution
- **THEN** after bootstrap the dataset has a remote for the `review` distribution whose content rule excludes sensitive files, and no remote for the `release` distribution

#### Scenario: Sensitive-only storage
- **WHEN** a dataset has a distribution whose filter includes only sensitive files
- **THEN** the remote created for it accepts only files marked sensitive

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

### Requirement: ma-DMP changes are reviewed and validated
The study superdataset SHALL accept changes to the ma-DMP only through pull requests, on which profile validation runs automatically. A pull request whose ma-DMP fails validation SHALL NOT be mergeable.

#### Scenario: Invalid edit proposed
- **WHEN** a pull request changes the ma-DMP so that it fails profile validation
- **THEN** the pull request shows the violations and cannot be merged

#### Scenario: Valid addition
- **WHEN** a pull request adding a derived dataset to the ma-DMP passes validation and is merged
- **THEN** the next bootstrap run creates that dataset

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
When a revised ma-DMP adds datasets, distributions or instruments, bootstrap SHALL create the new datasets and instrument instances, link them to their sources, register them in the study superdataset and configure the new distributions, without altering existing datasets' content. Registering a new instrument instance under `sourcedata/` of an existing derived dataset SHALL be proposed by pull request on that dataset and counts as an additive change.

#### Scenario: New derivative added
- **WHEN** a dataset derived from an existing dataset is added to the ma-DMP and bootstrap is run
- **THEN** only the new dataset is created and registered, and existing datasets gain no commit other than platform configuration for triggering the new one

#### Scenario: New instrument added
- **WHEN** an instrument is added to an existing instrument source dataset in the ma-DMP and bootstrap is run
- **THEN** the new instance is created, and each dataset derived from that source dataset has a pull request registering it under `sourcedata/`

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
