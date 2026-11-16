## Purpose

Provides a generic indexer that brings newly received instrument data into a site's source dataset under version control, guided by a study-provided heuristic, so that ingestion tools share one implementation of dataset, storage and hosting interactions.

## ADDED Requirements

### Requirement: Index command
The tool SHALL provide a command that, given a directory of received files and the stream they belong to, that is, an instrument source dataset of the study, works in a fresh clone of the instance for the instrument that produced the files, records the files as a new sample, transfers their content to the instance's `collection`-stage storage, and pushes the resulting history to the instance's repository.

#### Scenario: New sample indexed
- **WHEN** the command is run on a directory holding one new sample
- **THEN** the repository of the producing instrument's instance has a new commit recording the sample's files, and their content is retrievable from that instance's `collection` storage by a fresh clone

#### Scenario: Not an instrument source dataset
- **WHEN** the command is pointed at a dataset that declares no instrument
- **THEN** it fails before changing anything

### Requirement: Routing by instrument
The heuristic SHALL determine, from the incoming files, the identifier of the instrument that produced them. The indexer SHALL record the sample in the instance named `<site identifier>_<instrument identifier>` of the given stream for the current site. The instrument's software version, when the heuristic reports it, SHALL be recorded with the sample and SHALL NOT affect which instance is used.

#### Scenario: Two instruments at a site
- **WHEN** site `a` has instances for `PrismaFit16001` and `PrismaFit16002` and the incoming files come from `PrismaFit16002`
- **THEN** the sample is recorded in `a_PrismaFit16002` only

#### Scenario: Software update
- **WHEN** files arrive from a declared instrument whose software version differs from earlier samples
- **THEN** the sample is recorded in the same instance and its record carries the new software version

#### Scenario: Instrument of another site
- **WHEN** the incoming files come from an instrument the ma-DMP declares at a different site
- **THEN** nothing is recorded and the command fails naming the instrument and its declared site

### Requirement: Instruments not yet declared
When the incoming files come from an instrument the ma-DMP does not declare for the stream, the indexer SHALL create a new instance for it at the current site, with the same template and storage remotes as the other instances of that stream, and SHALL index pilot and production samples into it. Pushing the new instance SHALL open, on each dataset derived from that stream, a pull request registering the instance under `sourcedata/`. Samples indexed into the new instance SHALL NOT trigger any derived dataset until that pull request is merged; on merge, the samples indexed meanwhile SHALL be triggered. Merging SHALL also result in a pull request on the study superdataset that adds the instrument to the ma-DMP. Until the instrument is declared, the indexer SHALL warn at each run that it is undeclared.

#### Scenario: First sample from a new scanner
- **WHEN** a sample arrives at site `a` from the instrument `PrismaFit16002`, undeclared for the stream `dicoms`
- **THEN** the instance `a_PrismaFit16002` is created and holds the sample, the derived dataset has a pull request registering `sourcedata/dicoms/a_PrismaFit16002`, and the command's output warns that the instrument is not in the ma-DMP

#### Scenario: Samples wait for the registration
- **WHEN** two production samples are indexed into the new instance before its registration pull request is merged
- **THEN** the derived dataset has no pull request for either sample

#### Scenario: Registration merged
- **WHEN** the pull request registering the new instance is merged in the derived dataset
- **THEN** the derived dataset is triggered for the samples already indexed, and the study superdataset has a pull request adding the instrument, with its site, to the ma-DMP

### Requirement: Heuristic-driven behaviour
Indexing SHALL be driven by a heuristic, written in Python and provided by the source dataset's template, that receives the incoming files and decides: the instrument that produced the files, the sample's entity values, whether the sample is pilot, which files to keep, which files to mark sensitive, where each file is placed, whether the sample is stored in its own subdataset and under what name, and how a new subdataset is set up. Each decision other than the instrument and the entity values SHALL be optional for a heuristic, with a documented default.

#### Scenario: Entities from file metadata
- **WHEN** the heuristic derives `subject=01, session=003` from the incoming files' metadata
- **THEN** the sample is recorded under those entity values and at the paths the heuristic assigns

#### Scenario: Files dropped
- **WHEN** the heuristic excludes some incoming files
- **THEN** those files are not recorded and the command's output lists them as dropped

#### Scenario: Sample cannot be identified
- **WHEN** the heuristic cannot determine a value for a sample entity declared in the ma-DMP
- **THEN** nothing is recorded or pushed and the command fails naming the missing entity

### Requirement: Heuristic versioned with the dataset
The heuristic used SHALL be the one contained in the source dataset at the revision being indexed into. Each indexing commit SHALL record the heuristic's revision, the sample's entity values and whether the sample is pilot, in machine-readable form.

#### Scenario: Provenance of ingestion
- **WHEN** an indexing commit is inspected
- **THEN** the sample's entities, its pilot status and the revision of the heuristic that produced the layout are identifiable

### Requirement: Samples stored directly or in their own subdataset
When the heuristic asks for it, the sample SHALL be stored in a new subdataset of the instrument's instance, created by the indexer with the name the heuristic gives, with its own repository on the platform and its own storage remotes carrying the same rules as the parent's about which files each storage accepts. Otherwise the sample SHALL be stored directly in the instance.

#### Scenario: Sample with many files
- **WHEN** the heuristic asks for a per-sample subdataset named from the sample's entities
- **THEN** a repository with that name exists on the platform, it is registered in the source dataset at the path the heuristic assigns, and each of its storage remotes accepts and refuses the same kinds of files as the parent's corresponding remote

#### Scenario: Small sample
- **WHEN** the heuristic does not ask for a subdataset
- **THEN** the sample's files are recorded in the source dataset itself and no repository is created

### Requirement: Subdataset setup callback
The heuristic MAY provide a setup callback. When it does, the indexer SHALL call it once on each newly created subdataset, after creation and before any received file is recorded, so that it can configure the subdataset, for example which files are annexed. The changes it makes SHALL be recorded in the subdataset's history as a commit distinct from the data. The callback SHALL NOT be called again for a subdataset that already exists. Without a callback, a new subdataset SHALL take the source dataset's own file-handling configuration.

#### Scenario: Callback configures file handling
- **WHEN** the heuristic's setup callback declares that files of a given type are annexed and a per-sample subdataset is created
- **THEN** the subdataset's first commit after creation holds that configuration, and the received files of that type are recorded as annexed content

#### Scenario: No callback
- **WHEN** the heuristic has no setup callback and a per-sample subdataset is created
- **THEN** the subdataset handles files the same way as the source dataset

#### Scenario: Existing subdataset
- **WHEN** more data for a sample whose subdataset already exists is indexed
- **THEN** the setup callback is not called and the subdataset's configuration is unchanged

#### Scenario: Callback fails
- **WHEN** the setup callback raises an error
- **THEN** no data is recorded, nothing is pushed, and the command fails reporting the error

### Requirement: Archived storage of files
The indexer SHALL be able to record a sample's files packed into one or more archives on storage, through git-annex archive special remotes, when the source dataset's template so configures, while keeping the individual files' paths addressable from the dataset.

#### Scenario: Sample of thousands of small files
- **WHEN** archiving is configured and a sample of many small files is indexed
- **THEN** the storage holds archives instead of individual files, and a consumer can still obtain a single file by its path

### Requirement: Sensitive and pilot marking at indexing
Files the heuristic marks sensitive SHALL be recorded with the sensitive mark before any transfer, so that content rules apply from the first push. Content of a sample the heuristic marks pilot SHALL be recorded with the pilot mark, and the sample SHALL be recorded on the source dataset's `pilot` branch.

#### Scenario: Sensitive file
- **WHEN** the heuristic marks a file sensitive
- **THEN** its content is transferred only to storage whose rules accept sensitive files

#### Scenario: Pilot sample
- **WHEN** the heuristic marks the sample pilot
- **THEN** the sample appears on the source dataset's `pilot` branch and not on `dev`

### Requirement: Content before history
The indexer SHALL transfer content to storage before pushing history, and SHALL push a new subdataset's history before the parent's, so that no pushed revision references content or a subdataset that is not yet available.

#### Scenario: Storage unavailable
- **WHEN** the content transfer fails
- **THEN** no history is pushed and the command fails naming the storage

### Requirement: Repeatable indexing
Running the command again on data already indexed SHALL make no new commit. Running it again after an interrupted run SHALL complete the sample without duplicating it.

#### Scenario: Same data twice
- **WHEN** the command is run a second time on the same directory
- **THEN** the dataset is unchanged

#### Scenario: Resumed after failure
- **WHEN** a run that failed after transferring content is run again
- **THEN** the history is pushed and the sample appears once

### Requirement: Indexing starts the pipeline
Pushing an indexed sample to a source dataset SHALL trigger, for that sample, the datasets for which the source dataset is a triggering source, in the same way as a merged pull request.

#### Scenario: Conversion triggered
- **WHEN** a production sample has been indexed and pushed
- **THEN** the dataset derived from the source dataset opens a pull request for that sample against its `dev`

### Requirement: Runs at the site, outside the platform
The command SHALL be runnable on a machine at the site that is not a platform runner, using the site's configuration, a platform credential allowed to push to the source dataset and create repositories under it, and the site's storage credentials, all obtained from the environment. Secret values SHALL NOT be written to output or to the dataset.

#### Scenario: Missing credential
- **WHEN** the platform credential is absent from the environment
- **THEN** the command fails before changing anything and names the missing credential

### Requirement: Dry run
The command SHALL offer a mode that reports the heuristic's decisions and the changes that would be made, without recording, transferring or pushing anything.

#### Scenario: Checking a heuristic
- **WHEN** the command is run in dry-run mode on a directory of received files
- **THEN** it prints the entity values, pilot status, kept and dropped files, sensitive files and target paths, and changes nothing
