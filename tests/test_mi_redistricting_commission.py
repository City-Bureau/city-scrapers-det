from datetime import datetime
from operator import itemgetter
from os.path import dirname, join

import pytest  # noqa
from city_scrapers_core.constants import COMMISSION, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.mi_redistricting_commission import (
    MiRedistrictingCommissionSpider,
)

test_doc_response = file_response(
    join(dirname(__file__), "files", "mi_redistricting_commission_docs.html"),
    url="https://www.michigan.gov/sos/0,4670,7-127-1633_91141-540204--,00.html",
)

test_response = file_response(
    join(dirname(__file__), "files", "mi_redistricting_commission.html"),
    url="https://www.michigan.gov/sos/0,4670,7-127-1633_91141-540541--,00.html",
)


freezer = freeze_time("2020-11-17")
freezer.start()

spider = MiRedistrictingCommissionSpider()

spider.document_date_map = spider._parse_documents(test_doc_response)

parsed_items = sorted(
    [item for item in spider._parse_meetings(test_response)], key=itemgetter("start")
)

freezer.stop()


def test_title():
    assert parsed_items[0]["title"] == "Commission"


def test_description():
    assert (
        parsed_items[0]["description"]
        == "Advisory Committee for Review of Executive Director Candidates"
    )


def test_start():
    assert parsed_items[0]["start"] == datetime(2020, 11, 10, 9, 0)


def test_end():
    assert parsed_items[0]["end"] == datetime(2020, 11, 10, 11, 0)


def test_time_notes():
    assert parsed_items[0]["time_notes"] == ""


def test_id():
    assert (
        parsed_items[0]["id"] == "mi_redistricting_commission/202011100900/x/commission"
    )


def test_status():
    assert parsed_items[0]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == MiRedistrictingCommissionSpider.location


def test_source():
    assert parsed_items[0]["source"] == test_response.url


def test_links():
    assert parsed_items[0]["links"] == [
        {
            "href": "https://www.michigan.gov/documents/sos/ICRC_Mtg__Notice_Nov_10_1st_707226_7.pdf",  # noqa
            "title": "Meeting Notice - Nov. 10, 2020 - 1st Meeting",
        }
    ]


def test_classification():
    assert parsed_items[0]["classification"] == COMMISSION


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
