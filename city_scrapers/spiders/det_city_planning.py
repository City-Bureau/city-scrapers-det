import re

from city_scrapers_core.constants import COMMISSION
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetCityMixin


class DetCityPlanningSpider(DetCityMixin, CityScrapersSpider):
    name = "det_city_planning"
    agency = "Detroit City Planning Commission"
    agency_cal_id = "1591"
    # "City Planning Commission Minutes - <date>" documents. The commission's other
    # documents list holds correspondence dated when it was filed, not meetings.
    agency_doc_id = "3761"
    # Scrape from 2 years in the past through all future meetings
    start_days_prev = 730

    regular_title = "City Planning Commission"
    # " - Nov 20, 2025", " - Jan. 15, 2026" and " - CANCELLED" title endings
    title_suffix_re = re.compile(
        r"\s+-\s+(?:[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|CANCEL+ED|POSTPONED)\s*$",
        flags=re.IGNORECASE,
    )
    # The unit belongs with the room, not in the street address:
    # "2 Woodward Avenue, Suite 1300 Detroit, MI 48226"
    address_unit_re = re.compile(r",?\s*\b((?:Suite|Room|Floor)\s+\w+)\b,?\s*")
    # Venues an event names only in its description: the June 4, 2026 meeting
    # page's address, and the April 3, 2025 page's campus (ZIP from WCCCD)
    description_venues = [
        (
            re.compile(r"1776 W\.? Warren", flags=re.IGNORECASE),
            {
                "name": "Simmons Conference Room, Dauch Scout Center",
                "address": "1776 W. Warren Ave., Detroit, MI 48208",
            },
        ),
        (
            re.compile(r"8200 W\.? Outer", flags=re.IGNORECASE),
            {
                "name": "Denise Wellons-Glover Welcome Center, 2nd Floor, "
                "Wayne County Community College District Northwest Campus",
                "address": "8200 W. Outer Drive, Detroit, MI 48219",
            },
        ),
    ]

    def _parse_title(self, response):
        """
        "City Planning Commission Meeting - Nov 5, 2026" is the regular meeting.
        Workshops and other events keep their own title, without the date.
        """
        title = super()._parse_title(response)
        while self.title_suffix_re.search(title):
            title = self.title_suffix_re.sub("", title)
        if title.lower() == "city planning commission meeting":
            return self.regular_title
        return title

    def _parse_description(self, response):
        """The event's whole description: its purpose and how to join virtually"""
        text = " ".join(response.css("article.description *::text").extract())
        return " ".join(text.split())

    def _parse_classification(self, response):
        return COMMISSION

    def _parse_location(self, response):
        location = super()._parse_location(response)
        unit_match = self.address_unit_re.search(location["address"])
        if not unit_match:
            return location
        return {
            "name": "{}, {}".format(location["name"], unit_match.group(1)),
            "address": self.address_unit_re.sub(", ", location["address"], count=1),
        }

    def _parse_location_from_description(self, response):
        description = self._parse_description(response)
        for venue_re, venue in self.description_venues:
            if venue_re.search(description):
                return dict(venue)
        return None

    def _date_documents(self, response, start):
        """
        The minutes documents are all for regular meetings, so a workshop held the
        same day doesn't take them too.
        """
        if self._parse_title(response) != self.regular_title:
            return []
        return super()._date_documents(response, start)
