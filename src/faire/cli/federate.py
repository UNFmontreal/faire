import typer

app = typer.Typer()

@app.command()
def push():
    print("push")


@app.command()
def pull():
    print("pull")
