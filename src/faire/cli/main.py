import typer
import pathlib
import datalad
import datalad.api as dlad
from . import derivative, federate, run, init
from ..git_hosts import get_githost

app = typer.Typer()

app.add_typer(derivative.app, name="derivatives")
app.add_typer(federate.app, name="federate")
app.add_typer(init.app)
app.add_typer(run.app)


@app.command()
def auto(
    path:pathlib.Path
):
    pass

ds = dlad.Dataset(".")

@app.callback()
def main(verbose: bool = False):
    """
    Faire: juste faire le
    """
    pass

if __name__ == "__main__":
    with datalad.log.no_progress():
        app()
