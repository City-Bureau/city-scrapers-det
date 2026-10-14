from datetime import datetime

import pytest
from city_scrapers_core.constants import BOARD, CANCELLED, COMMITTEE, PASSED, TENTATIVE
from scrapy import Request
from scrapy.settings import Settings

from city_scrapers.mixins.det_authority import GUARDIAN_LOCATION, JEFFERSON_LOCATION
from city_scrapers.spiders.det_economic_development_corporation import (
    DetEconomicDevelopmentCorporationSpider,
)
from tests.det_authority_utils import (
    VIDEO_LINK,
    documents_response,
    find_item,
    load_events,
    parse_items,
)

DETAIL_URL = "https://www.degc.org/event-details/regular-edc-board-meeting-2026-10-13-09-00"  # noqa


@pytest.fixture(scope="module")
def parsed_items():
    return parse_items(
        DetEconomicDevelopmentCorporationSpider(), detail_urls=[DETAIL_URL]
    )


@pytest.fixture(scope="module")
def board_item(parsed_items):
    """Board meeting from the events API with matching documents"""
    return find_item(parsed_items, datetime(2026, 6, 23, 9))


@pytest.fixture(scope="module")
def committee_item(parsed_items):
    """Committee meeting only listed in documents"""
    return find_item(parsed_items, datetime(2026, 6, 23))


@pytest.fixture(scope="module")
def upcoming_item(parsed_items):
    """Upcoming meeting completed from its detail page"""
    return find_item(parsed_items, datetime(2026, 10, 13, 9))


def test_event_meetings_request_detail_pages():
    spider = DetEconomicDevelopmentCorporationSpider()
    spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": True})
    events = [e for e in load_events() if spider._is_agency_event(e)]
    requests = [
        r
        for r in spider._parse_documents(documents_response(spider), events)
        if isinstance(r, Request)
    ]
    assert DETAIL_URL in [r.url for r in requests]
    assert all(r.callback == spider._parse_event_detail for r in requests)


def test_count(parsed_items):
    assert len(parsed_items) == 55


def test_filters_other_agencies(parsed_items):
    assert all("DDA" not in link["title"] for i in parsed_items for link in i["links"])


def test_title(parsed_items, board_item, committee_item):
    assert board_item["title"] == "Board of Directors"
    assert committee_item["title"] == "Finance Committee"
    assert {i["title"] for i in parsed_items} == {
        "Board of Directors",
        "Finance Committee",
        "City Council Public Hearing",
    }


def test_description(board_item, committee_item, upcoming_item):
    assert (
        upcoming_item["description"]
        == "To be held in the offices of the DEGC and online via Zoom."
    )
    assert (
        board_item["description"]
        == "To be held in the offices of the DEGC and online via Zoom."
    )
    assert committee_item["description"] == ""


def test_start(parsed_items):
    assert parsed_items[0]["start"] == datetime(2025, 10, 14, 9)
    assert parsed_items[-1]["start"] == datetime(2027, 6, 22, 9)


def test_end(board_item):
    assert board_item["end"] is None


def test_time_notes(board_item, committee_item):
    assert board_item["time_notes"] == ""
    assert committee_item["time_notes"] == "See source to confirm meeting time"


def test_id(board_item):
    assert (
        board_item["id"]
        == "det_economic_development_corporation/202606230900/x/board_of_directors"
    )


def test_status(parsed_items, board_item, upcoming_item):
    assert board_item["status"] == PASSED
    assert upcoming_item["status"] == TENTATIVE
    # Cancellation only noted in the document title, not the event
    assert find_item(parsed_items, datetime(2026, 9, 22, 9))["status"] == CANCELLED


def test_location(board_item, committee_item, upcoming_item):
    assert board_item["location"] == GUARDIAN_LOCATION
    assert committee_item["location"] == GUARDIAN_LOCATION
    assert upcoming_item["location"] == JEFFERSON_LOCATION


def test_source(board_item, committee_item, upcoming_item):
    assert (
        board_item["source"]
        == "https://www.degc.org/event-details/regular-edc-board-meeting-2026-06-23-09-00"  # noqa
    )
    assert upcoming_item["source"] == DETAIL_URL
    assert committee_item["source"] == "https://www.degc.org/edc"


def test_links(board_item, upcoming_item):
    assert board_item["links"] == [
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_ad7db032182a42a6939fb78128809061.pdf",  # noqa
            "title": "EDC BOARD MEETING MINUTES",
        },
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_84b8b74cccc146bfb59078805f483252.pdf",  # noqa
            "title": "EDC BOARD MEETING AGENDA",
        },
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_33bbd1eccb2c4720b0ad64bb5ea5a67b.pdf",  # noqa
            "title": "EDC BOARD MEETING NOTICE",
        },
        VIDEO_LINK,
    ]
    assert upcoming_item["links"] == [VIDEO_LINK]


def test_classification(board_item, committee_item):
    assert board_item["classification"] == BOARD
    assert committee_item["classification"] == COMMITTEE


def test_all_day(parsed_items):
    assert all(item["all_day"] is False for item in parsed_items)


def test_video_link(parsed_items):
    assert all(item["links"][-1] == VIDEO_LINK for item in parsed_items)
