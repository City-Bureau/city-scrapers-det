from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import BOARD, CANCELLED, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.settings import Settings

from city_scrapers.spiders.det_next_michigan_development_corporation import (
    DetNextMichiganDevelopmentCorporationSpider,
)

test_response = file_response(
    join(dirname(__file__), "files", "det_authority.html"),
    url="https://www.degc.org/public-authorities/",
)
spider = DetNextMichiganDevelopmentCorporationSpider()
spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": False})

test_prev_meetings = file_response(
    join(dirname(__file__), "files", "det_next_michigan_development_corporation.html"),
    url="https://www.degc.org/d-nmdc/",
)
freezer = freeze_time("2021-02-10")
freezer.start()

parsed_items = [item for item in spider._next_meetings(test_response)] + [
    item for item in spider._parse_prev_meetings(test_prev_meetings)
]
parsed_items = sorted(parsed_items, key=lambda x: x["id"], reverse=True)
freezer.stop()


def test_meeting_count():
    assert len(parsed_items) == 2


def test_title():
    assert parsed_items[0]["title"] == "Board of Directors"


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2020, 12, 8, 0)


def test_end():
    assert parsed_items[0]["end"] is None


def test_id():
    assert (
        parsed_items[0]["id"]
        == "det_next_michigan_development_corporation/202012080000/x/board_of_directors"
    )


def test_status():
    assert parsed_items[0]["status"] == CANCELLED
    assert parsed_items[-1]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == spider.location


def test_source():
    assert parsed_items[0]["source"] == "https://www.degc.org/d-nmdc/"


def test_links():
    assert parsed_items[0]["links"] == [
        {
            "href": "https://www.degc.org/wp-content/uploads/2020/12/"
            + "12-08-20-DNMDC-Cancellation-Notice.pdf",
            "title": "D-NMDC BOARD MEETING CANCELLATION NOTICE",
        }
    ]


def test_classification():
    assert parsed_items[0]["classification"] == BOARD
    assert parsed_items[-1]["classification"] == BOARD


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
