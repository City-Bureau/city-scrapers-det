from datetime import datetime
from os.path import dirname, join

import pytest  # noqa
from city_scrapers_core.constants import BOARD, TENTATIVE
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_board_ethics import DetBoardEthicsSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_board_ethics.html"),
    url="https://detroitmi.gov/events/detroit-board-ethics-general-meeting-april-21-2021",  # noqa
)
spider = DetBoardEthicsSpider()

freezer = freeze_time("2021-03-24")
freezer.start()

item = spider.parse_event_page(test_response)

freezer.stop()


def test_title():
    assert item["title"] == "Board of Ethics"


def test_description():
    assert item["description"] == ""


def test_start():
    assert item["start"] == datetime(2021, 4, 21, 14)


def test_end():
    assert item["end"] is None


def test_time_notes():
    assert item["time_notes"] == ""


def test_id():
    assert item["id"] == "det_board_ethics/202104211400/x/board_of_ethics"


def test_status():
    assert item["status"] == TENTATIVE


def test_location():
    assert item["location"] == {"name": "", "address": ""}


def test_source():
    assert item["source"] == test_response.url


def test_links():
    assert item["links"] == []


def test_all_day():
    assert item["all_day"] is False


def test_classification():
    assert item["classification"] == BOARD
