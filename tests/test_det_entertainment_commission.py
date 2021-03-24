from datetime import datetime
from os.path import dirname, join

import pytest  # noqa
from city_scrapers_core.constants import COMMISSION, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_entertainment_commission import (
    DetEntertainmentCommissionSpider,
)

test_response = file_response(
    join(dirname(__file__), "files", "det_entertainment_commission.html"),
    url="https://detroitmi.gov/events/detroit-entertainment-commission-meeting-3-15-2021",  # noqa
)

freezer = freeze_time("2021-03-24")
freezer.start()

spider = DetEntertainmentCommissionSpider()
item = spider.parse_event_page(test_response)

freezer.stop()


def test_title():
    assert item["title"] == "Entertainment Commission"


def test_description():
    assert item["description"] == ""


def test_start():
    assert item["start"] == datetime(2021, 3, 15, 17)


def test_end():
    assert item["end"] == datetime(2021, 3, 15, 20)


def test_time_notes():
    assert item["time_notes"] == "Estimated 3 hour duration"


def test_id():
    assert (
        item["id"]
        == "det_entertainment_commission/202103151700/x/entertainment_commission"
    )


def test_status():
    assert item["status"] == PASSED


def test_location():
    assert item["location"] == {"name": "", "address": ""}


def test_source():
    assert item["source"] == test_response.url


def test_links():
    assert item["links"] == [
        {
            "href": "https://detroitmi.gov/sites/detroitmi.localhost/files/events/2021-03/Agenda%20March%2015%202021.pdf",  # noqa
            "title": "Agenda",
        },
        {
            "href": "https://detroitmi.gov/sites/detroitmi.localhost/files/events/2021-03/DEC%20Virtual%20Notice%20for%20March%2015%202021.pdf",  # noqa
            "title": "DEC Virtual Notice for March 15 2021.pdf",
        },
    ]


def test_all_day():
    assert item["all_day"] is False


def test_classification():
    assert item["classification"] == COMMISSION
