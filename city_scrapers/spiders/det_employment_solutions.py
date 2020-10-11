import logging
from datetime import datetime

from city_scrapers_core.constants import ADVISORY_COMMITTEE, BOARD, NOT_CLASSIFIED
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider


class DetEmploymentSolutionsSpider(CityScrapersSpider):
    name = "det_employment_solutions"
    agency = "Detroit Employment Solutions Corporation"
    timezone = "America/Chicago"
    start_urls = ["https://www.descmiworks.com/about-us/public-meetings/"]
    curr_type = None

    MEETING_TYPES = ["MWDB", "CEAC"]
    MEETING_TYPE_TO_CSS_SELECTOR_MAP = {
        "MWDB": "div.mwdb-meeting_wrapper_inner-wrapper",
        # TODO: find selector for CEAC meetings
        "CEAC": "div",
    }

    def set_current_meeting_type(self, item):
        """Setter function for curr_meeting_type property."""
        if not item:
            self.curr_type = None
        info = item.get()
        # Right now there are only 2 parsable meeting types on the webpage
        if "mwdb" in info:
            self.curr_type = self.MEETING_TYPES[0]
        if "CEAC" in info:
            self.curr_type = self.MEETING_TYPES[1]

    def parse(self, response):
        """
        `parse` should always `yield` Meeting items.

        NOTE: The entire monthly schedules are ONLY available for download
        in a docx and pdf format.

        Parsable meeting types:
         - MWDB Meetings
         - CAEC Meetings

        Unparsable meetings types (e.g. PDF/DOCX):
         - DESC Meetings
        """
        meeting_info_sections = response.css("section.desc-public-meeting")
        # XXX: Assumes location is the same across meeting types.
        location = self._parse_location(meeting_info_sections[0])

        for items in meeting_info_sections[1:]:
            self.set_current_meeting_type(items)
            for meeting_item in items.css(
                self.MEETING_TYPE_TO_CSS_SELECTOR_MAP[self.curr_type]
            ):
                logging.debug(meeting_item.get())
                meeting = Meeting(
                    title=self._parse_title(items),
                    description=self._parse_description(items),
                    classification=self._parse_classification(items),
                    start=self._parse_start(meeting_item),
                    end=self._parse_end(meeting_item),
                    all_day=False,
                    time_notes=self._parse_time_notes(items),
                    location=location,
                    links=self._parse_links(items),
                    source=response.url,
                )

                meeting["status"] = self._get_status(meeting)
                meeting["id"] = self._get_id(meeting)

                yield meeting

    def _parse_title(self, item):
        """Parse or generate meeting title"""
        if self.curr_type == "MWDB":
            return "Mayor's Workforce Development Board (MWDB) Meeting"
        if self.curr_type == "CEAC":
            return "Career and Education Advisory Council (CEAC) Meeting"
        return "DESC Meeting"

    def _parse_description(self, item):
        """Parse or generate meeting description."""
        # TODO
        return ""

    def _parse_classification(self, item):
        """Parse or generate classification from allowed options."""
        if self.curr_type == "MWDB":
            return BOARD
        if self.curr_type == "CEAC":
            return ADVISORY_COMMITTEE
        return NOT_CLASSIFIED

    def _parse_start(self, item):
        """Parse start datetime as a naive datetime object."""
        # TODO: consolidate duplicate logic between start/end parse methods
        if self.curr_type is None:
            return None
        if self.curr_type == "MWDB":
            # remove the 'nd' 'rd' 'th' from number day
            caldate = item.css("strong ::text").get().strip()[:-2]
            timeframe = item.css("p ::text").get().strip().split(" - ")
            # webpage dates don't include year, assume year of now
            # XXX: this might lead to bugs when jumping form december to january
            curr_year = str(datetime.now().year)
            date_str = "{} {} {}".format(caldate, curr_year, timeframe[0])
            date_str_fmt = "%A, %B %d %Y %I:%M%p"
        if self.curr_type == "CEAC":
            date_str = ""
            date_str_fmt = ""

        return datetime.strptime(date_str, date_str_fmt)

    def _parse_end(self, item):
        """Parse end datetime as a naive datetime object. Added by pipeline if None"""
        if self.curr_type is None:
            return None
        if self.curr_type == "MWDB":
            # remove the 'nd' 'rd' 'th' from number day
            caldate = item.css("strong ::text").get().strip()[:-2]
            timeframe = item.css("p ::text").get().strip().split(" - ")
            # webpage dates don't include year, assume year of now
            # XXX: this might lead to bugs when jumping form december to january
            curr_year = str(datetime.now().year)
            date_str = "{} {} {}".format(caldate, curr_year, timeframe[1])
            date_str_fmt = "%A, %B %d %Y %I:%M%p"
        if self.curr_type == "CEAC":
            date_str = ""
            date_str_fmt = ""

        return datetime.strptime(date_str, date_str_fmt)

    def _parse_time_notes(self, item):
        """Parse any additional notes on the timing of the meeting"""
        # TODO
        return ""

    def _parse_location(self, item):
        """Parse or generate location."""
        location_info = item.css("p ::text").get()
        first_comma_index = location_info.find(", ")
        return {
            "address": location_info[first_comma_index + 3 :],
            "name": location_info[0:first_comma_index],
        }

    def _parse_links(self, item):
        """Parse or generate links."""
        # TODO
        return [{"href": "", "title": ""}]
