import textwrap
from pathlib import Path

import pytest

from faire import heuristic as h

CTX = h.Context("dicoms", "a", ("subject", "session"), ("PrismaFit16001",))


def write(tmp_path, body):
    folder = tmp_path / "clone" / ".faire"
    folder.mkdir(parents=True)
    (folder / "heuristic.py").write_text(textwrap.dedent(body))
    return tmp_path / "clone"


def files(*names):
    return [h.IncomingFile(Path("/in") / n, n) for n in names]


ENTITIES_ONLY = textwrap.dedent(
    """
    def entities(files, ctx):
        return {"subject": "01", "session": "003"}
    """
)


def test_a_heuristic_implementing_only_entities_works_with_defaults(tmp_path):
    loaded = h.load(write(tmp_path, ENTITIES_ONLY))
    decision = h.decide(loaded, files("a.dcm", "sub/b.dcm"), CTX)
    assert decision.entities == {"subject": "01", "session": "003"}
    assert decision.instrument == "PrismaFit16001"  # the site's only instrument
    assert decision.software is None and decision.pilot is False
    assert [p.target for p in decision.kept] == ["01/003/a.dcm", "01/003/sub/b.dcm"]
    assert not decision.dropped and not decision.sensitive
    assert decision.subdataset is None and decision.has_setup is False


def test_a_missing_entity_fails_by_name(tmp_path):
    loaded = h.load(write(tmp_path, 'def entities(files, ctx):\n    return {"subject": "01"}\n'))
    with pytest.raises(h.MissingEntity, match="'session'"):
        h.decide(loaded, files("a.dcm"), CTX)


def test_an_undeclared_entity_is_refused(tmp_path):
    loaded = h.load(
        write(
            tmp_path,
            'def entities(files, ctx):\n    return {"subject": "1", "session": "2", "run": "3"}\n',
        )
    )
    with pytest.raises(h.HeuristicError, match="'run' is not declared"):
        h.decide(loaded, files("a.dcm"), CTX)


@pytest.mark.parametrize("value", ["../x", "a/b", "", " a", "-x"])
def test_entity_values_must_be_safe_names(tmp_path, value):
    loaded = h.load(
        write(
            tmp_path,
            f'def entities(files, ctx):\n    return {{"subject": {value!r}, "session": "1"}}\n',
        )
    )
    with pytest.raises(h.HeuristicError):
        h.decide(loaded, files("a.dcm"), CTX)


def test_optional_decisions_are_used_when_given(tmp_path):
    loaded = h.load(
        write(
            tmp_path,
            """
            def entities(files, ctx):
                return {"subject": "01", "session": "003"}
            def instrument(files, ctx):
                return {"id": "PrismaFit16002", "software": "XA60"}
            def pilot(files, ctx, entities):
                return entities["subject"] == "01"
            def keep(file, ctx):
                return not file.name.endswith(".tmp")
            def sensitive(file, ctx):
                return file.name.startswith("phi")
            def placement(file, ctx, entities):
                return "raw/" + file.name
            def subdataset(ctx, entities):
                return "sub-" + entities["subject"]
            def setup(dataset, ctx):
                pass
            """,
        )
    )
    decision = h.decide(loaded, files("a.dcm", "x.tmp", "phi.txt"), CTX)
    assert (decision.instrument, decision.software) == ("PrismaFit16002", "XA60")
    assert decision.pilot is True
    assert [f.name for f in decision.dropped] == ["x.tmp"]
    assert [(p.target, p.sensitive) for p in decision.kept] == [
        ("raw/a.dcm", False),
        ("raw/phi.txt", True),
    ]
    assert decision.subdataset == "sub-01" and decision.has_setup


def test_placements_must_be_distinct_and_inside_the_dataset(tmp_path):
    base = 'def entities(files, ctx):\n    return {"subject": "1", "session": "2"}\n'
    same = h.load(write(tmp_path / "same", base + 'def placement(f, c, e):\n    return "x"\n'))
    with pytest.raises(h.HeuristicError, match="both placed at x"):
        h.decide(same, files("a", "b"), CTX)
    for bad in ("../x", "/etc/passwd", ".git/hooks/x", "."):
        loaded = h.load(
            write(
                tmp_path / bad.replace("/", "_"),
                base + f"def placement(f, c, e):\n    return {bad!r}\n",
            )
        )
        with pytest.raises(h.HeuristicError):
            h.decide(loaded, files("a"), CTX)


def test_the_instrument_is_unknown_with_several_and_no_function(tmp_path):
    loaded = h.load(write(tmp_path, ENTITIES_ONLY))
    ctx = h.Context("dicoms", "a", ("subject", "session"), ("P1", "P2"))
    assert h.decide(loaded, files("a"), ctx).instrument is None


def test_errors_in_the_heuristic_are_reported_as_such(tmp_path):
    loaded = h.load(write(tmp_path, "def entities(files, ctx):\n    raise KeyError('x')\n"))
    with pytest.raises(h.HeuristicError, match="'entities' failed: KeyError"):
        h.decide(loaded, files("a"), CTX)


def test_loading_requires_the_file_and_the_function(tmp_path):
    with pytest.raises(h.HeuristicError, match="no heuristic"):
        h.load(tmp_path)
    with pytest.raises(h.HeuristicError, match="`entities` is required"):
        h.load(write(tmp_path / "x", "def pilot(f, c, e):\n    return False\n"))
    with pytest.raises(h.HeuristicError, match="cannot be loaded"):
        h.load(write(tmp_path / "y", "raise RuntimeError('broken')\n"))
    with pytest.raises(h.HeuristicError, match="'pilot' is not a function"):
        h.load(write(tmp_path / "z", ENTITIES_ONLY + "pilot = 3\n"))


def test_the_revision_follows_the_file_content(tmp_path):
    a = h.load(write(tmp_path / "a", ENTITIES_ONLY))
    b = h.load(write(tmp_path / "b", ENTITIES_ONLY + "# changed\n"))
    again = h.load(write(tmp_path / "c", ENTITIES_ONLY))
    assert a.revision == again.revision != b.revision
