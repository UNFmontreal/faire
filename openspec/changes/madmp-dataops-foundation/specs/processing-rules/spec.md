## Purpose

Defines how a dataset's computations and checks are described and executed: the ma-DMP says what is derived from what, the dataset template says how through a list of rules, and the tool plans which tasks are due and runs each one identically in CI or by hand, with provenance recorded.

## ADDED Requirements

### Requirement: Processing rules carried by the dataset
Each dataset SHALL contain a list of processing rules, provided by its template. Each rule SHALL declare an identifier, its trigger, the registered container to use, the command to execute, the input patterns it reads, the inputs it requires, the output patterns it produces, the files to keep as job artifacts, and the files to list in the pull request. Pipeline logic SHALL NOT be defined in platform-specific pipeline definitions, which SHALL only invoke the tool.

#### Scenario: Rules present after creation
- **WHEN** a derived dataset is created from its template
- **THEN** the dataset contains its processing rules, each naming a container registered in that dataset

#### Scenario: Rule naming an unknown container
- **WHEN** a processing rule names a container that is not registered in the dataset
- **THEN** planning fails before executing anything and names the rule and the container

### Requirement: Rule triggers
A rule SHALL be triggered either by a change in a triggering source of the dataset, or by a change, within the dataset itself, of files matching patterns the rule declares. A source-triggered rule SHALL deliver its results on the sample's feature branch through a pull request. A content-triggered rule SHALL deliver its results as a commit on the branch whose content triggered it.

#### Scenario: Source-triggered rule
- **WHEN** a triggering source gains sample `S`
- **THEN** the rule's results for `S` arrive as a pull request against the dataset's `dev`

#### Scenario: Content-triggered rule
- **WHEN** a pull request branch gains files matching the trigger patterns of a content-triggered rule
- **THEN** the rule's results are committed to that same branch and appear in the same pull request

### Requirement: Samples identified by entities
A sample SHALL be identified by values for the entity names declared in the ma-DMP. Input and output patterns of a rule SHALL be resolved by substituting the sample's entity values.

#### Scenario: Pattern resolution
- **WHEN** a rule declares an input pattern using the entities `subject` and `session` and is run for the sample `subject=01, session=003`
- **THEN** only files matching the pattern with those values are treated as inputs

#### Scenario: Missing entity
- **WHEN** a task is requested for a sample that lacks a value for an entity the rule's patterns use
- **THEN** it fails and names the missing entity

### Requirement: Planning from the dataset's state
The tool SHALL provide a command that determines, for a branch of a dataset, the tasks that are due, each task being one rule applied to one sample, and outputs them as a machine-readable list giving for each task its identifier, rule, sample, site and position in the order. A task SHALL be due when the inputs recorded by the rule's last run for that sample differ from their current state, or when the rule has never run for that sample. Planning SHALL depend only on the state of the dataset and its sources, not on which event started it, and SHALL NOT change the dataset.

#### Scenario: New sample upstream
- **WHEN** a triggering source holds a sample for which a source-triggered rule has no recorded run
- **THEN** the plan contains one task for that rule and sample

#### Scenario: Nothing to do
- **WHEN** every rule's recorded inputs match the current state
- **THEN** the plan is empty and the command exits successfully

#### Scenario: Missed event
- **WHEN** an upstream change occurred while no pipeline could start, and planning is run later
- **THEN** the plan contains the tasks that change made due

#### Scenario: Planning by hand
- **WHEN** a maintainer runs the planning command in a clone outside CI
- **THEN** the same list is produced as in a CI job for the same state

### Requirement: Explicit order of rules on a branch
Rules that deliver results on the same branch SHALL have an explicit order declared in the dataset. Their due tasks for a sample SHALL be executed consecutively in that order, each starting from the state left by the previous one. A rule that is skipped, because it is optional for that sample or its required inputs are absent, SHALL NOT prevent the rules ordered after it from running on the current state. No rule SHALL use the existence of another rule's outputs as its trigger.

#### Scenario: Two steps in sequence
- **WHEN** rules `A` then `B` are both due on a pull request branch for sample `S`
- **THEN** `A` runs and commits first, and `B` runs on the branch state that includes `A`'s commit

#### Scenario: Optional step skipped
- **WHEN** rule `A` is skipped for sample `S` and rule `B` is due
- **THEN** `B` runs on the branch state without `A`'s outputs

### Requirement: No re-triggering by own or later results
A commit made by a rule SHALL NOT make that rule, or a rule ordered before it on the same branch, due again for the same sample.

#### Scenario: Rule modifies its own inputs
- **WHEN** a content-triggered rule replaces files that match its own trigger patterns
- **THEN** planning after its commit does not contain that rule for that sample

#### Scenario: Later rule modifies earlier inputs
- **WHEN** rule `B`, ordered after `A`, changes files that `A` reads
- **THEN** planning after `B`'s commit does not contain `A` for that sample

### Requirement: Run command for one task
The tool SHALL provide a command that runs one planned task. For a source-triggered rule it SHALL work on the sample's feature branch and update the `sourcedata/` references to the triggering revisions. In all cases it SHALL retrieve only the inputs the rule declares, execute the command through `datalad containers-run`, save the declared outputs, push the results, and open or update the pull request when the rule delivers through one. The same command SHALL be able to run all due tasks of a branch consecutively in their order.

#### Scenario: Successful run
- **WHEN** a task for sample `S` is run in a derived dataset whose required inputs exist
- **THEN** the dataset has a pull request for `S` whose branch contains the outputs and a run record naming the container, command, inputs and outputs

#### Scenario: Only declared inputs retrieved
- **WHEN** a source dataset holds content for many samples and a task is run for sample `S`
- **THEN** only content matching the rule's resolved input patterns and the declared resources is retrieved

#### Scenario: All due tasks in one invocation
- **WHEN** the command is asked to run everything due on a branch with tasks `A` then `B`
- **THEN** both run in order in that single invocation and the branch ends in the same state as if each had run in its own job

### Requirement: Same behaviour in and out of CI
Running a task SHALL produce the same dataset changes whether invoked by a CI job or by a person in a clone, given the same sample, source revisions and credentials. Opening the pull request SHALL be skippable for local use.

#### Scenario: Local run
- **WHEN** a maintainer runs a task locally for sample `S` without pull request creation
- **THEN** the local branch contains the same outputs and run record a CI job would have produced, and no pull request is opened

### Requirement: Triggering sources and resource sources
A change to a triggering source SHALL make source-triggered rules due for the affected sample. A resource source SHALL be available to the computation at its pinned revision, and a change to it SHALL NOT make any task due.

#### Scenario: Resource updated
- **WHEN** a resource source of a dataset receives a new commit
- **THEN** the plan for that dataset is unchanged

#### Scenario: Resource used
- **WHEN** a rule declares inputs from a resource source and is run for a sample
- **THEN** those inputs are retrieved from the resource at the revision the dataset pins

### Requirement: Silent skip when required inputs are absent
When, for the given sample, no file matches an input the rule marks as required, the task SHALL make no branch, no commit and no pull request, SHALL exit successfully, and SHALL state the unmet requirement in its job output only. Datasets further downstream SHALL consequently not be triggered for that sample by that rule.

#### Scenario: Sample without the required data
- **WHEN** a task is run for a sample that has no file matching a required input
- **THEN** the dataset is unchanged, no pull request exists for that sample from that rule, and the command exits with status zero

### Requirement: Storage access for inputs and results
Running a task SHALL obtain the credentials for the storage holding inputs and receiving results from the secrets named by the ma-DMP and the site configuration. A missing secret SHALL fail the task with a message naming the secret. Secret values SHALL NOT appear in output or in the dataset.

#### Scenario: Missing storage secret
- **WHEN** the secret for the storage holding a required input is not available to the job
- **THEN** the task fails before execution, names the secret, and prints no secret value

### Requirement: Results pushed to the dataset's working storage
After a successful execution, the outputs' content SHALL be transferred to the storage of the dataset's distributions bound to the `review` stage, and the branch pushed to the dataset repository, before the pull request is opened or updated.

#### Scenario: Reviewer can fetch results
- **WHEN** a task has pushed its results to a pull request branch
- **THEN** a fresh clone of that branch can retrieve every output file from the dataset's working storage

### Requirement: Job artifacts declared by the rule
The files a rule declares as job artifacts SHALL be made available as artifacts of the job that ran the task, whether or not the task succeeded, in addition to anything saved in the dataset.

#### Scenario: Logs kept after failure
- **WHEN** a rule declares its log directory as job artifacts and the task fails
- **THEN** the log files are downloadable from the failed job

### Requirement: Files listed in the pull request
The files a rule declares for listing SHALL be listed in the pull request that carries the task's results, each with a link through which a reviewer can open it. The listing SHALL be updated when the task runs again.

#### Scenario: Quality report
- **WHEN** a rule declares its report file for listing and the task completes for sample `S`
- **THEN** the pull request for `S` shows a link to that report

### Requirement: Checks declared with the rules
A dataset SHALL declare its checks alongside its rules, each check being marked blocking or advisory. The tool SHALL provide a command that lists the checks applicable to a branch and runs any one of them separately, so that each can run as its own job. The outcome of each check SHALL be reported on the pull request.

#### Scenario: Checks listed
- **WHEN** the check command is asked to list checks for a pull request branch
- **THEN** it outputs each applicable check with its identifier and whether it is blocking or advisory

#### Scenario: One check alone
- **WHEN** the check command is run for a single check identifier
- **THEN** only that check runs and its exit status reflects its result

#### Scenario: Checks after processing
- **WHEN** content-triggered rules are due on a pull request branch
- **THEN** the checks are run on the state left by the last of them

### Requirement: Execution at the sample's site of origin
A task for a sample SHALL execute on runners belonging to the site where the sample originated. A site MAY use runners located elsewhere, provided they are orchestrated by that site and can reach its storage.

#### Scenario: Two sites
- **WHEN** a sample originating at site A is accepted in a source dataset
- **THEN** the downstream task for that sample executes on a runner of site A and not on a runner of site B

### Requirement: Ephemeral workspace
A task SHALL be able to execute in a fresh, temporary clone and SHALL leave every result needed afterwards in the dataset repository, its storage, the job artifacts and the pull request, so that the workspace can be discarded.

#### Scenario: Workspace discarded
- **WHEN** the workspace of a completed task is deleted
- **THEN** the pull request, its outputs and its run record remain retrievable

### Requirement: Results re-executable from their record
Any result accepted on `dev` or contained in a release SHALL be re-executable from its run record using only the dataset, the components it references at their recorded revisions, and access to the storage holding its inputs. The record SHALL identify the revision of every component involved: the sources, the container and the processing rule.

#### Scenario: Re-execution by someone with access
- **WHEN** a person with access to the inputs re-executes the run record of an accepted result in a fresh clone
- **THEN** the computation runs with the same container, command and input revisions without any step not described in the dataset

#### Scenario: Component versions recorded
- **WHEN** the history of an accepted result is inspected
- **THEN** the revision of each source, the container version and the processing rule version used are all identifiable

### Requirement: Re-running a sample
Running a source-triggered rule again for a sample that already has results in the dataset SHALL replace that sample's previous outputs in a new pull request and SHALL NOT alter other samples' outputs.

#### Scenario: Rerun after correction
- **WHEN** a task is run for a sample whose results are already on `dev`
- **THEN** a new pull request replaces that sample's outputs and leaves all other files unchanged
