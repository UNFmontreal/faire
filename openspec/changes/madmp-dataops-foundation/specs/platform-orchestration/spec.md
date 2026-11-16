## Purpose

Defines what the tool requires from, and configures on, a DevOps platform so that repositories, protections, CI settings and cross-dataset triggers follow from the ma-DMP and the same project can be hosted on different platforms.

## ADDED Requirements

### Requirement: Platform-neutral operations
All platform interactions SHALL go through a defined set of operations: create and look up a repository and its grouping, protect branches, set CI variables and secrets references, open and update pull requests, and trigger a pipeline in another repository. Support for a platform SHALL be addable without changing the behaviour specified for bootstrap, lifecycle or distribution.

#### Scenario: Reference platform
- **WHEN** the tool is configured for GitLab
- **THEN** every specified bootstrap, lifecycle and distribution behaviour is available

#### Scenario: Unsupported operation
- **WHEN** a configured platform does not support an operation a command needs
- **THEN** the command fails before making any change and names the unsupported operation

### Requirement: Repository organisation
Bootstrap SHALL place the study superdataset and all dataset repositories under one project grouping on the platform, named from the ma-DMP, so that access can be administered for the study as a whole.

#### Scenario: Study grouping
- **WHEN** a project is bootstrapped on the platform
- **THEN** all its repositories are listed under a single grouping for the study

### Requirement: Branch protection
Bootstrap SHALL configure every dataset repository so that `dev`, `pilot` and `main` accept changes only through merged pull requests or the automation identity, and so that release tags can be created only by maintainers or the automation identity.

#### Scenario: Protection applied
- **WHEN** a dataset repository has been created by bootstrap
- **THEN** its `dev` and `main` branches are protected and a direct push by a developer is refused

### Requirement: CI configuration from templates and from the ma-DMP
Pipeline definitions SHALL come from the dataset's template and live in the dataset repository. Bootstrap SHALL set on the platform the CI variables those pipelines need that derive from the ma-DMP, including the identifiers of source and downstream datasets and the names of the secrets used by distributions.

#### Scenario: Variables present
- **WHEN** a dataset with one downstream dataset and one distribution needing a secret has been bootstrapped
- **THEN** its repository's CI configuration exposes the downstream dataset's location and the name of that secret

### Requirement: Secrets provided by operators
The tool SHALL NOT create or store secret values. Bootstrap SHALL report every secret named in the ma-DMP that is not yet defined on the platform.

#### Scenario: Missing secret reported
- **WHEN** bootstrap finishes and a secret named by a distribution is not defined on the platform
- **THEN** the report lists that secret and the repositories that need it

### Requirement: Cross-dataset triggers
The platform configuration SHALL allow a merge into `dev` of a dataset to start the pipeline of each directly derived dataset with the sample identifier and the merged revision, and SHALL allow a release tag on the study superdataset to start the release in every dataset.

#### Scenario: Downstream pipeline started
- **WHEN** a sample pull request is merged in a dataset with two directly derived datasets
- **THEN** a pipeline starts in each of the two, receiving the sample identifier and the merged revision

### Requirement: Automation identity
All changes made by pipelines (pull requests, write-back commits, tags) SHALL be made under a dedicated automation identity, distinguishable from human contributors in the history.

#### Scenario: Attribution
- **WHEN** a pipeline commits processing results or a ma-DMP update
- **THEN** the commit author is the automation identity

### Requirement: Jobs run on platform runners
Lifecycle and distribution jobs SHALL run as CI jobs on runners registered with the platform. The specified behaviour SHALL NOT depend on where a runner executes, including runners that submit work to an HPC scheduler.

#### Scenario: Runner on a cluster
- **WHEN** a dataset's pipeline runs on a runner that executes jobs through an HPC scheduler
- **THEN** the resulting pull request is equivalent to one produced on any other runner
