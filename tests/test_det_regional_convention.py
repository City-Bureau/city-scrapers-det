from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import BOARD, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_regional_convention import DetRegionalConventionSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_regional_convention.html"),
    url="https://www.huntingtonplacedetroit.com/about/detroit-regional-convention-facility-authority/upcoming-drcfa-meetings",  # noqa
)
spider = DetRegionalConventionSpider()

freezer = freeze_time(datetime(2024, 5, 9, 13, 8))
freezer.start()

parsed_items = [item for item in spider.parse(test_response)]
parsed_item = parsed_items[0]
freezer.stop()


def test_title():
    assert parsed_item["title"] == "DRCFA Meeting"


def test_description():
    assert parsed_item["description"] == ""


def test_start():
    assert parsed_item["start"] == datetime(2023, 3, 9, 9, 0)


def test_end():
    assert parsed_item["end"] is None


def test_time_notes():
    assert parsed_item["time_notes"] == ""


def test_id():
    assert parsed_item["id"] == "det_regional_convention/202303090900/x/drcfa_meeting"


def test_status():
    assert parsed_item["status"] == PASSED


def test_location():
    assert parsed_item["location"] == {
        "name": "Huntingdon Place",
        "address": "Huntington Place Detroit Room 252A/B",
    }


def test_source():
    assert (
        parsed_item["source"]
        == "https://www.huntingtonplacedetroit.com/about/detroit-regional-convention-facility-authority/upcoming-drcfa-meetings"  # noqa
    )


def test_links():
    assert parsed_item["links"] == []


def test_classification():
    assert parsed_item["classification"] == BOARD


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
