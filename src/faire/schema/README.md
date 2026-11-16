# Vendored RDA DMP Common Standard

Files copied unchanged from
`RDA-DMP-Common/RDA-DMP-Common-Standard`, `examples/JSON/` (master, fetched 2026-11-16):

- `maDMP-schema-1.3.json`: JSON Schema (draft 2020-12), the base standard v1.3
- `ex9-dmp-long.json`, `ex7-dataset-many.json`: official examples, used as base-conformance fixtures

## Findings from the schema (task 2.1)

- `dataset.related_identifier` exists: array of `RelatedIdentifier`, required `identifier`, `type`,
  `relation_type`. `relation_type` is a free string (DataCite values suggested), so `IsDerivedFrom` is valid.
- `dataset.technical_resource` exists: array of `TechnicalResource`, required `name`; optional
  `description`, `technical_resource_id` (`identifier`, `type`).
- **No `additionalProperties` keyword appears anywhere in the schema.** Additional properties are
  therefore allowed on `dmp`, `dataset`, `distribution`, `host` and `technical_resource`, which is
  what the `faire` extension relies on.
- `host.certified_with` is an enum: din31644, dini-zertifikat, dsa, iso16363, iso16919, trac, wds,
  coretrustseal.
- Required fields: dmp (`contact`, `created`, `dataset`, `dmp_id`, `ethical_issues_exist`,
  `language`, `modified`, `title`), dataset (`dataset_id`, `personal_data`, `sensitive_data`,
  `title`), distribution (`data_access`, `title`), host (`title`).
- **Licenses live on the distribution**, not on the dataset: `distribution.license[]` with required
  `license_ref` (a URL) and `start_date`. `dataset.rights` is free text for other rights. The profile
  requirement "license on every dataset" has to be expressed accordingly (see the profile schema).

## Profile schema (`faire-profile-1.json`, task 2.2)

Validated independently of the base schema; examples must pass both. Shape of the `faire` property:

| Entity | Fields |
|---|---|
| `dmp.faire` | `sample_entities` (required), `hub.host` (a `host_id` identifier), `coordinator` (site id) |
| `dataset.faire` | `template{repository, version, parameters}`, `sources{<id>:{role}}`, `releases[]` |
| `technical_resource[].faire` | `instrument_id`, `site` |
| `distribution.faire` | `stage`, `two_way`, `filter` (one git-annex preferred-content expression, e.g. `not metadata=distribution-restrictions=sensitive and exclude=*/pilot/*`) |
| `host.faire` | `site_dependent`, `long_term`, `method`, `parameters`, `secrets{parameter: secret name}` |

Licenses stay where the base standard puts them, on `distribution.license[]`. The rules that every dataset has a licensed distribution and that `release` and `archival` distributions are licensed are checked in code.
Cross-document rules (uniqueness, graph, hub/coordinator, secrets) are checked in code (task 2.4).
