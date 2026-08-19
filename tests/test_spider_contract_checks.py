"""Tests for the contract checks themselves.

A check that never fires is worse than no check: it reports green forever and
nobody notices. Each test here hands one check an input it is supposed to
reject, and asserts it does - so the suite in test_spider_contract.py is known
to be measuring something.

C05 is the missing-end-time case that started this: a meeting whose end is
before its start used to reach production unremarked.
"""

from datetime import datetime, timedelta, timezone

import pytest
from city_scrapers_core.items import Meeting

from tests import spider_contract as sc

NOW = datetime(2026, 3, 25, 10, 0)


def meeting(**overrides):
    """A meeting that passes every output check, before overrides."""
    values = {
        "id": "det_test/202603251000/x/board_of_directors",
        "title": "Board of Directors",
        "description": "",
        "classification": "Board",
        "status": "passed",
        "start": NOW,
        "end": None,
        "all_day": False,
        "time_notes": "",
        "location": {"name": "City Hall", "address": "2 Woodward Ave, Detroit, MI"},
        "links": [{"href": "https://example.org/agenda.pdf", "title": "Agenda"}],
        "source": "https://example.org/calendar",
    }
    values.update(overrides)
    return Meeting(**values)


def context(meetings=None, source="", degraded=None, **kwargs):
    ctx = sc.SpiderContext(
        name="det_test",
        spider=None,
        source=source,
        meetings=[] if meetings is None else meetings,
        **kwargs,
    )
    ctx.degraded = degraded or {}
    return ctx


def run(check_id, ctx):
    """Run one check by id and return its detail, or None if it passed."""
    for cid, _summary, requires_meetings, fn in sc.CHECKS:
        if cid == check_id:
            if requires_meetings and not ctx.meetings:
                pytest.fail(f"{check_id} needs meetings; the test gave it none")
            return fn(ctx)
    pytest.fail(f"no check with id {check_id}")


def healthy_degradation():
    """Degraded runs that every silence check accepts."""
    return {
        label: {"meetings": [], "requests": 0, "raised": None, "logged": ["no rows"]}
        for label in ("empty", "truncated", "undated")
    }


# -- output shape -----------------------------------------------------------


def test_c01_fires_when_nothing_parses():
    assert run("C01", context())


def test_c01_names_the_missing_callback_fixture():
    detail = run("C01", context(requests_yielded=3))
    assert "callback" in detail


def test_c02_fires_on_a_foreign_id_prefix():
    assert run("C02", context([meeting(id="wayne_county/202603251000/x/board")]))


def test_c03_fires_on_duplicate_ids():
    assert run("C03", context([meeting(), meeting()]))


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"start": None},
        {"start": "2026-03-25T10:00"},
        {"source": ""},
    ],
)
def test_c04_fires_on_a_missing_required_field(overrides):
    assert run("C04", context([meeting(**overrides)]))


def test_c05_fires_when_end_precedes_start():
    assert run("C05", context([meeting(end=NOW - timedelta(hours=1))]))


def test_c05_accepts_an_absent_end():
    assert run("C05", context([meeting(end=None)])) is None


def test_c05_accepts_an_end_after_the_start():
    assert run("C05", context([meeting(end=NOW + timedelta(hours=2))])) is None


def test_c06_fires_on_mixed_datetime_awareness():
    aware = meeting(start=NOW.replace(tzinfo=timezone.utc))
    assert run("C06", context([meeting(), aware]))


def test_c07_fires_on_an_invented_classification():
    assert run("C07", context([meeting(classification="Board Of Directors")]))


def test_c08_fires_on_an_invented_status():
    assert run("C08", context([meeting(status="happened")]))


@pytest.mark.parametrize(
    "location",
    [
        "City Hall",
        {"name": "City Hall"},
        {"address": "2 Woodward Ave"},
        {"name": "", "address": ""},
    ],
)
def test_c09_fires_on_a_malformed_location(location):
    assert run("C09", context([meeting(location=location)]))


@pytest.mark.parametrize(
    "links",
    [
        "https://example.org/agenda.pdf",
        [{"url": "https://example.org/agenda.pdf"}],
        [{"href": ""}],
    ],
)
def test_c10_fires_on_malformed_links(links):
    assert run("C10", context([meeting(links=links)]))


def test_c10_accepts_an_empty_link_list():
    assert run("C10", context([meeting(links=[])])) is None


def test_c11_fires_on_markup_left_in_a_title():
    assert run("C11", context([meeting(title="Board <br> of Directors")]))


# -- behaviour under degraded input -----------------------------------------


@pytest.mark.parametrize("label,check_id", [("empty", "C12"), ("truncated", "C13")])
def test_silence_checks_fire_on_a_quiet_empty_result(label, check_id):
    degraded = healthy_degradation()
    degraded[label] = {
        "meetings": [],
        "requests": 0,
        "raised": None,
        "logged": [],
    }
    assert run(check_id, context([meeting()], degraded=degraded))


def test_c14_fires_on_a_quiet_undated_result():
    degraded = healthy_degradation()
    degraded["undated"] = {
        "meetings": [],
        "requests": 0,
        "raised": None,
        "logged": [],
    }
    assert run("C14", context([meeting()], degraded=degraded))


def test_silence_check_accepts_a_raised_exception():
    degraded = healthy_degradation()
    degraded["empty"] = {
        "meetings": [],
        "requests": 0,
        "raised": "IndexError: list index out of range",
        "logged": [],
    }
    assert run("C12", context([meeting()], degraded=degraded)) is None


def test_silence_check_accepts_a_warning_log():
    assert run("C12", context([meeting()], degraded=healthy_degradation())) is None


def test_c15_fires_when_degraded_input_yields_a_startless_meeting():
    degraded = healthy_degradation()
    degraded["undated"] = {
        "meetings": [meeting(start=None)],
        "requests": 0,
        "raised": None,
        "logged": [],
    }
    assert run("C15", context([meeting()], degraded=degraded))


# -- source policy ----------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    parse(x)\nexcept Exception:\n    pass\n",
        "try:\n    parse(x)\nexcept ValueError:\n    continue\n",
        "try:\n    parse(x)\nexcept:\n    pass\n",
    ],
)
def test_c16_fires_on_a_bare_swallow(source):
    assert run("C16", context(source=source))


def test_c16_accepts_a_swallow_that_logs():
    source = (
        "try:\n"
        "    parse(x)\n"
        "except ValueError:\n"
        "    logger.warning('could not parse %s', x)\n"
        "    continue\n"
    )
    assert run("C16", context(source=source)) is None


def test_c17_fires_on_a_spoofed_user_agent():
    source = (
        "headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}"
    )
    assert run("C17", context(source=source))


def test_c17_accepts_an_honest_user_agent():
    source = "USER_AGENT = 'City Scrapers (+https://cityscrapers.org)'"
    assert run("C17", context(source=source)) is None


def test_c18_fires_on_a_hardcoded_cookie():
    source = "headers = {'Cookie': 'ASP.NET_SessionId=abc123def456'}"
    assert run("C18", context(source=source))


def test_c19_fires_when_ids_are_hand_rolled():
    source = "meeting['id'] = f\"{self.name}/{start:%Y%m%d%H%M}/x/{slug}\"\n"
    assert run("C19", context([meeting()], source=source))


def test_c19_accepts_the_framework_helpers():
    source = (
        "meeting['status'] = self._get_status(meeting)\n"
        "meeting['id'] = self._get_id(meeting)\n"
    )
    assert run("C19", context([meeting()], source=source)) is None
