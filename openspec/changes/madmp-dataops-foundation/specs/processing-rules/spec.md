## Purpose

Defines how a dataset's computation for one sample is described and executed: the ma-DMP says what is derived from what, the dataset template says how, and a single run command performs it identically in CI or by hand, with provenance recorded.

## ADDED Requirements

### Requirement: Processing rule carried by the dataset
Each derived dataset SHALL contain a processing rule, provided by its template, that declares the registered container to use, the command to execute, the input patterns it reads from each source, the inputs it requires, and the output patterns it produces. Pipeline logic SHALL NOT be defined in platform-specific pipeline definitions, which SHALL only invoke the run command.

#### Scenario: Rule present after bootstrap
- **WHEN** a derived dataset is created from its template
- **THEN** the dataset contains a processing rule naming a container registered in that dataset

#### Scenario: Rule naming an unknown container
- **WHEN** a processing rule names a container that is not registered in the dataset
- **THEN** the run command fails before executing anything and names the container

### Requirement: Samples identified by entities
A sample SHALL be identified by values for the entity names declared in the ma-DMP. Input and output patterns of a processing rule SHALL be resolved by substituting the sample's entity values.

#### Scenario: Pattern resolution
- **WHEN** a rule declares an input pattern using the entities `subject` and `session` and is run for the sample `subject=01, session=003`
- **THEN** only files matching the pattern with those values are treated as inputs

#### Scenario: Missing entity
- **WHEN** the run command is given a sample that lacks a value for an entity the rule's patterns use
- **THEN** it fails and names the missing entity

### Requirement: Run command for one sample
The tool SHALL provide a command that runs a dataset's processing rule for one sample. It SHALL work on the sample's feature branch, update the `sourcedata/` references to the triggering revisions, retrieve only the inputs the rule declares, execute the command through `datalad containers-run`, save the declared outputs, push the results, and open or update the sample's pull request.

#### Scenario: Successful run
- **WHEN** the run command is invoked for sample `S` in a derived dataset whose required inputs exist
- **THEN** the dataset has a pull request for `S` whose branch contains the outputs and a run record naming the container, command, inputs and outputs

#### Scenario: Only declared inputs retrieved
- **WHEN** a source dataset holds content for many samples and the rule is run for sample `S`
- **THEN** only content matching the rule's resolved input patterns and the declared resources is retrieved

### Requirement: Same behaviour in and out of CI
The run command SHALL produce the same dataset changes whether invoked by a CI job or by a person in a clone, given the same sample, source revisions and credentials. Opening the pull request SHALL be skippable for local use.

#### Scenario: Local run
- **WHEN** a maintainer runs the command locally for sample `S` without pull request creation
- **THEN** the local sample branch contains the same outputs and run record a CI job would have produced, and no pull request is opened

### Requirement: Triggering sources and resource sources
A change to a triggering source SHALL start the run for the affected sample. A resource source SHALL be available to the computation at its pinned revision, and a change to it SHALL NOT start any run.

#### Scenario: Resource updated
- **WHEN** a resource source of a dataset receives a new commit
- **THEN** no run starts in that dataset

#### Scenario: Resource used
- **WHEN** a rule declares inputs from a resource source and is run for a sample
- **THEN** those inputs are retrieved from the resource at the revision the dataset pins

### Requirement: Silent skip when required inputs are absent
When, for the given sample, no file matches an input the rule marks as required, the run command SHALL make no branch, no commit and no pull request, SHALL exit successfully, and SHALL state the unmet requirement in its job output only. Datasets further downstream SHALL consequently not be triggered for that sample.

#### Scenario: Sample without the required data
- **WHEN** the run command is invoked for a sample that has no file matching a required input
- **THEN** the dataset is unchanged, no pull request exists for that sample, and the command exits with status zero

### Requirement: Storage access for inputs and results
The run command SHALL obtain the credentials for the storage holding inputs and receiving results from the secrets named by the ma-DMP and the site configuration. A missing secret SHALL fail the run with a message naming the secret. Secret values SHALL NOT appear in output or in the dataset.

#### Scenario: Missing storage secret
- **WHEN** the secret for the storage holding a required input is not available to the job
- **THEN** the run fails before execution, names the secret, and prints no secret value

### Requirement: Results pushed to the dataset's working storage
After a successful execution, the outputs' content SHALL be transferred to the storage of the dataset's distributions bound to the `review` stage, and the branch pushed to the dataset repository, before the pull request is opened or updated.

#### Scenario: Reviewer can fetch results
- **WHEN** a pull request has been opened by the run command
- **THEN** a fresh clone of that branch can retrieve every output file from the dataset's working storage

### Requirement: Execution at the sample's site of origin
A run for a sample SHALL execute on runners belonging to the site where the sample originated. A site MAY use runners located elsewhere, provided they are orchestrated by that site and can reach its storage.

#### Scenario: Two sites
- **WHEN** a sample originating at site A is accepted in a source dataset
- **THEN** the downstream run for that sample executes on a runner of site A and not on a runner of site B

### Requirement: Ephemeral workspace
The run command SHALL be able to execute in a fresh, temporary clone and SHALL leave every result needed afterwards in the dataset repository and its storage, so that the workspace can be discarded.

#### Scenario: Workspace discarded
- **WHEN** the workspace of a completed run is deleted
- **THEN** the pull request, its outputs and its run record remain retrievable

### Requirement: Re-running a sample
Running the rule again for a sample that already has results in the dataset SHALL replace that sample's previous outputs in a new pull request and SHALL NOT alter other samples' outputs.

#### Scenario: Rerun after correction
- **WHEN** the run command is invoked for a sample whose results are already on `dev`
- **THEN** a new pull request replaces that sample's outputs and leaves all other files unchanged
