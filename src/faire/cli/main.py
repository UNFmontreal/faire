import typer

from . import derivative, federate, run, init

app = typer.Typer()

app.add_typer(derivative.app, name="derivatives")
app.add_typer(federate.app, name="federate")
app.add_typer(init.app)
app.add_typer(run.app)

if __name__ == "__main__":
    app()
