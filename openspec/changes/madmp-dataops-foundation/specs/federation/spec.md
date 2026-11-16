## Purpose

Lets several sites contribute to one study under a single ma-DMP: each site keeps its source and sensitive data local and processes its own samples, while non-sensitive standardized and derived data are synchronised through a hub and released together.

## ADDED Requirements

### Requirement: Federation is optional
A study SHALL be operable by a single site with no hub. All federation behaviour SHALL apply only when the ma-DMP declares a hub.

#### Scenario: Single-site study
- **WHEN** the ma-DMP declares no hub
- **THEN** bootstrap, processing, release and archival work without any synchronisation step

### Requirement: Hub-and-spoke topology
Sites SHALL exchange dataset history and content only through the hub. The tool SHALL NOT synchronise one site directly with another.

#### Scenario: Two sites and a hub
- **WHEN** site A and site B both participate in a study
- **THEN** changes accepted at site A reach site B only after site A has synchronised with the hub and site B has synchronised with the hub

### Requirement: Sites
A site SHALL be defined by a site identifier, its runners, its storage and its secrets. Two deployments SHALL be supported with the same behaviour: each site running its own DevOps platform and synchronising with the hub, and the hub's platform orchestrating all pipelines with each site providing only runners and storage.

#### Scenario: Hub-orchestrated study
- **WHEN** all repositories live on the hub's platform and sites provide runners
- **THEN** each sample is still processed on its site of origin's runners using that site's storage, and no repository synchronisation between platforms is needed

### Requirement: Site configuration
Each site's non-secret configuration SHALL be version-controlled in the study superdataset and readable by all sites. It SHALL give the site identifier, the mapping from host names used in the ma-DMP to that site's storage, and how jobs are routed to that site's runners. Secrets SHALL be held by each site's platform and never stored in the configuration.

#### Scenario: Adding a site
- **WHEN** a site configuration is added to the study superdataset and the ma-DMP declares that site's instruments
- **THEN** the site can be bootstrapped

#### Scenario: Host not mapped
- **WHEN** the ma-DMP names a site-dependent host that the site's configuration does not map
- **THEN** bootstrap for that site fails and names the host

### Requirement: Joining a study from the hub
A site SHALL be able to join an existing study by installing the study superdataset from the hub. Joining SHALL create the site's local repositories for the federated datasets, the instances of instrument source datasets for the site's own instruments, and the site's storage remotes.

#### Scenario: Second site joins
- **WHEN** site B joins a study already populated by site A
- **THEN** site B has the federated datasets with site A's accepted history, an empty instance for each of its own declared instruments, and no access to the content of site A's instances

### Requirement: What is federated
A dataset SHALL be federated only if it has a two-way distribution to the hub. Instrument source datasets SHALL NOT be federated. Files excluded by the hub distribution's filters, including files marked sensitive, SHALL never be transferred to the hub or to another site.

#### Scenario: Source data stays local
- **WHEN** a site synchronises with the hub
- **THEN** no content of its instrument source datasets is transferred

#### Scenario: Sensitive file in a federated dataset
- **WHEN** a federated dataset contains a file marked sensitive
- **THEN** other sites receive the file's entry in the history and cannot retrieve its content

### Requirement: References to other sites' source datasets
Every site SHALL know, for each instrument source dataset instance of another site, its repository location and the revision referenced by derived datasets, without being able to retrieve its content. When the hub orchestrates the study, the repositories of instrument source datasets MAY be visible to all sites on the hub, their content remaining on the owning site's storage.

#### Scenario: Reference without access
- **WHEN** site B inspects a federated dataset derived from site A's source data
- **THEN** site B sees the location and revision of site A's source dataset under `sourcedata/` and cannot retrieve any of its content

### Requirement: Hub-orchestrated deployment footprint
When the hub orchestrates the study, a site SHALL need to deploy only its ingestion services and its runners, both with access to the site's storage.

#### Scenario: Minimal site
- **WHEN** a site joins a hub-orchestrated study with runners and an ingestion service that can reach its storage
- **THEN** its samples are ingested, processed and delivered without any site-hosted DevOps platform

### Requirement: Synchronisation with the hub
The `sync` command SHALL synchronise a site with the hub through the datasets' two-way distributions: for each federated dataset, in provenance order with sources first, it merges the hub's `dev`, `main` and `pilot` branches into the site's, then pushes the result to the hub. It SHALL be runnable on a schedule and after each merge.

#### Scenario: Both sides changed
- **WHEN** site A accepted sample `S1` and the hub already holds sample `S2` from site B
- **THEN** after site A synchronises, both site A's `dev` and the hub's `dev` contain `S1` and `S2`

#### Scenario: Nothing to do
- **WHEN** a site and the hub are identical
- **THEN** synchronisation makes no commit and no push

### Requirement: Conflict resolution
Files for which the dataset template declares a union merge SHALL be merged by union. A conflict on a `sourcedata/` subdataset reference SHALL be resolved by taking the commit that descends from the other; because sources are synchronised first, when neither reference descends from the other the source dataset's synchronised head, which descends from both, SHALL be used. Any other conflict SHALL stop the synchronisation of that dataset, leave the hub and the site's protected branches unchanged, and be reported.

#### Scenario: Tabular file edited at both sites
- **WHEN** both sites appended different rows to a file the template declares as union-merged
- **THEN** the merged file contains the rows of both and synchronisation continues

#### Scenario: Diverged source reference
- **WHEN** site A's and the hub's versions of a derived dataset reference different, diverged commits of the same source
- **THEN** the merged dataset references the source's synchronised head

#### Scenario: Unresolvable conflict
- **WHEN** both sides changed the same lines of a file with no declared merge rule
- **THEN** that dataset is not pushed, the conflict is reported with the file path, and other datasets are still synchronised

### Requirement: No second review and no reprocessing of received samples
Samples received from the hub SHALL land on the site's `dev` directly, without a pull request. Receiving another site's sample SHALL NOT start any processing at the receiving site.

#### Scenario: Sample from another site
- **WHEN** site B receives sample `S1`, originated and accepted at site A
- **THEN** `S1` is on site B's `dev`, no pull request was opened for it, and no run started at site B

### Requirement: Content availability across sites
Each site SHALL transfer the non-sensitive content it produced to the hub's storage when the hub has storage. The hub MAY hold version history only. In both cases the record of where each file is held SHALL be shared through the hub so every site knows which site or storage holds a file.

#### Scenario: Hub without storage
- **WHEN** the hub holds history only and site B looks up a file produced at site A
- **THEN** site B sees that the file is held by site A's storage, and no transfer to the hub was attempted

### Requirement: Coordinated federated release
A federated study SHALL declare one coordinator. Only the coordinator SHALL start a release, and only when every site's accepted work is on the hub. The release tag SHALL propagate through the hub; each site SHALL then transfer the released files it holds to the release hosts. The release SHALL NOT depend on the hub holding content.

#### Scenario: Site not yet synchronised
- **WHEN** the coordinator starts a release while a site has accepted work not yet on the hub
- **THEN** the release is refused and the site is named

#### Scenario: Each site delivers its own files
- **WHEN** release `R` has propagated to sites A and B
- **THEN** each site transfers to the release host the files of `R` that it holds and that the distribution's filters allow

### Requirement: Release completion by the coordinator
The coordinator alone SHALL create the external repositories for a release, obtain persistent identifiers and write release records to the ma-DMP, and SHALL do so only once every file selected for the release is recorded as present on the release host. Until then the release SHALL be reported as incomplete with the sites still owing files.

#### Scenario: One site still transferring
- **WHEN** site A has delivered its files for release `R` and site B has not
- **THEN** no identifier is obtained, and the release status names site B

#### Scenario: All files delivered
- **WHEN** every selected file of release `R` is present on the release host
- **THEN** the coordinator obtains the identifier and the ma-DMP gains one release record per dataset

### Requirement: Federated archival
Archival of a federated study SHALL follow the same process as a federated release: started by the coordinator, delivered by each site for the files it holds, and completed by the coordinator once every selected file is present on the archival host.

#### Scenario: Archival across sites
- **WHEN** the coordinator starts archival and both sites have delivered their files to the archival host
- **THEN** the archive is reported complete and holds the content of every release from both sites

### Requirement: Single writer for the ma-DMP
In a federated study, the authoritative ma-DMP SHALL be the one in the study superdataset on the hub, where it is revised collaboratively through reviewed pull requests. Changes to the ma-DMP made by tooling SHALL be made by the coordinator only. All changes SHALL reach the sites through synchronisation of the study superdataset.

#### Scenario: Plan revised on the hub
- **WHEN** a pull request adding a dataset to the ma-DMP is merged on the hub
- **THEN** each site receives the revised ma-DMP at its next synchronisation and its next bootstrap run creates the dataset locally

#### Scenario: Site-side fulfilment
- **WHEN** a site fulfils a distribution
- **THEN** the site makes no commit to the ma-DMP, and the corresponding facts are written by the coordinator
