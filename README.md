# FAIRe

"Juste FAIRe le!" © 

Building on [FAIR principles](https://www.gofair.foundation/fair-principles) of research data management:
- F for findable: datasets metadata and structure are exposed, searchable, lightly duplicated for resilience.
- A for accessible: data can be fetched 
- I for interoperable: use file-based standards (eg. BIDS), use git to manage data for interoperability.
- R for reproducible: everything is run on containers that are part of the data, the call of the containers is logged in commit through datalad-run
- E for executable: FAIR principles don't have to be only words on paper, they can be living in a machine-actionable schema, and tools to operate on that schema.

It also builds on:
- the legacy of [BIDSFlux](https://bids-flux-docs.readthedocs.io/en/latest/) a domain specific proof-of-concept
- newer [STAMPED principles](https://stamped-principles.org/)
- [RDA DMP standard](https://rda-dmp-common.github.io/RDA-DMP-Common-Standard/) for the schema of machine-actionable data management plans, that we extend for real data actionability.

See `openspec/changes/madmp-dataops-foundation/` for the specification.

Mais qu'est ce que ça peut faire?
Ça peut tout faire! 
C'est la [barre de faire](docs/assets/barre_de_faire.png) tout!
