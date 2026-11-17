## 1. Project setup

- [x] 1.1 Create the Python package skeleton (pyproject, source package, test directory, command-line entry point) and verify the command prints its help and an empty test run passes
- [x] 1.2 Add dependencies (DataLad, datalad-container, copier, a JSON Schema validator, a GitLab API client) and verify a clean environment installs and imports them
- [ ] 1.3 Add CI for the tool itself (lint and tests) and verify it passes on the skeleton
- [x] 1.4 Fill `openspec/config.yaml` context with the stack and conventions chosen here and verify `openspec validate` still passes

## 2. ma-DMP profile

- [x] 2.1 Vendor the RDA DMP Common Standard v1.3 JSON schema and confirm from it that `dataset.related_identifier` exists and that additional properties are allowed on dmp, dataset, distribution and host; record the findings in the schema directory's README
- [x] 2.2 Write the profile JSON schema for the extension (template declaration, source roles, instruments on `technical_resource` with identifier and site, sample entities, distribution stage, filters, two-way flag, site-dependent hosts, host transfer parameters, hub and coordinator, release records) and verify a hand-written single-site example and a federated example validate against both the base and the profile schema
- [x] 2.3 Implement loading a ma-DMP into a typed model and verify round-tripping both examples leaves them unchanged
- [x] 2.4 Implement the non-schema checks (instruments with identifier and site, consistent across streams and unique within one, no hub or release distribution on instrument source datasets, license with resolvable reference on at least one distribution of every dataset and on every release or archival distribution, archival distributions only to long-term hosts, unique identifiers, pinned template, resolvable `IsDerivedFrom`, acyclic graph, at least one triggering source, filters that parse as git-annex matching expressions, no inline secrets, two-way only to the hub, hub requires coordinator) and verify one failing fixture per check
- [x] 2.5 Implement the `validate` command reporting all violations with document locations and exit status, and verify against the valid fixtures and a fixture with three violations
- [x] 2.6 Add a test that stripping the extension property from the examples leaves valid base-standard documents

## 3. Sites and reference templates

- [x] 3.1 Define the site configuration format (identifier, host mapping, runner routing) and its loader, and verify an unmapped site-dependent host is reported by name
- [x] 3.2 Create a minimal reference dataset template (copier) with one registered container, a processing rule file, `.gitattributes` union-merge entries, one blocking check and one advisory protocol check, and verify rendering yields a dataset where `datalad containers-list` shows the container
- [x] 3.3 Create a reference study template defining the study superdataset layout, the ma-DMP location and the site configuration location, and verify rendering yields a valid DataLad dataset
- [x] 3.4 Add to the dataset template the single entry pipeline definition (plan, render, child pipeline) and the single-job fallback, and verify both pass the platform's pipeline linter and contain no pipeline logic

## 4. Bootstrap and reconcile (local)

- [x] 4.1 Implement computing the creation plan from a ma-DMP and a site in provenance order, including one instance per declared instrument named `<site>_<instrument>`, and verify the order, instance names and `sourcedata/<stream type>/<site>_<instrument>` paths on a fixture with one instrument feeding two streams
- [x] 4.2 Implement dataset creation from its template with the recorded ma-DMP entry and `dev`, `pilot` and `main` branches, and verify the record matches and a template fetch failure leaves no partial dataset
- [x] 4.3 Implement installing triggering and resource sources under `sourcedata/` and verify one-source, two-source, resource and root fixtures
- [x] 4.4 Implement study superdataset creation with the ma-DMP and site configuration tracked and all datasets registered, and verify a fresh clone installs every dataset
- [x] 4.5 Implement creation of storage remotes for `collection`, `review` and `accepted` distributions with wanted rules from the filters, and verify with directory special remotes that a general and a sensitive-only remote get the right rules and no `release` remote exists
- [x] 4.6 Implement idempotence and dry-run, and verify a second run makes no commit and dry-run changes nothing
- [x] 4.7 Implement additive reconcile (new dataset, new distribution) and verify existing datasets' content is untouched
- [x] 4.8 Implement detection and reporting of non-additive differences and unplanned datasets with a non-zero exit, and verify with changed-sources and removed-dataset fixtures
- [ ] 4.9 Add ma-DMP validation as a required check on study superdataset pull requests and verify an invalid edit cannot be merged
- [x] 4.10 Write the license (with SPDX identifier) and a generated entry-point README into each created dataset and verify both are present in a clone taken without the study superdataset
- [x] 4.11 Implement additive handling of a new instrument (new instance, pull request registering it in derived datasets) and verify existing instances are untouched

## 5. Platform orchestration

- [x] 5.1 Define the platform interface and an in-memory fake, and verify the fake passes a shared conformance test suite
- [x] 5.2 Implement the GitLab backend (grouping, repositories, branch and tag protection, CI variables, pull requests, cross-repository pipeline trigger) and verify the conformance suite against a test GitLab instance
- [x] 5.3 Connect `init` to the platform (repositories created, subdataset URLs pointing at them, variables for downstream datasets, site and secret names) and verify cloning the study superdataset from the platform resolves all subdatasets
- [x] 5.4 Implement the missing-secrets report and the capability check before changes, and verify each with the fake
- [x] 5.5 Configure the automation identity for pipeline commits and verify authorship on a pipeline-made commit
- [x] 5.6 Implement the GitLab renderer producing a child pipeline from a plan (one job per task and check, `needs` order, serialisation per branch, runner tags per site, declared artifacts, advisory checks allowed to fail, native downstream trigger jobs) and verify the four generated-pipeline scenarios on the test instance
- [ ] 5.7 Implement `trigger` through the platform interface and verify the portable trigger with the fake and recovery from a lost trigger by re-planning
- [ ] 5.8 Configure protection of the tool's branch name patterns at `init` so sample branches can read task secrets, and verify an arbitrary branch cannot
- [ ] 5.8a Require at least one human approval plus passing blocking checks to merge into `dev` and `main` at `init`, and verify a green unapproved pull request cannot be merged
- [ ] 5.9 Verify the single-job fallback leaves the same branch state as the generated pipeline

## 6. Processing rules

- [x] 6.1 Implement the rule file model (identifier, trigger, container, command, inputs, required inputs, outputs, order, artifacts, listed files, checks with blocking or advisory mark) and entity-based pattern resolution, and verify resolution, a missing entity and an unknown container each behave as specified
- [x] 6.2 Implement state-based `plan` for source-triggered rules from run records and verify the new-sample, nothing-to-do, missed-event and resource-update scenarios, with identical output in and out of CI
- [x] 6.3 Implement planning of content-triggered rules with explicit order and the rule that own or later results do not re-trigger, and verify the sequence, optional-step and both re-triggering scenarios
- [x] 6.4 Implement `run --task` for source-triggered rules (sample branch, source pointer update, retrieval of declared inputs only, `datalad containers-run`, save) and verify the run record and that unrelated samples' content was not retrieved
- [x] 6.5 Implement `run --task` for content-triggered rules committing to the triggering branch, and `run --all`, and verify the branch state equals that of separate jobs
- [x] 6.6 Implement the silent skip on unmet required inputs and verify the dataset is unchanged and the exit status is zero
- [x] 6.7 Implement storage credential handling from named secrets and verify a missing secret fails early, is named, and no value is printed
- [x] 6.8 Implement result push to `review` storage and the repository, then pull request creation or update with a switch to skip it, and verify a fresh clone of the branch can retrieve all outputs
- [x] 6.9 Implement collection of declared job artifacts (including after failure) and the tool-owned pull request listing of declared files, and verify logs are kept from a failed task and a report link appears and is updated on rerun
- [x] 6.10 Implement `test --list` and `test --check` and verify listing, running one check alone, and that checks run on the state left by the last content-triggered task
- [x] 6.11 Verify a local run and a CI run of the same task and source revisions produce the same tree
- [x] 6.12 Implement rerun for a sample already on `dev` and verify only that sample's outputs change
- [x] 6.13 Implement site assignment of tasks in the plan and verify on a two-site fixture that the other site's runner is not used
- [x] 6.14 Verify an accepted result can be re-executed with `datalad rerun` in a fresh clone and that the record identifies the source revisions, container version and rule version

## 7. Data indexing

- [ ] 7.1 Define the heuristic interface (optional functions for entities, pilot, keep, sensitive, placement, subdataset name, subdataset setup, with defaults) and its loader from the dataset clone, and verify a heuristic implementing only entities works and a missing entity fails by name
- [ ] 7.2 Add a reference heuristic to the reference source dataset template and verify dry-run prints its decisions and changes nothing
- [ ] 7.3 Implement `index` for direct storage (fresh clone, placement, save, sensitive and pilot marks, commit record with entities and heuristic revision) and verify the commit record and that a pilot sample lands on `pilot`
- [ ] 7.4 Implement per-sample subdataset creation (platform repository, remotes with the parent's wanted rules, setup callback run once before data with its own commit, parent's file handling by default, registration in the parent) reusing the bootstrap remote setup, and verify the four callback scenarios with the fake platform
- [ ] 7.5 Implement archived storage of files through git-annex archive special remotes, configured by the setup callback, and verify a single file can still be obtained by path from a fresh clone
- [ ] 7.6 Implement the push order (content, subdataset, parent) with failure handling and verify no history is pushed when storage is unavailable
- [ ] 7.7 Verify repeatability: the same directory indexed twice makes no commit, and an interrupted run completes without duplication
- [ ] 7.8 Implement credential handling from the environment for off-platform use and verify a missing platform credential fails before any change
- [ ] 7.9 Wire the indexing push to the downstream trigger with the sample entities and verify a derived dataset opens a pull request for the indexed sample
- [ ] 7.10 Implement routing by instrument identifier and per-sample recording of the software version, and verify the two-instruments, software-update and other-site scenarios
- [ ] 7.11 Implement handling of undeclared instruments (instance creation, warning, pull request on derived datasets, no downstream trigger until merged, triggering of waiting samples and ma-DMP pull request on merge) and verify the three specified scenarios with the fake platform

## 8. Dataset lifecycle

- [ ] 8.1 Implement the sample branch convention and pull request creation on push for manual contributions, and verify the pull request identifies the sample and that a derived dataset's pull request targets `pilot` for a pilot sample
- [ ] 8.2 Wire merge events to downstream `run` for triggering sources only, and verify on a three-dataset chain that the cascade advances one level per merge and a resource change triggers nothing
- [ ] 8.3 Verify a second trigger for the same sample updates the open pull request, using a two-source dataset
- [ ] 8.4 Verify the advisory protocol check warns without blocking, and that merging a deviating sample produces no downstream pull request and no failure
- [ ] 8.5 Verify pilot samples cascade to downstream `pilot` branches and that committed protocol expectations are used on the next production pull request
- [ ] 8.6 Implement retriggering on correction of an accepted sample and the manual reprocess command, and verify each opens the expected pull requests
- [ ] 8.7 Implement the stage query command and verify it across collection, review, accepted and release
- [ ] 8.8 Implement the study release pipeline (consistency check, merge to `main`, tag in provenance order, update of study pointers) and verify a consistent project is tagged everywhere without pilot samples, and an inconsistent one gets no tag and a report naming the lagging datasets
- [ ] 8.9 Verify two successive releases remain retrievable by tag
- [ ] 8.10 Implement sensitive marking of originals replaced by inline processing and pilot marking of pilot content, and verify originals stay retrievable from the site's sensitive storage and neither originals nor pilot content reach any non-site remote
- [ ] 8.11 Implement the release check on referenced components (in release, declared restricted, or external and answering at the pinned revision) and the release report, and verify the external-container, unretrievable-component and restricted-source scenarios
- [ ] 8.12 Add the license listing to the release report and verify differing licenses are shown without blocking

## 9. Data distribution

- [ ] 9.1 Implement the `sync` command for a dataset and stage, covering one-way distributions with filter enforcement and delegating two-way distributions to the hub exchange, with an option to name distributions, and verify only that stage's distributions are fulfilled, a sensitive file is never transferred, and a fresh clone sees the remote's content
- [ ] 9.2 Implement first-use creation of `release` and `archival` remotes with wanted rules and verify creation on the first release and reuse on the second
- [ ] 9.3 Implement failure handling for missing secrets (named, no values printed, other distributions still attempted) and verify with a fixture
- [ ] 9.4 Implement the release completeness check from git-annex location tracking and verify no identifier is obtained while a selected file is missing from the release remote
- [ ] 9.5 Define the deposit adapter interface for hosts without git-annex support and for identifier minting, with a fake adapter, and verify a release records the fake identifier exactly once across a repeated run
- [ ] 9.6 Implement ma-DMP write-back (issue date, size, access location, release record) with re-validation and serialised commits, and verify the commit content and author after a release
- [ ] 9.7 Verify an interrupted fulfilment completes on a second run transferring only missing files

## 10. Federation

- [ ] 10.1 Implement joining a study from the hub (install, create local repositories, create instances for the site's own instruments, create site remotes) and verify a second site gets the first site's accepted history and no access to its source content
- [ ] 10.2 Implement `sync` for `dev`, `main` and `pilot` in provenance order with the hub as a sibling, and verify two sites converge through a bare-repository hub and an unchanged state makes no commit
- [ ] 10.3 Implement conflict resolution (union merges from the template, ancestry-based source pointer resolution, abort and report otherwise) and verify the three specified conflict scenarios
- [ ] 10.4 Verify received samples land on `dev` without a pull request and start no run at the receiving site
- [ ] 10.5 Implement content transfer to hub storage when present and verify, with a git-only hub, that another site sees the holding site in the location record and no transfer is attempted
- [ ] 10.6 Implement the coordinator-only release start with the all-sites-synchronised check, and verify a release is refused naming the lagging site
- [ ] 10.7 Implement per-site delivery of released files on tag arrival and the coordinator's completion step, and verify identifiers are obtained only after both sites delivered and that only the coordinator commits to the ma-DMP
- [ ] 10.8 Verify the hub-orchestrated deployment on the fake platform: one platform, two sites' runners, each sample processed at its site
- [ ] 10.9 Verify other sites see the location and revision of a site's source dataset under `sourcedata/` and cannot retrieve its content, and that a ma-DMP revision merged on the hub reaches a site by sync
- [ ] 10.10 Implement federated archival by reusing the release flow and verify the archive completes only after both sites delivered

## 11. Archival

- [ ] 11.1 Implement the archival command (push history and release content to archival hosts, relative subdataset URLs in the archived copy) and verify with local bare repositories as archival hosts
- [ ] 11.2 Verify that cloning the archived study superdataset with the platform unreachable installs all subdatasets and retrieves the content of every release

## 12. End-to-end and documentation

- [ ] 12.1 Add a single-site end-to-end test on the test platform: bootstrap a three-dataset example, push one pilot and one production sample, merge through the chain, release, and check the ma-DMP release records
- [ ] 12.2 Add a two-site end-to-end test with a hub: each site accepts one sample, both synchronise, the coordinator releases, and the release completes with files from both sites
- [ ] 12.3 Write user documentation (profile reference, site configuration, bootstrap, processing rules, lifecycle and pilot stream, distribution, federation, platform setup, required secrets) and verify every documented command runs against the example project
- [ ] 12.5 Run the STAMPED checklist against the example project and record the outcome next to the conformance table in the documentation
- [ ] 12.4 Publish the example ma-DMPs and reference templates with the documentation and verify the quick-start works from a clean checkout in local-only mode
