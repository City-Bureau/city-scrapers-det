"""Run the harambe contract against real create_ocd_event output.

Every harambe meeting is built by ``create_ocd_event``, so these checks apply to
every harambe scraper without any of them opting in. The parametrised cases
below are the inputs that funnel has actually been handed in production,
including the two that broke.
"""

import pytest

from harambe_scrapers.utils import create_ocd_event, localize_iso_datetime
from tests.harambe_contract import (
    CHECKS,
    KNOWN_SILENT_EXCEPT,
    baseline_key,
    harambe_modules,
    run_event_checks,
    scraper_segment,
    silent_except_blocks,
    summary_line,
)

CHECK_IDS = [check_id for check_id, _, _ in CHECKS]

AGENCY = "Wayne County Commission"
TIMEZONE = "America/Detroit"


def event(**overrides):
    """Build an event the way a scraper does, with per-case overrides."""
    values = {
        "title": "Ways and Means Committee",
        "start_time": localize_iso_datetime("2026-03-25T10:00:00", TIMEZONE),
        "scraper_name": "wayne_ways_means",
        "agency_name": AGENCY,
        "timezone": TIMEZONE,
        "source_url": "https://www.waynecountymi.gov/meeting/12345",
    }
    values.update(overrides)
    return create_ocd_event(**values)


# The shapes create_ocd_event is handed by scrapers in this repo. Each has to
# come out the other side satisfying every check.
CASES = {
    "start only, no end": {},
    "with an end time": {
        "end_time": localize_iso_datetime("2026-03-25T12:00:00", TIMEZONE)
    },
    "cancelled": {"is_cancelled": True},
    "past meeting": {
        "start_time": localize_iso_datetime("2020-01-14T09:30:00", TIMEZONE)
    },
    "all day": {"all_day": True},
    "no location given": {"location": None},
    "with links": {
        "links": [
            {"url": "https://example.org/agenda.pdf", "title": "Agenda"},
            {"url": "https://zoom.us/j/123", "title": "Zoom"},
        ]
    },
    "classified": {"classification": "Committee"},
    "derived scraper name": {"scraper_name": "wayne_seniors_and_veterans_affairs"},
}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("check_id", CHECK_IDS)
def test_funnel_output_satisfies_contract(check_id, case):
    results = {r.check_id: r for r in run_event_checks(event(**CASES[case]))}
    result = results[check_id]
    assert (
        result.passed
    ), f"{case!r} fails {check_id} ({summary_line(check_id)}): {result.detail}"


# -- the two bugs this repo shipped ----------------------------------------


def test_h01_rejects_a_comma_joined_scraper_name():
    """The Wayne County bug: thirteen names glued into one prefix.

    Every meeting carried this, the importer matched no agency, and nothing was
    ingested for months while every run reported success.
    """
    glued = ", ".join(
        [
            "wayne_full_commission",
            "wayne_ways_means",
            "wayne_committee_of_the_whole",
        ]
    )
    results = {r.check_id: r for r in run_event_checks(event(scraper_name=glued))}
    assert not results["H01"].passed
    assert "single registered identifier" in results["H01"].detail


def test_scraper_segment_matches_what_the_importer_reads():
    """H01 is only meaningful if it reads the same substring the importer does."""
    built = event(scraper_name="wayne_ways_means")
    assert scraper_segment(built) == "wayne_ways_means"
    assert built["extras"]["cityscrapers/id"].startswith("wayne_ways_means/")


def test_h05_rejects_an_end_before_the_start():
    """The lone-start-time bug's neighbour: a range parsed the wrong way round."""
    built = event(
        start_time=localize_iso_datetime("2026-03-25T14:00:00", TIMEZONE),
        end_time=localize_iso_datetime("2026-03-25T09:30:00", TIMEZONE),
    )
    results = {r.check_id: r for r in run_event_checks(built)}
    assert not results["H05"].passed


def test_h05_accepts_a_meeting_with_no_end_time():
    """Pages that publish only a start time are legitimate, not a defect."""
    results = {r.check_id: r for r in run_event_checks(event(end_time=None))}
    assert results["H05"].passed


@pytest.mark.parametrize(
    "bad_name",
    [
        "wayne_ways_means, wayne_audit",
        "Wayne Ways Means",
        "wayne ways means",
        "",
    ],
)
def test_h01_rejects_every_unusable_scraper_name(bad_name):
    results = {r.check_id: r for r in run_event_checks(event(scraper_name=bad_name))}
    assert not results["H01"].passed


def test_h09_catches_a_scraper_name_h01_cannot_see():
    """A slash truncates the prefix instead of malforming it.

    'wayne/ways/means' leaves 'wayne' as the segment the importer reads, which
    is a perfectly well-formed name for the wrong agency - so H01 passes and
    only the segment count gives it away.
    """
    results = {
        r.check_id: r for r in run_event_checks(event(scraper_name="wayne/ways/means"))
    }
    assert results["H01"].passed
    assert not results["H09"].passed


# -- source policy ---------------------------------------------------------


def test_harambe_modules_are_discovered():
    names = {p.name for p in harambe_modules()}
    assert "utils.py" in names
    assert "wayne_commission.py" in names


@pytest.mark.parametrize(
    "module",
    harambe_modules(),
    ids=lambda p: baseline_key(p) if hasattr(p, "name") else str(p),
)
def test_no_silent_exception_swallowing(module):
    """except/pass with no log is how one bad page becomes one missing meeting."""
    key = baseline_key(module)
    hits = silent_except_blocks(module.read_text())
    if key in KNOWN_SILENT_EXCEPT:
        assert hits, (
            f"{key} no longer swallows exceptions silently. Remove its entry "
            f"from KNOWN_SILENT_EXCEPT in tests/harambe_contract.py so the "
            f"check stays enforced there."
        )
        pytest.xfail(KNOWN_SILENT_EXCEPT[key])
    assert not hits, (
        f"{key} has {len(hits)} 'except: pass/continue' block(s) with no "
        f"logging: {hits}"
    )


def test_silent_except_baseline_names_real_modules():
    known = set(harambe_modules())
    listed = {baseline_key(m) for m in known}
    unknown = sorted(set(KNOWN_SILENT_EXCEPT) - listed)
    assert (
        not unknown
    ), f"KNOWN_SILENT_EXCEPT lists modules that do not exist: {unknown}"
