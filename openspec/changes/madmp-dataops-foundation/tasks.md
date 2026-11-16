## 1. Project setup

- [ ] 1.1 Create the Python package skeleton (pyproject, source package, test directory, command-line entry point) and verify the command prints its help and an empty test run passes
- [ ] 1.2 Add dependencies (DataLad, datalad-container, copier, a JSON Schema validator, a GitLab API client) and verify a clean environment installs and imports them
- [ ] 1.3 Add CI for the tool itself (lint and tests) and verify it passes on the skeleton
- [ ] 1.4 Fill `openspec/config.yaml` context with the stack and conventions chosen here and verify `openspec validate` still passes

## 2. ma-DMP profile

- [ ] 2.1 Vendor the RDA DMP Common Standard v1.3 JSON schema and confirm from it that `dataset.related_identifier` exists and that additional properties are allowed on dataset, distribution and host; record the findings in the schema directory's README
- [ ] 2.2 Write the profile JSON schema for the extension property (template declaration, distribution stage, filters, host transfer parameters, release records) and verify a hand-written example validates against both the base and the profile schema
- [ ] 2.3 Implement loading a ma-DMP into a typed model and verify round-tripping the example file leaves it unchanged
- [ ] 2.4 Implement the non-schema checks (unique identifiers, pinned template, resolvable `IsDerivedFrom`, acyclic graph, parsable filters, no inline secrets) and verify one failing fixture per check
- [ ] 2.5 Implement the `validate` command reporting all violations with document locations and exit status, and verify against the valid fixture and a fixture with three violations
- [ ] 2.6 Add a test that stripping the extension property from the example leaves a valid base-standard document

## 3. Reference templates

- [ ] 3.1 Create a minimal reference dataset template (copier) with one registered container, a trivial pipeline run through `datalad containers-run`, and one check, and verify rendering it yields a dataset where `datalad containers-list` shows the container
- [ ] 3.2 Create a reference study template defining the study superdataset layout and the ma-DMP location, and verify rendering it yields a valid DataLad dataset
- [ ] 3.3 Add the pipeline definitions to the dataset template (pull request checks, inline processing, sample pipeline, downstream trigger, distribution job) and verify they pass the platform's pipeline linter

## 4. Local bootstrap and reconcile

- [ ] 4.1 Implement computing the creation plan from a ma-DMP in provenance order and verify the order on a three-dataset chain fixture
- [ ] 4.2 Implement dataset creation from its template with the recorded ma-DMP entry, and verify the record matches the fixture and a template fetch failure leaves no partial dataset
- [ ] 4.3 Implement installing source datasets under `sourcedata/` and verify one- and two-source fixtures and a root dataset
- [ ] 4.4 Implement study superdataset creation with the ma-DMP tracked and all datasets registered, and verify a fresh clone installs every dataset
- [ ] 4.5 Implement idempotence and dry-run, and verify a second run makes no commit and dry-run changes nothing
- [ ] 4.6 Implement additive reconcile (new dataset, new distribution) and verify existing datasets' content is untouched
- [ ] 4.7 Implement detection and reporting of non-additive differences and unplanned datasets with a non-zero exit, and verify with changed-sources and removed-dataset fixtures

## 5. Platform orchestration

- [ ] 5.1 Define the platform interface and an in-memory fake, and verify the fake passes a shared conformance test suite
- [ ] 5.2 Implement the GitLab backend (grouping, repositories, branch protection, tag protection, CI variables, pull requests, cross-repository pipeline trigger) and verify the conformance suite against a test GitLab instance
- [ ] 5.3 Connect bootstrap to the platform (repositories created, subdataset URLs pointing at them, variables for downstream datasets and secret names) and verify cloning the study superdataset from the platform resolves all subdatasets
- [ ] 5.4 Implement the missing-secrets report and the capability check before changes, and verify each with the fake
- [ ] 5.5 Configure the automation identity for pipeline commits and verify authorship on a pipeline-made commit

## 6. Dataset lifecycle

- [ ] 6.1 Implement the sample branch convention and pull request creation on push, and verify pushing a sample branch to a root dataset opens one identified pull request
- [ ] 6.2 Implement the downstream job (create or update the sample branch, update the `sourcedata/` pointer, run the pipeline with a run record, open or update the pull request) and verify on a two-dataset project that merging in the upstream opens a downstream pull request with the merged revision
- [ ] 6.3 Verify the cascade stops at one level until the intermediate pull request is merged, using a three-dataset chain
- [ ] 6.4 Verify a second trigger for the same sample updates the open pull request, using a two-source dataset
- [ ] 6.5 Implement retriggering on correction of an accepted sample and the manual reprocess command, and verify each opens the expected pull requests
- [ ] 6.6 Implement the stage query command and verify it across collection, review, accepted and release on a fixture project
- [ ] 6.7 Implement the study release pipeline (consistency check, merge to `main`, tag in provenance order, update of study pointers) and verify a consistent project gets the tag everywhere and an inconsistent one gets no tag and a report naming the lagging datasets
- [ ] 6.8 Verify two successive releases remain retrievable by tag

## 7. Data distribution

- [ ] 7.1 Implement configuring git-annex remotes for distributions at bootstrap from host parameters and named secrets, and verify with a local directory special remote
- [ ] 7.2 Implement translating filters to git-annex matching expressions and wanted content, and verify a file marked sensitive in annex metadata is not transferred, including after being marked later
- [ ] 7.3 Implement the `distribute` command for a dataset and stage, and verify only distributions bound to that stage are fulfilled and a fresh clone sees the remote's content
- [ ] 7.4 Implement failure handling for missing secrets (named, no values printed, other distributions still attempted) and verify with a fixture
- [ ] 7.5 Implement ma-DMP write-back (issue date, size, access location, release record) with re-validation and serialised commits, and verify the commit content and author after a release
- [ ] 7.6 Define the deposit adapter interface for hosts without git-annex support and identifier minting, with a fake adapter, and verify a release records the fake identifier exactly once across a repeated run
- [ ] 7.7 Verify an interrupted fulfilment completes on a second run transferring only missing files

## 8. Archival

- [ ] 8.1 Implement the archival command (push history and release content to archival hosts, relative subdataset URLs in the archived copy) and verify with local bare repositories as archival hosts
- [ ] 8.2 Verify that cloning the archived study superdataset with the platform unreachable installs all subdatasets and retrieves the content of every release

## 9. End-to-end and documentation

- [ ] 9.1 Add an end-to-end test on the test platform: bootstrap a three-dataset example, push one sample, merge through the chain, release, and check the ma-DMP release records
- [ ] 9.2 Write user documentation (profile reference, bootstrap, lifecycle, distribution, platform setup, required secrets) and verify every documented command runs against the example project
- [ ] 9.3 Publish the example ma-DMP and reference templates with the documentation and verify the quick-start works from a clean checkout in local-only mode
