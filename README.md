# faire:
## "juste faire le": a Yoda-talad helper for FAIR pipeline on CI-CD.

faire aims to be a light wrapper around datalad to orchestrate FAIR data pipelines running on CI/CD, following Yoda provenance tracking principles.


Each datalad dataset has:

- a `sourcedata` folder with submodule(s) in there
- containers submodule(s) with the necessary process to generate the dataset.
- configurations:
  - containers configs (extending `.datalad/config`) with:
		- a mapping from each sourcedata submodule to a container
		- inputs/outputs data
	- downstream datasets to be triggered when new data is created in the dataset

Samples in the datasets need to follow a BIDS-like naming for the subject and session (`sub-xxx/ses-yyy`).
