import re
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
        # Scraping upcoming meetings if they become available
        future_meeting = True
        for item in response.xpath(
            "//div[@class='textarea']//div[@class='content clearfix']"
        )[1:]:
            title = self._parse_title(item, future_meeting)
            for meeting in item.xpath(
                "../following-sibling::div[1][@class='events']//\
                div[@class='event_list']//div[@class='info clearfix']//h3"
            ):
                start = self._parse_start(meeting, future_meeting)
                print(start)
                print(title)
                if None in (start, title):
                    continue
                meeting = Meeting(
                    title=title,
                    description=self._parse_description(item),
                    classification=self._parse_classification(item),
                    start=start,
                    end=self._parse_end(item),
                    all_day=self._parse_all_day(item),
                    time_notes=self._parse_time_notes(item),
                    location=self._parse_location(item),
                    links=self._parse_links(item, future_meeting),
                    source=self._parse_source(response),
                )

                meeting["status"] = self._get_status(meeting)
                meeting["id"] = self._get_id(meeting)

                yield meeting

        future_meeting = False
        for item in response.xpath("//div[@class='link']/ul/li/a"):
            start = self._parse_start(item, future_meeting)
            if start is None:
                continue
            meeting = Meeting(
                title=self._parse_title(item, future_meeting),
                description=self._parse_description(item),
                classification=self._parse_classification(item),
                start=start,
                end=self._parse_end(item),
                all_day=self._parse_all_day(item),
                time_notes=self._parse_time_notes(item),
                location=self._parse_location(item),
                links=self._parse_links(item, future_meeting),
                source=self._parse_source(response),
            )

            meeting["status"] = self._get_status(meeting)
            meeting["id"] = self._get_id(meeting)

            yield meeting

    def _parse_title(self, item, future_meeting):
        """Parse or generate meeting title."""
        if future_meeting:
            for announcement in item.xpath(".//h1/text()"):
                meeting_announce = announcement.get().split()
                remove_words = ["dates", "schedule"]
                title_list = [
                    word
                    for word in meeting_announce
                    if word.lower() not in remove_words
                ]
                return " ".join(title_list)
        else:
            return "Board of Directors"

    def _parse_description(self, item):
        """Parse or generate meeting description."""
        return ""

    def _parse_classification(self, item):
        """Parse or generate classification from allowed options."""
        return BOARD

    def _parse_start(self, item, future_meeting):
        """Parse start datetime as a naive datetime object."""
        if future_meeting:
            time_unparsed = item.xpath("text()").getall()[2]
            time_struct = r"(\d{1,2}):(\d{2})(\s*[ap]m?)"
            time_str = re.search(time_struct, time_unparsed)
            date_str = " ".join(item.xpath(".//span/text()").getall())
            if time_str and date_str:
                datetime_str = date_str + " " + time_str.group(0)
                datetime_object = datetime.strptime(datetime_str, "%b %d , %Y %I:%M%p")
                return datetime_object
            else:
                return None
        else:
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
                return None
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
            "name": "TCF Center",
        }

    def _parse_links(self, item, future_meeting):
        """Parse or generate links."""
        if future_meeting:
            return None
        else:
            report_link = item.xpath("./@href")[0].get()
            report_desc = item.xpath("./@title")[0].get()
            return [{"href": report_link, "title": report_desc}]

    def _parse_source(self, response):
        """Parse or generate source."""
        return response.url
