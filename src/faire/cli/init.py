import typer
import pathlib
from typing import Optional
import datalad.api as dlad
from ..git_hosts import DEFAULT_GITHOST

app = typer.Typer()

@app.command()
def init(
    path:pathlib.Path,
    storage:bool = True,
    template_url:str = None,
    extra_storages:Optional[str] = None,  #eg. for sensitive data
    procedures: Optional[list[str]] = None,
):
    """
    initializes a dataset
    """
    # optionally use a template from a git-url (eg. bids, bids-derivatives)
    if template_url:
        dlad.install(source=template_url, dest='.')
    # create datalad
    ds = dlad.create(".", force=True)
    ds.run_procedure("cfg_nidataops")

    # create repo on githost
    if DEFAULT_GITHOST:
        DEFAULT_GITHOST.create_repo(path)
        # add remote
        ds.siblings("add", 'origin', DEFAULT_GITHOST)

    # setup storage

    # install sourcedata datasets
    
    # run setup:
    # - setup default container
