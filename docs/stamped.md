# STAMPED conformance of the example project

Checklist: stamped-checklist 0.4.0 (https://checklist.stamped-principles.org, items in
https://github.com/stamped-principles/stamped-checklist-schema). The checklist has no answer
options beyond yes/no with a reason; answers below are for a study bootstrapped from
`examples/madmp/single_site.json` with this repository's reference templates. "Yes (checked)" is
asserted by `tests/test_docs.py`; the others are judged from the design (`design.md` D26) and
are not machine-checked.

| Item | Level | Answer | Reason |
|---|---|---|---|
| must/001 one common root | MUST | Yes (checked) | study superdataset holds every dataset as a subdataset |
| must/002 referenced datasets reachable | MUST | Yes (checked) | sources are `sourcedata/` subdatasets, containers a pinned collection subdataset |
| must/003 external software bundled | MUST | Yes | container collections are subdatasets at a pinned revision |
| must/004 VCS for text and config | MUST | Yes | git/DataLad |
| must/005 large binaries tool | MUST | Yes | git-annex; identifiable files are routed to the annex |
| must/006 environment recorded | MUST | Yes | `containers-run` records, `faire-container` trailer |
| must/007 README with usage | MUST | Yes (checked) | README rendered in each dataset and the study |
| must/008 starting point | MUST | Yes | `faire run --all` and the rule file |
| must/009 relative paths | MUST | Yes | rules use dataset-relative patterns |
| must/010 dependencies in spec | MUST | Yes | container image pinned per dataset |
| must/011 host assumptions documented | MUST | Partial | site configuration documents storage and runners; OS assumptions of a template are the template author's |
| must/012 system requirements | MUST | Partial | tool requirements are in `pyproject.toml` and the guide; domain templates must list theirs |
| must/013 specs in version control | MUST | Yes | frozen container entry in `.datalad/config`, collection revision, copier answers |
| must/014 update process | MUST | Partial | new pipeline versions are new datasets (D3); no automated reminder |
| must/015 exact replication specs | MUST | Yes | image path and collection revision are pinned |
| must/016 specs shared | MUST | Yes | collections are shared datasets; archived with the study |
| must/017 how to obtain specs | MUST | Yes | `docs/guide.md` |
| must/018 license next to content | MUST | Yes (checked) | `LICENSE` with SPDX identifier in each dataset |
| should/001 one VCS | SHOULD | Yes | |
| should/002 workflow tested regularly | SHOULD | Partial | the tool's CI tests it; a study's CI must schedule `faire test` |
| should/003 modules separated | SHOULD | Yes | raw, standardized and derived datasets, containers |
| should/004 fresh environment test | SHOULD | Yes | `faire run` works in a throwaway clone on a runner |
| should/005 disposable environment | SHOULD | Yes | one job per task |
| should/006 specs regularly tested | SHOULD | No | not scheduled by the tool |
| should/007 environment artifacts archived | SHOULD | Partial | collections are archived by their owners, not copied at release (D26) |
| should/008 tracked update process | SHOULD | Partial | as must/014 |
| should/009 restricted data in own modules | SHOULD | Partial | source data is per instrument; sensitive files in a standardized dataset are separated by filters, not by module (M.4) |
| should/010 actions recorded | SHOULD | Yes | `datalad run` records |
| should/011 module license identifiable | SHOULD | Yes (checked) | per-dataset license |
| should/012 license combination checked | SHOULD | Partial | reported at release for human review, not enforced |
| should/013 licenses look-up | SHOULD | Yes | SPDX identifier and URL |
| may/001 external components as submodules | MAY | Yes | |
| may/002 modular structure documented | MAY | Yes | ma-DMP provenance graph, guide |
| may/003 independent module boundaries | MAY | Yes | per-dataset release pins |
| may/004 composition mechanism | MAY | Yes | git submodules |
| may/005 navigation tooling | MAY | Partial | `faire stage`, `faire plan`; no browser |

Outcome: 26 Yes, 9 Partial, 1 No. No MUST is answered No; three MUSTs (must/011, 012, 014) are
Partial because they depend on what a domain template or a study adds. The one No (should/006)
is outside the tool's scope. The checklist was read on 2026-11-18; its item texts were
paraphrased from a summary, so the wording above is not verbatim.
