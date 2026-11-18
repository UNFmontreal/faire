"""Routing a sample to the instance of the instrument that produced it."""

import pytest

from faire import indexing
from faire.platform.fake import FakePlatform
from indexfix import GROUP, git, received, request

pytestmark = pytest.mark.integration

P1, P2 = "dicoms-a_PrismaFit16001", "dicoms-a_PrismaFit16002"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def sample(instrument, software=None):
    marker = f"{instrument} {software}\n" if software else f"{instrument}\n"
    return {"01/003/a.txt": "scan\n", "01/003/instrument.txt": marker}


def head(platform, repo):
    return git(platform.get_repository(GROUP, repo).url, "rev-parse", "dev")


def test_the_sample_is_recorded_in_the_instance_of_its_instrument_only(project, platform, tmp_path):
    project.add_instrument("PrismaFit16002", "a")
    project.init(platform=platform, group=GROUP)
    first, second = head(platform, P1), head(platform, P2)
    out = indexing.index(request(project, platform, received(tmp_path, sample("PrismaFit16002"))))
    assert out.instance == "a_PrismaFit16002"
    assert head(platform, P1) == first  # the other scanner's instance is untouched
    assert head(platform, P2) != second
    assert "faire-instrument: PrismaFit16002" in git(
        platform.get_repository(GROUP, P2).url, "log", "dev", "--format=%B"
    )


def test_a_software_update_keeps_the_instance_and_is_recorded_with_the_sample(
    project, platform, tmp_path
):
    project.init(platform=platform, group=GROUP)
    indexing.index(request(project, platform, received(tmp_path, sample("PrismaFit16001", "XA50"))))
    later = {**sample("PrismaFit16001", "XA60"), "01/004/a.txt": "scan\n"}
    later["01/004/instrument.txt"] = later.pop("01/003/instrument.txt")
    later.pop("01/003/a.txt")
    out = indexing.index(request(project, platform, received(tmp_path, later, name="later")))
    assert out.instance == "a_PrismaFit16001"
    log = git(platform.get_repository(GROUP, P1).url, "log", "dev", "--format=%B")
    assert "faire-software: XA50" in log and "faire-software: XA60" in log
    assert log.count("faire-instrument: PrismaFit16001") == 2


def test_an_instrument_of_another_site_records_nothing(project, platform, tmp_path):
    project.add_instrument("Skyra45012", "b")
    project.init(platform=platform, group=GROUP)
    before = head(platform, P1)
    with pytest.raises(indexing.IndexingError) as raised:
        indexing.index(request(project, platform, received(tmp_path, sample("Skyra45012"))))
    assert "Skyra45012" in str(raised.value) and "'b'" in str(raised.value)
    assert head(platform, P1) == before
