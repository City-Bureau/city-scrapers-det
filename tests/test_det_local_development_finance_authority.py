from datetime import datetime

import pytest
from city_scrapers_core.constants import BOARD, PASSED, TENTATIVE

from city_scrapers.mixins.det_authority import GUARDIAN_LOCATION, JEFFERSON_LOCATION
from city_scrapers.spiders.det_local_development_finance_authority import (  # noqa
    DetLocalDevelopmentFinanceAuthoritySpider,
)
from tests.det_authority_utils import find_item, parse_items


@pytest.fixture(scope="module")
def parsed_items():
    return parse_items(DetLocalDevelopmentFinanceAuthoritySpider())


@pytest.fixture(scope="module")
def doc_item(parsed_items):
    """Meeting only listed in documents"""
    return find_item(parsed_items, datetime(2026, 6, 16))


@pytest.fixture(scope="module")
def event_item(parsed_items):
    """Upcoming meeting from the events API"""
    return find_item(parsed_items, datetime(2026, 10, 27, 10))


def test_count(parsed_items):
    assert len(parsed_items) == 10


def test_title(doc_item, event_item):
    assert doc_item["title"] == "Board of Directors"
    assert event_item["title"] == "Board of Directors"


def test_description(doc_item):
    assert doc_item["description"] == ""


def test_end(event_item):
    assert event_item["end"] is None


def test_id(event_item):
    assert event_item["id"] == (
        "det_local_development_finance_authority/202610271000/x/board_of_directors"  # noqa
    )


def test_status(doc_item, event_item):
    assert doc_item["status"] == PASSED
    assert event_item["status"] == TENTATIVE


def test_location(doc_item, event_item):
    assert doc_item["location"] == GUARDIAN_LOCATION
    assert event_item["location"] == JEFFERSON_LOCATION


def test_source(doc_item, event_item):
    assert doc_item["source"] == "https://www.degc.org/ldfa"
    assert event_item["source"] == (
        "https://www.degc.org/event-details/ldfa-board-meeting-2026-10-27-10-00"  # noqa
    )


def test_links(doc_item):
    assert doc_item["links"][0]["href"].startswith("https://www.degc.org/_files/")


def test_classification(doc_item, event_item):
    assert doc_item["classification"] == BOARD
    assert event_item["classification"] == BOARD


def test_all_day(parsed_items):
    assert all(item["all_day"] is False for item in parsed_items)
