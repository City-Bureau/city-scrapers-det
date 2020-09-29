from datetime import datetime
from os.path import dirname, join

import pytest  # noqa
from city_scrapers_core.constants import COMMITTEE, TENTATIVE
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_city_council import DetCityCouncilSpider

freezer = freeze_time("2020-09-29")
freezer.start()

test_response = file_response(
    join(dirname(__file__), "files", "det_city_council.html"),
    url="https://pub-detroitmi.escribemeetings.com/Meetings.aspx",
)
spider = DetCityCouncilSpider()
parsed_items = [i for i in spider._parse_upcoming_meetings(test_response)] + [
    i for i in spider._parse_past_meetings(test_response)
]

freezer.stop()


def test_title():
    assert parsed_items[0]["title"] == "City Council Formal Session"


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2020, 9, 29, 10, 0)


def test_end():
    assert parsed_items[0]["end"] is None


def test_time_notes():
    assert parsed_items[0]["time_notes"] == ""


def test_id():
    assert (
        parsed_items[0]["id"]
        == "det_city_council/202009291000/x/city_council_formal_session"
    )


def test_status():
    assert parsed_items[0]["status"] == TENTATIVE


def test_location():
    assert parsed_items[0]["location"] == {
        "name": "Committee of the Whole Room",
        "address": "1340 Coleman A. Young Municipal Center Detroit, MI 48226",
    }


def test_source():
    assert (
        parsed_items[0]["source"]
        == "https://pub-detroitmi.escribemeetings.com/Meeting.aspx?Id=00c8942e-5eff-4224-8f30-ac0d1aa465eb&lang=English"  # noqa
    )


def test_links():
    assert parsed_items[0]["links"] == [
        {
            "href": "https://pub-detroitmi.escribemeetings.com/Meeting.aspx?Id=00c8942e-5eff-4224-8f30-ac0d1aa465eb&Agenda=Agenda&lang=English",  # noqa
            "title": "Agenda (HTML)",
        }
    ]


def test_all_day():
    assert parsed_items[0]["all_day"] is False


def test_classification():
    assert parsed_items[1]["classification"] == COMMITTEE
