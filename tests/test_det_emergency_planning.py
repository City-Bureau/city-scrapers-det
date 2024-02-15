from datetime import datetime
from os.path import dirname, join

import pytest  # noqa
from city_scrapers_core.constants import ADVISORY_COMMITTEE, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.det_emergency_planning import DetEmergencyPlanningSpider

test_response = file_response(
    join(dirname(__file__), "files", "det_emergency_planning.html"),
    url="https://detroitmi.gov/events/detroit-local-emergency-planning-committee-meeting-4",  # noqa
)
spider = DetEmergencyPlanningSpider()

freezer = freeze_time("2023-08-19")
freezer.start()

item = spider.parse_event_page(test_response)

freezer.stop()


def test_title():
    assert item["title"] == "National Weather Service SkyWarn Spotter Program Training"


def test_description():
    assert item["description"] == ""


def test_start():
    assert item["start"] == datetime(2023, 4, 29, 13)


def test_end():
    assert item["end"] is None


def test_time_notes():
    assert item["time_notes"] == ""


def test_id():
    assert (
        item["id"]
        == "det_emergency_planning/202304291300/x/national_weather_service_skywarn_spotter_program_training"  # noqa
    )


def test_status():
    assert item["status"] == PASSED


def test_location():
    assert item["location"] == {"name": "", "address": ""}


def test_source():
    assert item["source"] == test_response.url


def test_links():
    assert item["links"] == []


def test_all_day():
    assert item["all_day"] is False


def test_classification():
    assert item["classification"] == ADVISORY_COMMITTEE
