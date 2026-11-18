# Example ma-DMPs

- `single_site.json`: one site, four datasets (an instrument stream, a resource, a standardized
  and an analysis dataset), release and archival distributions.
- `federated.json`: two sites and a hub; site `a` coordinates.

Both validate with `faire validate`. Their dataset templates point at `gh:example/...`; the
quick-start in `docs/guide.md` builds a runnable copy that points at the templates of this
repository (`examples/gitlab-demo/build.py`). The reference templates are `templates/dataset`
(derived dataset), `templates/source` (instrument stream) and `templates/study` (study
superdataset).
