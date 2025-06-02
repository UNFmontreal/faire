import typer
app = typer.Typer()

@app.command()
def config():
    print("config")


@app.command()
def trigger():
    print("trigger")
