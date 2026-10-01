import json
from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import (
    ADVISORY_COMMITTEE,
    BOARD,
    CANCELLED,
    COMMITTEE,
    PASSED,
)
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse
from twisted.python.failure import Failure

from city_scrapers.spiders.det_water_sewage_department import (
    DetWaterSewageDepartmentSpider,
)

VIRTUAL_DETAILS = "\n".join(
    [
        "Attend Meeting Virtually",
        "To attend online: https://cityofdetroit.zoom.us/j/81572635118",
        "Use Passcode: 482262021",
        "Attend by phone: call one of these numbers:",
        "+1-301-715-8592",
        "+1-312-626-6799",
        "+1-267-831-0333",
        "Use Meeting ID: 815 7263 5118",
        "Use Passcode: 482262021",
    ]
)

YOUTUBE_LINK = {
    "title": "YouTube channel",
    "href": "https://www.youtube.com/@DWSD/streams",
}


def fixture(name):
    return join(dirname(__file__), "files", name)


legistar_response = file_response(
    fixture("det_water_sewage_department_legistar.html"),
    url="https://dwsd.legistar.com/Calendar.aspx",
)
list_response = file_response(
    fixture("det_water_sewage_department_list.html"),
    url="https://detroitmi.gov/Calendar-and-Events?term_node_tid_depth=171",
)
meeting_response = file_response(
    fixture("det_water_sewage_department_meeting.html"),
    url="https://detroitmi.gov/events/board-water-commissioners-june-2026-meeting",
)
committee_response = file_response(
    fixture("det_water_sewage_department_committee.html"),
    url="https://detroitmi.gov/events/board-water-commissioners-june-2026-committee-meetings",  # noqa
)

with open(fixture("det_water_sewage_department.json")) as f:
    legistar_events = json.load(f)

freezer = freeze_time("2026-09-30")
freezer.start()

spider = DetWaterSewageDepartmentSpider()
legistar_items = spider.parse_legistar(legistar_events)
board_meeting = spider.parse_event_page(meeting_response)
committee_meeting = spider.parse_event_page(committee_response)
merged_items = list(
    spider._merge_meetings([board_meeting, committee_meeting], legistar_items)
)

freezer.stop()


def find(items, title, start):
    return next(i for i in items if i["title"] == title and i["start"] == start)


# Legistar


def test_calendar_icon_column_does_not_drop_rows():
    # The core parser returned no events at all from this page
    events = DetWaterSewageDepartmentSpider()._parse_legistar_events(legistar_response)
    assert events == legistar_events
    assert len(events) == 71
    assert all("iCalendar" in event for event in events)


def legistar_table(first_cell):
    return HtmlResponse(
        url="https://dwsd.legistar.com/Calendar.aspx",
        body=f"""
        <table class="rgMasterTable">
          <tr>
            <th class="rgHeader"><input value=" " /></th>
            <th class="rgHeader">Name</th>
          </tr>
          <tr class="rgRow">
            <td>{first_cell}</td>
            <td>Board of Water Commissioners</td>
          </tr>
        </table>
        """.encode(),
    )


def test_blank_icon_header_keeps_the_row():
    # The icon column's header is only a hidden input holding a space
    response = legistar_table('<a href="View.ashx?M=IC&amp;ID=123">icon</a>')
    assert DetWaterSewageDepartmentSpider()._parse_legistar_events(response) == [
        {
            "iCalendar": {"url": "https://dwsd.legistar.com/View.ashx?M=IC&ID=123"},
            "Name": "Board of Water Commissioners",
        }
    ]


def test_onclick_link_is_read():
    response = legistar_table(
        "<a onclick=\"window.open('View.ashx?M=IC&amp;ID=456','_blank')\">icon</a>"
    )
    (event,) = DetWaterSewageDepartmentSpider()._parse_legistar_events(response)
    assert event["iCalendar"] == {
        "url": "https://dwsd.legistar.com/View.ashx?M=IC&ID=456"
    }


def test_legistar_count():
    assert len(legistar_items) == 71


def test_legistar_title():
    assert {item["title"] for item in legistar_items} == {
        "Board of Water Commissioners",
        "Audit Committee",
        "Capital Improvement Program and Operations Committee",
        "Customer Service Committee",
        "Finance Committee",
        "Human Resources/Organizational Development",
        "Legal and Government Affairs",
    }


def test_legistar_board_meeting():
    item = find(
        legistar_items, "Board of Water Commissioners", datetime(2026, 6, 17, 14)
    )
    assert item["classification"] == BOARD
    assert item["status"] == PASSED
    assert item["location"] == {"name": "TBD", "address": ""}
    assert item["description"].startswith("To attend by phone call")
    assert "https://cityofdetroit.zoom.us/j/81572635118" in item["description"]
    assert item["source"].startswith(
        "https://dwsd.legistar.com/MeetingDetail.aspx?ID=1400881"
    )
    assert item["links"] == [
        {
            "href": "https://dwsd.legistar.com/View.ashx?M=A&ID=1400881&GUID=86EB72DC-4007-48C2-8E94-CC37326D0A70",  # noqa
            "title": "Agenda",
        },
        {
            "href": "https://dwsd.legistar.com/View.ashx?M=M&ID=1400881&GUID=86EB72DC-4007-48C2-8E94-CC37326D0A70",  # noqa
            "title": "Minutes",
        },
        YOUTUBE_LINK,
    ]
    assert (
        item["id"]
        == "det_water_sewage_department/202606171400/x/board_of_water_commissioners"
    )


def test_legistar_cancelled_from_meeting_time():
    item = find(legistar_items, "Audit Committee", datetime(2026, 3, 4))
    assert item["status"] == CANCELLED


def test_rescheduled_note_does_not_cancel():
    event = dict(legistar_events[0])
    event["Meeting Location"] = (
        "BOWC Meeting The meeting has been rescheduled to Thursday, July 17, 2025"
    )
    with freeze_time("2026-09-30"):
        (item,) = spider.parse_legistar([event])
    assert item["status"] != CANCELLED


def test_committee_without_the_word_is_classified_committee():
    item = next(
        i for i in legistar_items if i["title"] == "Legal and Government Affairs"
    )
    assert item["classification"] == COMMITTEE


def test_every_legistar_body_is_kept():
    # Legistar pads some body names, like its annual Water Advisory Council
    event = {**legistar_events[0], "Name": "Water Advisory Council "}
    with freeze_time("2026-09-30"):
        (item,) = spider.parse_legistar([event])
    assert item["title"] == "Water Advisory Council"
    assert item["classification"] == ADVISORY_COMMITTEE


# detroitmi.gov


def test_event_list_requests_each_event_once():
    list_spider = DetWaterSewageDepartmentSpider()
    requests = list(list_spider._read_event_list(list_response))
    event_requests = [r for r in requests if "/events/" in r.url]
    assert len(event_requests) == 10
    assert all(r.callback == list_spider.parse_primary_event for r in event_requests)
    # The same events from the second filter are not requested again
    assert not [
        r for r in list_spider._read_event_list(list_response) if "/events/" in r.url
    ]


def test_primary_board_meeting():
    assert board_meeting["title"] == "Board of Water Commissioners"
    assert board_meeting["start"] == datetime(2026, 6, 17, 14)
    assert board_meeting["classification"] == BOARD
    assert board_meeting["location"] == {
        "name": "Water Board Building",
        "address": "735 Randolph Street, First Floor Detroit, MI 48226",
    }
    assert board_meeting["description"] == VIRTUAL_DETAILS
    assert board_meeting["links"] == [YOUTUBE_LINK]
    assert board_meeting["source"] == meeting_response.url


def test_primary_committee_meeting():
    assert (
        committee_meeting["title"] == "Board of Water Commissioners Committee Meeting"
    )
    assert committee_meeting["start"] == datetime(2026, 6, 3, 13)
    assert committee_meeting["classification"] == COMMITTEE
    # Held virtually; the attendance details are in the description
    assert committee_meeting["location"] == {"name": "TBD", "address": ""}
    assert committee_meeting["description"] == VIRTUAL_DETAILS
    assert committee_meeting["links"] == [YOUTUBE_LINK]


def test_venue_named_only_in_the_description():
    response = HtmlResponse(
        url="https://detroitmi.gov/events/board-water-commissioners-october-2026-meeting",  # noqa
        body=b"""
        <article class="description">
          <p>The board will meet at 2 p.m. at the Water Board Building.</p>
        </article>
        <article class="item location"></article>
        """,
    )
    assert spider._parse_location(response) == {
        "name": "Water Board Building",
        "address": "735 Randolph St, Detroit, MI 48226",
    }


# Combined


def test_merged_count():
    # The primary board meeting replaces its Legistar twin
    assert len(merged_items) == len(legistar_items) + 1


def test_merged_ids_unique():
    ids = [item["id"] for item in merged_items]
    assert len(ids) == len(set(ids))


def test_merged_board_meeting_takes_legistar_attachments():
    item = find(merged_items, "Board of Water Commissioners", datetime(2026, 6, 17, 14))
    assert item["source"] == meeting_response.url
    assert item["location"]["name"] == "Water Board Building"
    assert [link["title"] for link in item["links"]] == [
        "Agenda",
        "Minutes",
        "YouTube channel",
    ]
    # The primary meeting itself is left as parsed
    assert board_meeting["links"] == [YOUTUBE_LINK]


def test_committee_meeting_is_not_merged():
    item = find(
        merged_items,
        "Board of Water Commissioners Committee Meeting",
        datetime(2026, 6, 3, 13),
    )
    assert item["links"] == [YOUTUBE_LINK]
    # The board's own 12:30 meeting that day still comes from Legistar
    find(merged_items, "Board of Water Commissioners", datetime(2026, 6, 3, 12, 30))


def test_merged_meeting_takes_legistar_cancellation():
    twin = find(
        legistar_items, "Board of Water Commissioners", datetime(2026, 6, 17, 14)
    )
    cancelled_twin = twin.copy()
    cancelled_twin["status"] = CANCELLED
    (item,) = spider._merge_meetings([board_meeting], [cancelled_twin])
    assert item["status"] == CANCELLED


# Crawl bookkeeping


def test_meetings_are_held_until_every_request_settles():
    crawl_spider = DetWaterSewageDepartmentSpider()
    requests = list(crawl_spider.start_requests())
    assert len(requests) == 3
    assert crawl_spider._pending == 3

    with freeze_time("2026-09-30"):
        assert list(crawl_spider.parse_primary_event(meeting_response)) == []
        assert list(crawl_spider._on_error(Failure(IgnoreRequest()))) == []
        # The last request to settle releases everything
        crawl_spider._legistar_meetings.extend(legistar_items)
        items = list(crawl_spider.parse_primary_event(committee_response))

    assert crawl_spider._pending == 0
    assert len(items) == len(merged_items)


def test_every_start_request_is_counted_before_the_first_is_sent():
    # Scrapy pulls start requests one at a time
    crawl_spider = DetWaterSewageDepartmentSpider()
    next(crawl_spider.start_requests())
    assert crawl_spider._pending == 3


def test_a_page_that_fails_to_parse_still_settles(monkeypatch):
    crawl_spider = DetWaterSewageDepartmentSpider()
    crawl_spider._pending = 2

    def broken(response):
        raise ValueError

    monkeypatch.setattr(crawl_spider, "parse_event_page", broken)
    assert list(crawl_spider.parse_primary_event(meeting_response)) == []
    assert crawl_spider._pending == 1


@pytest.mark.parametrize("item", merged_items)
def test_all_day(item):
    assert item["all_day"] is False


@pytest.mark.parametrize("item", merged_items)
def test_youtube_link(item):
    assert item["links"][-1] == YOUTUBE_LINK
