"""Reference heuristic: received files are laid out as <subject>/<session>/<file>.

`faire index` applies the functions below to a directory of received files. Only `entities` is
required; the other functions are optional and are shown here with what they do by default.
A study replaces this file with a heuristic that reads its instrument's formats.
"""

from pathlib import Path

INSTRUMENT_FILE = "instrument.txt"  # optional: first line `<instrument id> [<software version>]`
PILOT_MARKER = "PILOT"  # optional: an empty file by this name marks the sample as a pilot


def entities(files, ctx):
    """The sample's entity values; here the first two folders of the received paths."""
    first = sorted(f.name for f in files)[0].split("/")
    if len(first) < 3:
        raise ValueError(f"expected <subject>/<session>/<file>, got {'/'.join(first)}")
    return dict(zip(ctx.entity_names, first[:2], strict=False))


def instrument(files, ctx):
    """The instrument that produced the files, and its software version when known."""
    for file in files:
        if file.name.rsplit("/", 1)[-1] == INSTRUMENT_FILE:
            fields = Path(file.path).read_text().split()
            if fields:
                return {"id": fields[0], "software": fields[1] if len(fields) > 1 else None}
    return ctx.instruments[0] if len(ctx.instruments) == 1 else None


def pilot(files, ctx, entities):
    """Whether the sample is a pilot, kept on the `pilot` branch and local to the site."""
    return any(f.name.rsplit("/", 1)[-1] == PILOT_MARKER for f in files)


def placement(file, ctx, entities):
    """Where a file is stored in the dataset; here where it was received (the default would put
    the entity values in front of the received path)."""
    return file.name


def keep(file, ctx):
    """Whether to record a file: not hidden files and not this heuristic's own marker files."""
    base = file.name.rsplit("/", 1)[-1]
    return not base.startswith(".") and base not in (INSTRUMENT_FILE, PILOT_MARKER)


def sensitive(file, ctx):
    """Whether a file may identify a participant: kept off storage that does not take such files."""
    return file.name.endswith((".pdf", ".docx")) or file.name.rsplit("/", 1)[-1].startswith("phi")
