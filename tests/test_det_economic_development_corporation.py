from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import BOARD, PASSED, TENTATIVE
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.settings import Settings

from city_scrapers.spiders.det_economic_development_corporation import (
    DetEconomicDevelopmentCorporationSpider,
)

test_response = file_response(
    join(dirname(__file__), "files", "det_authority.html"),
    url="https://www.degc.org/public-authorities/",
)
spider = DetEconomicDevelopmentCorporationSpider()
spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": False})

test_prev_meetings = file_response(
    join(dirname(__file__), "files", "det_economic_development_corporation.html",),
    url="https://www.degc.org/edc/",
)
freezer = freeze_time("2021-02-10")
freezer.start()

parsed_items = [item for item in spider._next_meetings(test_response)] + [
    item for item in spider._parse_prev_meetings(test_prev_meetings)
]
parsed_items = sorted(parsed_items, key=lambda x: x["id"], reverse=True)
freezer.stop()


def test_meeting_count():
    assert len(parsed_items) == 34


def test_title():
    assert parsed_items[0]["title"] == "Board of Directors"


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2021, 6, 22, 8, 30)


def test_end():
    assert parsed_items[0]["end"] is None


def test_id():
    assert (
        parsed_items[0]["id"]
        == "det_economic_development_corporation/202106220830/x/board_of_directors"
    )


def test_status():
    assert parsed_items[0]["status"] == TENTATIVE
    assert parsed_items[-1]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == spider.location


def test_source():
    assert parsed_items[0]["source"] == test_response.url


def test_links():
    assert parsed_items[0]["links"] == []
    assert parsed_items[-1]["links"] == [
        {
            "href": "https://www.degc.org/wp-content/uploads/2020/07/02-25-20-EDC-Board-Meeting-Minutes.pdf",  # noqa
            "title": "EDC BOARD MEETING MINUTES",
        },
        {
            "href": "https://www.degc.org/wp-content/uploads/2020/07/Pages-from-February-25-2020-EDC-Board-Meeting-Agenda-Page.pdf",  # noqa
            "title": "EDC BOARD MEETING AGENDA",
        },
    ]


def test_classification():
    assert parsed_items[0]["classification"] == BOARD
    assert parsed_items[-1]["classification"] == BOARD


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
