from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import COMMITTEE, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.settings import Settings

from city_scrapers.spiders.det_land_bank import DetLandBankSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_land_bank.html"),
    url="https://buildingdetroit.org/events/meetings",
)
spider = DetLandBankSpider()
spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": False})

freezer = freeze_time("2019-01-01")
freezer.start()
parsed_items = [item for item in spider.parse(test_response)]
parsed_items = sorted(parsed_items, key=lambda x: x["start"])
freezer.stop()


def test_count():
    assert len(parsed_items) == 50


def test_title():
    assert parsed_items[0]["title"] == "Finance/Audit Committee"


def test_description():
    assert parsed_items[0]["description"] == "Tuesday’s at 1:00 p.m."


def test_start():
    assert parsed_items[0]["start"] == datetime(2018, 1, 9, 13, 0)


def test_end():
    assert parsed_items[0]["end"] is None


def test_id():
    assert (
        parsed_items[0]["id"] == "det_land_bank/201801091300/x/finance_audit_committee"
    )


def test_status():
    assert parsed_items[0]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == {
        "name": "",
        "address": "500 Griswold St, Suite 1200 Detroit, Michigan 48226",
    }


def test_source():
    assert parsed_items[0]["source"] == "https://buildingdetroit.org/events/meetings"


def test_links():
    assert parsed_items[0]["links"] == []


def test_classification():
    assert parsed_items[0]["classification"] == COMMITTEE


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
