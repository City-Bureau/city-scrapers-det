from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import BOARD
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_employment_solutions import DetEmploymentSolutionsSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_employment_solutions.html"),
    url="https://www.descmiworks.com/about-us/public-meetings/",
)
spider = DetEmploymentSolutionsSpider()

freezer = freeze_time("2020-10-04")
freezer.start()

parsed_items = [item for item in spider.parse(test_response)]

freezer.stop()


def test_title():
    assert parsed_items[0]["title"] == ("Mayor's Workforce Development " +
                                        "Board (MWDB) Meeting")


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2020, 10, 26, 14, 0)


def test_end():
    assert parsed_items[0]["end"] == datetime(2020, 10, 26, 16, 0)


# def test_time_notes():
#     assert parsed_items[0]["time_notes"] == "EXPECTED TIME NOTES"


def test_id():
    assert parsed_items[0]["id"] == ("det_employment_solutions/202010261400/x/" +
                                     "mayor_s_workforce_development_board_mwdb_meeting")


# def test_status():
#     assert parsed_items[0]["status"] == "EXPECTED STATUS"


def test_location():
    assert parsed_items[0]["location"] == {
        "name": ("All meetings for the Mayor’s Workforce Development Board " +
                 "(MWDB) will take place at Detroit Public Safety Headquarters"),
        "address": "301 Third Ave., Detroit, MI 48226 (Location subject to change)"
    }


def test_source():
    assert parsed_items[0]["source"] == (
            "https://www.descmiworks.com/about-us/public-meetings/")


def test_links():
    assert parsed_items[0]["links"] == [{
      "href": "",
      "title": ""
    }]


def test_classification():
    assert parsed_items[0]["classification"] == BOARD 


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
