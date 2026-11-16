## 1. Project setup

- [ ] 1.1 Create the Python package skeleton (pyproject, source package, test directory, command-line entry point) and verify the command prints its help and an empty test run passes
- [ ] 1.2 Add dependencies (DataLad, datalad-container, copier, a JSON Schema validator, a GitLab API client) and verify a clean environment installs and imports them
- [ ] 1.3 Add CI for the tool itself (lint and tests) and verify it passes on the skeleton
- [ ] 1.4 Fill `openspec/config.yaml` context with the stack and conventions chosen here and verify `openspec validate` still passes

## 2. ma-DMP profile

- [ ] 2.1 Vendor the RDA DMP Common Standard v1.3 JSON schema and confirm from it that `dataset.related_identifier` exists and that additional properties are allowed on dmp, dataset, distribution and host; record the findings in the schema directory's README
- [ ] 2.2 Write the profile JSON schema for the extension (template declaration, source roles, site-scoped flag, sample entities, distribution stage, filters, two-way flag, site-dependent hosts, host transfer parameters, hub and coordinator, release records) and verify a hand-written single-site example and a federated example validate against both the base and the profile schema
- [ ] 2.3 Implement loading a ma-DMP into a typed model and verify round-tripping both examples leaves them unchanged
- [ ] 2.4 Implement the non-schema checks (archival distributions only to long-term hosts, unique identifiers, pinned template, resolvable `IsDerivedFrom`, acyclic graph, at least one triggering source, parsable filters, no inline secrets, site-scoped datasets without hub or release distributions, two-way only to the hub, hub requires coordinator) and verify one failing fixture per check
- [ ] 2.5 Implement the `validate` command reporting all violations with document locations and exit status, and verify against the valid fixtures and a fixture with three violations
- [ ] 2.6 Add a test that stripping the extension property from the examples leaves valid base-standard documents

## 3. Sites and reference templates

- [ ] 3.1 Define the site configuration format (identifier, host mapping, runner routing) and its loader, and verify an unmapped site-dependent host is reported by name
- [ ] 3.2 Create a minimal reference dataset template (copier) with one registered container, a processing rule file, `.gitattributes` union-merge entries, one blocking check and one advisory protocol check, and verify rendering yields a dataset where `datalad containers-list` shows the container
- [ ] 3.3 Create a reference study template defining the study superdataset layout, the ma-DMP location and the site configuration location, and verify rendering yields a valid DataLad dataset
- [ ] 3.4 Add thin pipeline definitions to the dataset template that only call the tool (checks, `run`, downstream trigger, `distribute`, `sync`) and verify they pass the platform's pipeline linter and contain no pipeline logic

## 4. Bootstrap and reconcile (local)

- [ ] 4.1 Implement computing the creation plan from a ma-DMP and a site in provenance order, including per-site instances of site-scoped datasets, and verify the order and instance names on a fixture
- [ ] 4.2 Implement dataset creation from its template with the recorded ma-DMP entry and `dev`, `pilot` and `main` branches, and verify the record matches and a template fetch failure leaves no partial dataset
- [ ] 4.3 Implement installing triggering and resource sources under `sourcedata/` and verify one-source, two-source, resource and root fixtures
- [ ] 4.4 Implement study superdataset creation with the ma-DMP and site configuration tracked and all datasets registered, and verify a fresh clone installs every dataset
- [ ] 4.5 Implement creation of storage remotes for `collection`, `review` and `accepted` distributions with wanted rules from the filters, and verify with directory special remotes that a general and a sensitive-only remote get the right rules and no `release` remote exists
- [ ] 4.6 Implement idempotence and dry-run, and verify a second run makes no commit and dry-run changes nothing
- [ ] 4.7 Implement additive reconcile (new dataset, new distribution) and verify existing datasets' content is untouched
- [ ] 4.8 Implement detection and reporting of non-additive differences and unplanned datasets with a non-zero exit, and verify with changed-sources and removed-dataset fixtures
- [ ] 4.9 Add ma-DMP validation as a required check on study superdataset pull requests and verify an invalid edit cannot be merged

## 5. Platform orchestration

- [ ] 5.1 Define the platform interface and an in-memory fake, and verify the fake passes a shared conformance test suite
- [ ] 5.2 Implement the GitLab backend (grouping, repositories, branch and tag protection, CI variables, pull requests, cross-repository pipeline trigger) and verify the conformance suite against a test GitLab instance
- [ ] 5.3 Connect bootstrap to the platform (repositories created, subdataset URLs pointing at them, variables for downstream datasets, site and secret names) and verify cloning the study superdataset from the platform resolves all subdatasets
- [ ] 5.4 Implement the missing-secrets report and the capability check before changes, and verify each with the fake
- [ ] 5.5 Configure the automation identity for pipeline commits and verify authorship on a pipeline-made commit

## 6. Processing rules

- [ ] 6.1 Implement the rule file model and entity-based pattern resolution, and verify resolution, a missing entity and an unknown container each behave as specified
- [ ] 6.2 Implement `run --sample` (sample branch, source pointer update, retrieval of declared inputs only, `datalad containers-run`, save) and verify the run record and that unrelated samples' content was not retrieved
- [ ] 6.3 Implement the silent skip on unmet required inputs and verify the dataset is unchanged and the exit status is zero
- [ ] 6.4 Implement storage credential handling from named secrets and verify a missing secret fails early, is named, and no value is printed
- [ ] 6.5 Implement result push to `review` storage and the repository, then pull request creation or update with a switch to skip it, and verify a fresh clone of the branch can retrieve all outputs
- [ ] 6.6 Verify a local run and a CI run of the same sample and source revisions produce the same tree
- [ ] 6.7 Implement rerun for a sample already on `dev` and verify only that sample's outputs change
- [ ] 6.8 Implement job routing to the sample's site of origin and verify on a two-site fixture that the other site's runner is not used

## 7. Dataset lifecycle

- [ ] 7.1 Implement the sample branch convention, the pilot mark and pull request creation on push, and verify a production sample targets `dev` and a pilot sample targets `pilot`
- [ ] 7.2 Wire merge events to downstream `run` for triggering sources only, and verify on a three-dataset chain that the cascade advances one level per merge and a resource change triggers nothing
- [ ] 7.3 Verify a second trigger for the same sample updates the open pull request, using a two-source dataset
- [ ] 7.4 Verify the advisory protocol check warns without blocking, and that merging a deviating sample produces no downstream pull request and no failure
- [ ] 7.5 Verify pilot samples cascade to downstream `pilot` branches and that committed protocol expectations are used on the next production pull request
- [ ] 7.6 Implement retriggering on correction of an accepted sample and the manual reprocess command, and verify each opens the expected pull requests
- [ ] 7.7 Implement the stage query command and verify it across collection, review, accepted and release
- [ ] 7.8 Implement the study release pipeline (consistency check, merge to `main`, tag in provenance order, update of study pointers) and verify a consistent project is tagged everywhere without pilot samples, and an inconsistent one gets no tag and a report naming the lagging datasets
- [ ] 7.9 Verify two successive releases remain retrievable by tag
- [ ] 7.10 Implement sensitive marking of originals replaced by inline processing and pilot marking of pilot content, and verify originals stay retrievable from the site's sensitive storage and neither originals nor pilot content reach any non-site remote

## 8. Data distribution

- [ ] 8.1 Implement the `distribute` command for a dataset and stage with filter enforcement, and verify only that stage's distributions are fulfilled, a sensitive file is never transferred, and a fresh clone sees the remote's content
- [ ] 8.2 Implement first-use creation of `release` and `archival` remotes with wanted rules and verify creation on the first release and reuse on the second
- [ ] 8.3 Implement failure handling for missing secrets (named, no values printed, other distributions still attempted) and verify with a fixture
- [ ] 8.4 Implement the release completeness check from git-annex location tracking and verify no identifier is obtained while a selected file is missing from the release remote
- [ ] 8.5 Define the deposit adapter interface for hosts without git-annex support and for identifier minting, with a fake adapter, and verify a release records the fake identifier exactly once across a repeated run
- [ ] 8.6 Implement ma-DMP write-back (issue date, size, access location, release record) with re-validation and serialised commits, and verify the commit content and author after a release
- [ ] 8.7 Verify an interrupted fulfilment completes on a second run transferring only missing files

## 9. Federation

- [ ] 9.1 Implement joining a study from the hub (install, create local repositories, instantiate site-scoped datasets, create site remotes) and verify a second site gets the first site's accepted history and no access to its source content
- [ ] 9.2 Implement `sync` for `dev`, `main` and `pilot` in provenance order with the hub as a sibling, and verify two sites converge through a bare-repository hub and an unchanged state makes no commit
- [ ] 9.3 Implement conflict resolution (union merges from the template, ancestry-based source pointer resolution, abort and report otherwise) and verify the three specified conflict scenarios
- [ ] 9.4 Verify received samples land on `dev` without a pull request and start no run at the receiving site
- [ ] 9.5 Implement content transfer to hub storage when present and verify, with a git-only hub, that another site sees the holding site in the location record and no transfer is attempted
- [ ] 9.6 Implement the coordinator-only release start with the all-sites-synchronised check, and verify a release is refused naming the lagging site
- [ ] 9.7 Implement per-site delivery of released files on tag arrival and the coordinator's completion step, and verify identifiers are obtained only after both sites delivered and that only the coordinator commits to the ma-DMP
- [ ] 9.8 Verify the hub-orchestrated deployment on the fake platform: one platform, two sites' runners, each sample processed at its site
- [ ] 9.9 Verify other sites see the location and revision of a site's source dataset under `sourcedata/` and cannot retrieve its content, and that a ma-DMP revision merged on the hub reaches a site by sync
- [ ] 9.10 Implement federated archival by reusing the release flow and verify the archive completes only after both sites delivered

## 10. Archival

- [ ] 10.1 Implement the archival command (push history and release content to archival hosts, relative subdataset URLs in the archived copy) and verify with local bare repositories as archival hosts
- [ ] 10.2 Verify that cloning the archived study superdataset with the platform unreachable installs all subdatasets and retrieves the content of every release

## 11. End-to-end and documentation

- [ ] 11.1 Add a single-site end-to-end test on the test platform: bootstrap a three-dataset example, push one pilot and one production sample, merge through the chain, release, and check the ma-DMP release records
- [ ] 11.2 Add a two-site end-to-end test with a hub: each site accepts one sample, both synchronise, the coordinator releases, and the release completes with files from both sites
- [ ] 11.3 Write user documentation (profile reference, site configuration, bootstrap, processing rules, lifecycle and pilot stream, distribution, federation, platform setup, required secrets) and verify every documented command runs against the example project
- [ ] 11.4 Publish the example ma-DMPs and reference templates with the documentation and verify the quick-start works from a clean checkout in local-only mode
