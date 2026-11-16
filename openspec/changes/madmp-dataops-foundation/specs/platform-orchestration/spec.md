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

### Requirement: Human approval to merge
Bootstrap SHALL configure every dataset repository so that a pull request into `dev` or `main` can be merged only after at least one human approval and passing blocking checks. Automatic merging SHALL NOT be enabled by the tool.

#### Scenario: Green pull request without approval
- **WHEN** all blocking checks of a pull request pass and nobody has approved it
- **THEN** the pull request cannot be merged

### Requirement: CI configuration from templates and from the ma-DMP
The entry pipeline definition SHALL come from the dataset's template and live in the dataset repository. Bootstrap SHALL set on the platform the CI variables those pipelines need that derive from the ma-DMP, including the identifiers of source and downstream datasets and the names of the secrets used by distributions.

#### Scenario: Variables present
- **WHEN** a dataset with one downstream dataset and one distribution needing a secret has been bootstrapped
- **THEN** its repository's CI configuration exposes the downstream dataset's location and the name of that secret

### Requirement: Pipeline generated from the plan
Each dataset repository SHALL have a single entry pipeline definition, provided by its template, that runs on updates to its branches, obtains the plan of due tasks and applicable checks from the tool, and starts one job per task and per check. Each generated job SHALL only invoke the tool with the task or check identifier. The generated pipeline SHALL preserve the declared order of tasks on a branch, run checks after them, route each job to the runners of the task's site, attach the artifacts the rule declares, and let advisory checks fail without failing the pipeline. On the reference platform the generated jobs SHALL be visible as part of the pipeline of the branch or pull request that started them.

#### Scenario: Two samples due
- **WHEN** the plan for a branch contains tasks for two samples of the same site
- **THEN** the pipeline has two jobs, each invoking the tool with one task identifier, on that site's runners

#### Scenario: Ordered tasks then checks
- **WHEN** the plan contains content-triggered tasks `A` then `B` for a pull request branch, and two checks
- **THEN** the job for `B` starts only after the job for `A` succeeded, and the check jobs start after `B`

#### Scenario: Empty plan
- **WHEN** nothing is due on the updated branch and no check applies
- **THEN** no task job is started and the pipeline succeeds

#### Scenario: Advisory check fails
- **WHEN** an advisory check job fails and all blocking check jobs succeed
- **THEN** the pipeline is reported as passed with a warning and the pull request can be merged

### Requirement: Single-job fallback
On a platform for which no pipeline generation is available, the entry pipeline definition SHALL be able to run all due tasks and applicable checks consecutively in one job, with the same resulting dataset state as the generated pipeline.

#### Scenario: Platform without generation
- **WHEN** the plan contains tasks `A` then `B` and the platform has no pipeline generation
- **THEN** one job runs `A`, `B` and the checks in order, and the branch ends in the same state as with separate jobs

### Requirement: Trigger command
The tool SHALL provide a command that starts the planning pipeline of the datasets directly derived from the current one, passing the revision that changed. On the reference platform, the generated pipeline SHALL instead use the platform's native cross-repository trigger so that upstream and downstream pipelines are shown as linked. Because planning works from state, a trigger that is lost SHALL be recoverable by starting the downstream planning pipeline again by any means.

#### Scenario: Native trigger on the reference platform
- **WHEN** a sample is accepted on `dev` of a dataset on the reference platform
- **THEN** the downstream datasets' pipelines are started and appear linked to the upstream pipeline

#### Scenario: Portable trigger
- **WHEN** the trigger command is run on a platform without a native cross-repository trigger
- **THEN** the downstream datasets' pipelines are started through the platform's programming interface

#### Scenario: Lost trigger
- **WHEN** a downstream trigger failed and the downstream planning pipeline is later started manually
- **THEN** the tasks made due by the upstream change are planned

### Requirement: Secrets available to sample branches
Initialisation SHALL configure each dataset repository so that jobs running on sample feature branches and pull requests can obtain the secrets their tasks need, while those secrets remain unavailable to branches outside the patterns the tool uses.

#### Scenario: Task on a feature branch
- **WHEN** a task runs on a sample feature branch and needs a storage secret
- **THEN** the secret is available to the job

#### Scenario: Arbitrary branch
- **WHEN** a contributor pushes a branch that does not follow the tool's branch naming
- **THEN** jobs on that branch cannot read the storage secrets

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
