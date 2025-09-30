import typer

app = typer.Typer()

@app.command()
def sync(
    push_annex: bool=True
):
    """
    sync data to a federated instance
    """
    # push/pull git from federated
    # push wanted new local annexed data to federated remote
    pass

@app.command()
def install():
    """
    Fork a whole study on the local instance.
    """
    # for a newly created (forked) super-dataset, locally fork of all datasets
    pass
