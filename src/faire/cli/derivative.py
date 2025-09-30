import typer
app = typer.Typer()

@app.command()
def config():
    """
    configure derivative pipeline
    """
    pass

@app.command()
def trigger():
    """
    trigger downstream derivatives pipelines
    """
    # this should look at the `.derivatives`
    # some pipelines needs to be triggered in merge request that add data (eg. QC jobs)
    # other needs to be trigger post-merge to dev|pilot branch

    # trigger is done through API calls or downstream pipeline(gitlab)
    # passing infos about triggering parent repo (url, commit, PR to report to) and target branch (dev|pilot)
    pass
