from datetime import datetime

import pytest
from city_scrapers_core.constants import BOARD, CANCELLED, COMMITTEE, PASSED, TENTATIVE

from city_scrapers.mixins.det_authority import JEFFERSON_LOCATION
from city_scrapers.spiders.det_downtown_development_authority import (
    DetDowntownDevelopmentAuthoritySpider,
)
from tests.det_authority_utils import VIDEO_LINK, find_item, parse_items

DETAIL_URL = "https://www.degc.org/event-details/regular-dda-board-meeting-2026-09-23-15-00"  # noqa


@pytest.fixture(scope="module")
def parsed_items():
    return parse_items(
        DetDowntownDevelopmentAuthoritySpider(), detail_urls=[DETAIL_URL]
    )


@pytest.fixture(scope="module")
def board_item(parsed_items):
    """Board meeting completed from its detail page"""
    return find_item(parsed_items, datetime(2026, 9, 23, 15))


@pytest.fixture(scope="module")
def committee_item(parsed_items):
    """Committee meeting only listed in documents"""
    return find_item(parsed_items, datetime(2026, 9, 28))


def test_count(parsed_items):
    assert len(parsed_items) == 46


def test_title(parsed_items, board_item, committee_item):
    assert board_item["title"] == "Board of Directors"
    assert committee_item["title"] == "Finance Committee"
    assert "Tigers Ticket Donation Program Committee" in [
        i["title"] for i in parsed_items
    ]


def test_description(board_item, committee_item):
    """Attendance details from the event page are kept as they are written"""
    assert board_item["description"].startswith(
        "To be held in the offices of the DEGC and online via Zoom.\n\n"
        "Topic: My Webinar\n\n"
        "Join from PC, Mac, iPad, or Android:\n"
        "https://us06web.zoom.us/j/88105431213?pwd=mvbyabjG9UoD9wfSiGag4vIWWOKCXd.1\n"
        "Passcode:600220\n"
    )
    assert board_item["description"].endswith(
        "Webinar ID: 881 0543 1213\n"
        "International numbers available: https://us06web.zoom.us/u/kcSNjuZGZ6"
    )
    assert committee_item["description"] == ""


def test_no_attendance_links(parsed_items):
    """Online attendance details go in the description, not links"""
    assert all(
        "zoom.us" not in link["href"] for i in parsed_items for link in i["links"]
    )


def test_start(parsed_items):
    assert parsed_items[0]["start"] == datetime(2025, 10, 8, 15)


def test_end(board_item):
    assert board_item["end"] is None


def test_id(board_item):
    assert (
        board_item["id"]
        == "det_downtown_development_authority/202609231500/x/board_of_directors"
    )


def test_no_duplicate_events(parsed_items):
    """Edited recurring events are listed twice, once marked as canceled"""
    ids = [i["id"] for i in parsed_items]
    assert len(ids) == len(set(ids))
    # The copy of this event that isn't canceled on the site is used
    assert find_item(parsed_items, datetime(2026, 4, 22, 15))["status"] == PASSED


def test_status(parsed_items, board_item, committee_item):
    assert board_item["status"] == PASSED
    assert committee_item["status"] == TENTATIVE
    assert find_item(parsed_items, datetime(2026, 9, 9, 15))["status"] == CANCELLED


def test_location(board_item, committee_item):
    assert board_item["location"] == JEFFERSON_LOCATION
    assert committee_item["location"] == JEFFERSON_LOCATION


def test_source(board_item, committee_item):
    assert board_item["source"] == DETAIL_URL
    assert committee_item["source"] == "https://www.degc.org/dda"


def test_links(board_item):
    assert board_item["links"] == [
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_4cab8fce96484d82bb928ae9198b6e3a.pdf",  # noqa
            "title": "REGULAR DDA BOARD MEETING AGENDA",
        },
        {
            "href": "https://www.degc.org/_files/ugd/69e7f0_bac5faf0ecee4ebc8b996ae903a646b9.pdf",  # noqa
            "title": "REGULAR DDA BOARD MEETING NOTICE",
        },
        VIDEO_LINK,
    ]


def test_classification(board_item, committee_item):
    assert board_item["classification"] == BOARD
    assert committee_item["classification"] == COMMITTEE


def test_all_day(parsed_items):
    assert all(item["all_day"] is False for item in parsed_items)


def test_video_link(parsed_items):
    assert all(item["links"][-1] == VIDEO_LINK for item in parsed_items)
