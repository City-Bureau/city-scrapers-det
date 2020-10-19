from datetime import datetime, time

from city_scrapers_core.constants import BOARD
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider


class DetRegionalConventionSpider(CityScrapersSpider):
    name = "det_regional_convention"
    agency = "Detroit Regional Convention Facility Authority"
    timezone = "America/Detroit"
    start_urls = ["http://www.drcfa.org/upcoming-meetings"]

    def parse(self, response):
        """
        `parse` should always `yield` Meeting items.
        """
        for item in response.xpath("//div[@class='link']/ul/li/a"):
            self._ignore = False
            meeting = Meeting(
                title=self._parse_title(item),
                description=self._parse_description(item),
                classification=self._parse_classification(item),
                start=self._parse_start(item),
                end=self._parse_end(item),
                all_day=self._parse_all_day(item),
                time_notes=self._parse_time_notes(item),
                location=self._parse_location(item),
                links=self._parse_links(item),
                source=self._parse_source(response),
            )

            meeting["status"] = self._get_status(meeting)
            meeting["id"] = self._get_id(meeting)

            if self._ignore is False:
                yield meeting

    def _parse_title(self, item):
        """Parse or generate meeting title."""
        return "Boards of directors of Detroit Regional \
        Convention Facility Authority"

    def _parse_description(self, item):
        """Parse or generate meeting description."""
        return ""

    def _parse_classification(self, item):
        """Parse or generate classification from allowed options."""
        return BOARD

    def _parse_start(self, item):
        """Parse start datetime as a naive datetime object."""
        default_starttime = time(8, 30)
        report_name = item.xpath("./@href")[0].get().split("/")[-1]
        name_splitted = report_name.replace("-", ".").replace("_", ".").split(".")
        date_digits = [int(digit) for digit in name_splitted if digit.isdigit()]
        if len(date_digits) == 3:
            date_obj = datetime(
                2000 + int(str(date_digits[2])[:2]), date_digits[0], date_digits[1]
            )
        else:
            # One meeting does not have similar naming structure
            self._ignore = True
            return datetime.now()
        return datetime.combine(date_obj, default_starttime)

    def _parse_end(self, item):
        """Parse end datetime as a naive datetime object. Added by pipeline if None"""
        return None

    def _parse_time_notes(self, item):
        """Parse any additional notes on the timing of the meeting"""
        return ""

    def _parse_all_day(self, item):
        """Parse or generate all-day status. Defaults to False."""
        return False

    def _parse_location(self, item):
        """Parse or generate location."""
        return {
            "address": "1 Washington Blvd, Detroit, MI 48226",
            "name": "Cobo Conference and Exhibition Center",
        }

    def _parse_links(self, item):
        """Parse or generate links."""
        report_link = item.xpath("./@href")[0].get()
        report_desc = item.xpath("./@title")[0].get()
        return [{"href": report_link, "title": report_desc}]

    def _parse_source(self, response):
        """Parse or generate source."""
        return response.url
