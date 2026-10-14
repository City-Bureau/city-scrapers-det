import logging
from datetime import datetime

import pytest
from city_scrapers_core.constants import (
    ADVISORY_COMMITTEE,
    BOARD,
    COMMITTEE,
    FORUM,
    PASSED,
    TENTATIVE,
)
from scrapy import Request
from scrapy.settings import Settings
from twisted.python.failure import Failure

from city_scrapers.mixins.det_authority import JEFFERSON_LOCATION, TBD_LOCATION
from city_scrapers.spiders.det_brownfield_redevelopment_authority import (
    DetBrownfieldRedevelopmentAuthoritySpider,
)
from tests.det_authority_utils import (
    detail_response,
    documents_response,
    find_item,
    parse_items,
)

DETAIL_URL = "https://www.degc.org/event-details/regular-dbra-board-meeting-2026-12-16-16-00"  # noqa


@pytest.fixture
def spider():
    spider = DetBrownfieldRedevelopmentAuthoritySpider()
    spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": True})
    return spider


@pytest.fixture(scope="module")
def parsed_items():
    return parse_items(
        DetBrownfieldRedevelopmentAuthoritySpider(), detail_urls=[DETAIL_URL]
    )


@pytest.fixture(scope="module")
def board_item(parsed_items):
    return find_item(parsed_items, datetime(2026, 9, 23, 16))


@pytest.fixture(scope="module")
def detail_item(parsed_items):
    """Recurring meeting whose description is only on its detail page"""
    return find_item(parsed_items, datetime(2026, 12, 16, 16))


@pytest.fixture(scope="module")
def cac_item(parsed_items):
    return find_item(parsed_items, datetime(2026, 9, 23, 17))


@pytest.fixture(scope="module")
def hearing_item(parsed_items):
    return find_item(parsed_items, datetime(2026, 9, 29, 17))


@pytest.fixture(scope="module")
def lbrf_item(parsed_items):
    return find_item(parsed_items, datetime(2026, 6, 10, 15, 45))


@pytest.fixture(scope="module")
def council_hearing_item(parsed_items):
    return find_item(parsed_items, datetime(2026, 7, 2))


def detail_meeting():
    return {
        "title": "Board of Directors",
        "description": "",
        "classification": BOARD,
        "start": datetime(2026, 12, 16, 16),
        "end": None,
        "time_notes": "",
        "all_day": False,
        "location": JEFFERSON_LOCATION,
        "links": [],
        "source": DETAIL_URL,
        "_status_text": "Regular DBRA Board Meeting",
    }


def test_count(parsed_items):
    assert len(parsed_items) == 114


def test_title(board_item, cac_item, lbrf_item, hearing_item, council_hearing_item):
    assert board_item["title"] == "Board of Directors"
    assert cac_item["title"] == "Community Advisory Committee"
    assert lbrf_item["title"] == "Local Brownfield Revolving Fund Committee"
    assert (
        hearing_item["title"]
        == "Renaissance Center And Rivereast District Local Public Hearing"
    )
    assert (
        council_hearing_item["title"]
        == "Stockbridge Renaissance City Council Public Hearing"
    )


def test_description(board_item, detail_item, hearing_item):
    assert board_item["description"] == ""
    # The events API has no description for this date, the detail page does
    assert detail_item["description"].startswith(
        "Join from PC, Mac, iPad, or Android:\n"
        "https://us06web.zoom.us/j/84843111872?pwd=fauZTbIatYPSOeFUPVS2q0Cs9JyX1s.1\n"
        "Passcode:241288\n\n"
        "Phone one-tap:\n"
    )
    assert detail_item["description"].endswith(
        "Webinar ID: 848 4311 1872\n"
        "International numbers available: https://us06web.zoom.us/u/kw7fMeyk4"
    )
    assert hearing_item["description"] == (
        "Please note that this is an in-person meeting."
    )


def test_description_without_detail_page():
    items = parse_items(DetBrownfieldRedevelopmentAuthoritySpider())
    assert find_item(items, datetime(2026, 12, 16, 16))["description"] == ""


def test_detail_page_rendered_fallback(spider):
    """Use the rendered "About the event" section if the event data is missing"""
    response = detail_response(spider, DETAIL_URL)
    response = response.replace(
        body=response.body.replace(b'id="wix-warmup-data"', b'id="removed"')
    )
    item = next(spider._parse_event_detail(response, meeting=detail_meeting()))
    assert item["description"].startswith(
        "Join from PC, Mac, iPad, or Android:\n"
        "https://us06web.zoom.us/j/84843111872?pwd=fauZTbIatYPSOeFUPVS2q0Cs9JyX1s.1\n"
        "Passcode:241288"
    )


def test_detail_page_error_keeps_meeting(spider, caplog):
    request = Request(DETAIL_URL, cb_kwargs={"meeting": detail_meeting()})
    failure = Failure(Exception("timed out"))
    failure.request = request
    with caplog.at_level(logging.WARNING):
        items = list(spider._handle_detail_error(failure))
    assert [i["id"] for i in items] == [
        "det_brownfield_redevelopment_authority/202612161600/x/board_of_directors"
    ]
    assert "Could not read the event page" in caplog.text


def test_empty_documents_page_is_logged(spider, caplog):
    response = documents_response(spider).replace(body=b"")
    with caplog.at_level(logging.WARNING):
        assert list(spider._parse_documents(response)) == []
    assert "No dated meeting documents found" in caplog.text


def test_start(parsed_items):
    assert parsed_items[0]["start"] == datetime(2025, 10, 2, 17)


def test_end(board_item):
    assert board_item["end"] is None


def test_id(board_item):
    assert (
        board_item["id"]
        == "det_brownfield_redevelopment_authority/202609231600/x/board_of_directors"
    )


def test_status(board_item, detail_item, hearing_item):
    assert board_item["status"] == PASSED
    assert hearing_item["status"] == TENTATIVE
    assert detail_item["status"] == TENTATIVE


def test_location(parsed_items, board_item, hearing_item, council_hearing_item):
    assert board_item["location"] == JEFFERSON_LOCATION
    assert hearing_item["location"] == {
        "name": "Coleman A. Young Municipal Center",
        "address": "2 Woodward Ave, Detroit, MI 48226",
    }
    assert parsed_items[0]["location"] == {
        "name": "",
        "address": "2826 Bagley St, Detroit, MI 48216",
    }
    assert council_hearing_item["location"] == TBD_LOCATION


def test_source(board_item, detail_item, council_hearing_item):
    assert (
        board_item["source"]
        == "https://www.degc.org/event-details/regular-dbra-board-meeting-2026-09-23-16-00"  # noqa
    )
    assert detail_item["source"] == DETAIL_URL
    assert council_hearing_item["source"] == "https://www.degc.org/dbra"


def test_links(board_item, cac_item, hearing_item, detail_item):
    assert board_item["links"] == [
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_19b21bcae72c4df692ee6be5d46b01f8.pdf",  # noqa
            "title": "DBRA REGULAR BOARD MEETING NOTICE",
        },
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_58a6738bc8dd4411861642984e420191.pdf",  # noqa
            "title": "DBRA REGULAR BOARD MEETING AGENDA",
        },
    ]
    assert cac_item["links"] == [
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_f3925068cc7d4419a2887025c3a77790.pdf",  # noqa
            "title": "DBRA-CAC REGULAR MEETING NOTICE",
        },
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_cccf7234270c4398bc1dfa5b51c28b3a.pdf",  # noqa
            "title": "DBRA-CAC REGULAR MEETING AGENDA",
        },
    ]
    # Documents matched to an event with a different title on the same day
    assert hearing_item["links"] == [
        {
            "href": "https://www.degc.org/_files/ugd/5bbdb1_4ad24a27cde84f5fbf0b9e78681304ea.pdf",  # noqa
            "title": "RENAISSANCE CENTER AND RIVEREAST DISTRICT LOCAL PUBLIC HEARING NOTICE",  # noqa
        }
    ]
    # Zoom details are in the description rather than links
    assert detail_item["links"] == []


def test_classification(board_item, cac_item, lbrf_item, hearing_item):
    assert board_item["classification"] == BOARD
    assert cac_item["classification"] == ADVISORY_COMMITTEE
    assert lbrf_item["classification"] == COMMITTEE
    assert hearing_item["classification"] == FORUM


def test_all_day(parsed_items):
    assert all(item["all_day"] is False for item in parsed_items)
