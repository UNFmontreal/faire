# Diagrams: ma-DMP, faire and the DevOps/CI engine

Illustrative companion to `design.md`. Not an OpenSpec artifact; the specs remain normative.

## 1. Components: ma-DMP, `faire`, platform, storage

```mermaid
flowchart LR
  subgraph STUDY["Study superdataset (hub, authoritative)"]
    DMP["ma-DMP<br/>RDA v1.3 + faire extension"]
    SITES["site configs<br/>(non-secret)"]
  end

  subgraph FAIRE["faire (Python tool)"]
    VAL["validate"]
    INIT["init"]
    IDX["index"]
    PLAN["plan"]
    RUN["run / test"]
    TRIG["trigger"]
    SYNC["sync"]
  end

  subgraph PLAT["DevOps platform + CI engine"]
    REPOS["repositories, groups,<br/>branch protection, CI variables"]
    CI["pipelines and runners"]
    PR["pull requests"]
  end

  subgraph STORE["Storage"]
    WORK["site working storage<br/>(git-annex remotes)"]
    EXT["release / archival hosts"]
    HUB["hub (git, maybe storage)"]
  end

  TPL["dataset templates<br/>rules, checks, heuristics"]

  DMP --> VAL
  DMP --> INIT
  TPL --> INIT
  SITES --> INIT
  INIT -->|creates| REPOS
  INIT -->|creates early-stage remotes| WORK
  IDX -->|content| WORK
  IDX -->|history| REPOS
  CI -->|calls| PLAN
  CI -->|calls| RUN
  CI -->|calls| TRIG
  RUN --> PR
  RUN -->|results| WORK
  SYNC --> WORK
  SYNC --> HUB
  SYNC -->|release, archival| EXT
  SYNC -->|write-back by coordinator| DMP
```

## 2. How the ma-DMP becomes repositories

```mermaid
flowchart TB
  DMP["ma-DMP"]
  DMP --> D1["dataset dicoms<br/>technical_resource: instruments"]
  DMP --> D2["dataset bids<br/>IsDerivedFrom dicoms"]
  DMP --> D3["dataset fmriprep<br/>IsDerivedFrom bids"]
  DMP --> D4["dataset atlas<br/>(resource source)"]

  D1 --> R1a["a_PrismaFit16001"]
  D1 --> R1b["b_Skyra45012"]

  subgraph BIDS["repository: bids"]
    S1["sourcedata/dicoms/a_PrismaFit16001"]
    S2["sourcedata/dicoms/b_Skyra45012"]
  end
  R1a -. submodule .-> S1
  R1b -. submodule .-> S2

  subgraph FP["repository: fmriprep"]
    S3["sourcedata/bids (triggering)"]
    S4["sourcedata/atlas (resource)"]
    C["containers/ (registered)"]
  end
  D2 --> BIDS
  D3 --> FP

  STUDYSD["study superdataset<br/>registers all datasets<br/>in a user-oriented layout"]
  BIDS -.-> STUDYSD
  FP -.-> STUDYSD
```

## 3. One sample, from instrument to derivative

```mermaid
sequenceDiagram
  participant Inst as Instrument / ingestion
  participant Idx as faire index (at site)
  participant SrcRepo as dicoms instance repo
  participant CI as CI engine
  participant Faire as faire plan / run
  participant BIDS as bids repo + PR
  participant Stor as site storage

  Inst->>Idx: directory of received files
  Idx->>Idx: heuristic: instrument, entities, pilot
  Idx->>Stor: annexed content
  Idx->>SrcRepo: push history to dev (or pilot)
  SrcRepo->>CI: update on branch
  CI->>Faire: plan (state-based)
  Faire-->>CI: tasks due, with order and site
  CI->>Faire: one job per task: run --task
  Faire->>Stor: get declared inputs only
  Faire->>BIDS: containers-run, push feature branch, open PR
  Faire->>Stor: push results (review stage)
  BIDS->>CI: PR pipeline
  CI->>Faire: plan: content-triggered tasks (e.g. defacing), in order
  CI->>Faire: test: blocking and advisory checks
  Note over BIDS: curator reviews, merges to dev
  BIDS->>CI: merge to dev
  CI->>Faire: native trigger to derived datasets
  Note over Faire: next level plans and opens its own PR
```

## 4. Plan, render, run inside the CI engine

```mermaid
flowchart TB
  EV["push to a branch<br/>or trigger from upstream"] --> P1["planning job:<br/>faire plan"]
  P1 --> LIST[["neutral task list<br/>id, rule, sample, site, order, artifacts"]]
  LIST --> REND["faire ci render"]
  REND --> GL["GitLab child pipeline<br/>needs, resource_group, runner tags,<br/>artifacts, allow_failure"]
  REND -.later.-> ACT["Actions-style matrix<br/>GitHub, Forgejo, Gitea"]
  LIST -.fallback.-> ONE["single job:<br/>faire run --all then faire test"]
  GL --> J1["job: run --task A"]
  J1 --> J2["job: run --task B"]
  J2 --> CH["jobs: test --check X"]
  CH --> DS["trigger jobs:<br/>derived datasets"]
```

## 5. Lifecycle stages, release and federation

Stages: `collection`, `review`, `accepted`, `release`, `archival`.

```mermaid
flowchart LR
  subgraph SITEA["Site A"]
    A1["index, run, PRs"]
    A2["dev"]
  end
  subgraph SITEB["Site B"]
    B1["index, run, PRs"]
    B2["dev"]
  end
  HUB["Hub<br/>history, optional storage"]

  A2 <-->|sync| HUB
  B2 <-->|sync| HUB

  COORD["Coordinator:<br/>tag on study superdataset"]
  HUB --> COORD
  COORD -->|"consistency check,<br/>dev to main, tag"| HUB
  HUB -->|tag propagates| A2
  HUB -->|tag propagates| B2
  A2 -->|files it holds| REL["release host"]
  B2 -->|files it holds| REL
  REL -->|"all files present?"| COORD
  COORD -->|"DOI, release records<br/>into ma-DMP"| HUB
```
