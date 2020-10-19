from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import BOARD, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_regional_convention import DetRegionalConventionSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_regional_convention.html"),
    url="http://www.drcfa.org/upcoming-meetings",
)
spider = DetRegionalConventionSpider()

freezer = freeze_time("2020-10-19")
freezer.start()

parsed_items = [item for item in spider.parse(test_response)]

freezer.stop()


def test_title():
    assert (
        parsed_items[0]["title"]
        == "Boards of directors of Detroit Regional \
        Convention Facility Authority"
    )


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2015, 1, 29, 8, 30)


def test_end():
    assert parsed_items[0]["end"] is None


def test_time_notes():
    assert parsed_items[0]["time_notes"] == ""


def test_id():
    assert (
        parsed_items[0]["id"]
        == "det_regional_convention/201501290830/x/"
        + "boards_of_directors_of_detroit_regional_convention_facility_authority"
    )


def test_status():
    assert parsed_items[0]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == {
        "address": "1 Washington Blvd, Detroit, MI 48226",
        "name": "Cobo Conference and Exhibition Center",
    }


def test_source():
    assert parsed_items[0]["source"] == "http://www.drcfa.org/upcoming-meetings"


def test_links():
    assert parsed_items[0]["links"] == [
        {
            "href": "http://www.drcfa.org/assets/doc/Approved-Minutes-1-29-15.pdf",
            "title": "Approved DRCFA Minutes January 29, 2015",
        }
    ]


def test_classification():
    assert parsed_items[0]["classification"] == BOARD


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
