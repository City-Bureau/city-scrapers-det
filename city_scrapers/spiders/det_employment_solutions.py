import re
from datetime import datetime

from city_scrapers_core.constants import ADVISORY_COMMITTEE, BOARD, COMMITTEE
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider


class DetEmploymentSolutionsSpider(CityScrapersSpider):
    name = "det_employment_solutions"
    agency = "Detroit Employment Solutions Corporation"
    timezone = "America/Chicago"
    start_urls = ["https://www.descmiworks.com/about-us/public-meetings/"]
    curr_type = None

    MEETING_TYPES = ["MWDB", "CEAC", "DESC"]
    MEETING_TYPE_TO_CSS_SELECTOR_MAP = {
        "MWDB": "div.mwdb-meeting_wrapper_inner-wrapper",
        "CEAC": "div.elementor-text-editor",
        "DESC": "div.elementor-text-editor > p:nth-child(even) > a",
    }

    def get_meeting_type(self, item):
        """Get the meeting type based on the item selector."""
        if not item:
            return None
        info = item.get()
        if "No Upcoming Meetings" in info:
            return None
        # There are 3 meeting types mentioned on the webpage
        if "mwdb" in info:
            return self.MEETING_TYPES[0]
        if "CEAC" in info:
            return self.MEETING_TYPES[1]
        if "DESC" in info:
            # DESC meetings currently have parsable links only
            return self.MEETING_TYPES[2]

    def parse(self, response):
        """
        `parse` should always `yield` Meeting items.

        NOTE: If the HTML structure changes this will need to be re-written.

        NOTE: The entire monthly schedules are ONLY available for download
        in a docx and pdf format.

        Parsable meeting types:
         - MWDB Meetings
         - CAEC Meetings

        Unparsable meetings types (e.g. PDF/DOCX):
         - DESC Meetings
        """
        elementor_row = response.css(
            "section.elementor-element:nth-child(4)"
            + "> div:nth-child(1) > div:nth-child(1)"
        )
        # The css selector for the left section of the page
        meeting_sections = elementor_row.css("section.desc-public-meeting")
        # Assumes location is the same across meeting types.
        location = self._parse_location(meeting_sections[0])
        # Appends the css selector for the right section on the page
        meeting_sections.append(
            elementor_row.css(
                "div.elementor-row > " "div.elementor-column:nth-child(2) > div > div"
            )
        )

        for items in meeting_sections[1:]:
            meeting_type = self.get_meeting_type(items)
            if not meeting_type:
                continue
            for meeting_item in items.css(
                self.MEETING_TYPE_TO_CSS_SELECTOR_MAP[meeting_type]
            ):
                meeting = Meeting(
                    title=self._parse_title(items, meeting_type),
                    description="",
                    classification=self._parse_classification(items, meeting_type),
                    start=self._parse_start(meeting_item, meeting_type),
                    end=self._parse_end(meeting_item, meeting_type),
                    all_day=False,
                    time_notes=self._parse_time_notes(items),
                    location=location,
                    links=self._parse_links(meeting_item, meeting_type),
                    source=response.url,
                )
                meeting["id"] = self._get_id(meeting)
                meeting["status"] = self._get_status(meeting)

                yield meeting

    def _parse_title(self, item, meeting_type):
        """Parse or generate meeting title"""
        if meeting_type == "MWDB":
            return "Mayor's Workforce Development Board (MWDB) Meeting"
        if meeting_type == "CEAC":
            return "Career and Education Advisory Council (CEAC) Meeting"
        return "DESC Meeting"

    def _parse_classification(self, item, meeting_type):
        """Parse or generate classification from allowed options."""
        if meeting_type == "MWDB":
            return BOARD
        if meeting_type == "CEAC":
            return ADVISORY_COMMITTEE
        if meeting_type == "DESC":
            meeting_name = item.css("strong ::text").get()
            if meeting_name == "Corporation Board Meeting":
                return BOARD
            if meeting_name == "Executive Committee Meeting":
                return COMMITTEE

        return BOARD

    def find_date(self, item, meeting_type, is_start=False):
        """Parses item and creates a datetime formatted string."""
        if meeting_type is None:
            return None
        if meeting_type == "MWDB":
            # remove the 'nd' 'rd' 'th' from number day
            caldate = item.css("strong ::text").get().strip()[:-2]
            timeframe = item.css("p ::text").get().strip().split(" - ")
            # webpage dates don't include year, assume year of now
            curr_year = str(datetime.now().year)
            curr_month = str(datetime.now().month)
            # If the current month is not January but January is in the meeting
            # date than the meeting date falls in the next year.
            if (curr_month != "1") and ("January" in caldate or "February" in caldate):
                curr_year = str(int(curr_year) + 1)
            meeting_time = timeframe[0] if is_start else timeframe[1]
            date_str = "{} {} {}".format(caldate, curr_year, meeting_time)
            date_str_fmt = "%A, %B %d %Y %I:%M%p"
        if meeting_type == "CEAC":
            # date is in the format: 11/23/2020 – 11 am – 12:30 pm
            parsed_item = re.compile("(: )|( – )").split(
                item.css("ul > li ::text").get().strip()
            )
            caldate = parsed_item[0].split("/")
            timeframe = re.compile("(-)|(–)").split(parsed_item[3])
            if len(timeframe) < 2 and (not is_start):
                return None
            meeting_time = timeframe[0] if is_start else timeframe[3]
            if ":" not in meeting_time:
                meeting_time = ":00 ".join(meeting_time.split(" "))
            if len(caldate[2]) == 2:
                caldate[2] = "20" + caldate[2]
            date_str = "{} {}".format("/".join(caldate), meeting_time.replace(" ", ""))
            date_str_fmt = "%m/%d/%Y %I:%M%p"
        if meeting_type == "DESC":
            if not is_start:
                return None
            date_str = "9:45 am"
            date_str_fmt = "%I:%M %p"

        return datetime.strptime(date_str, date_str_fmt)

    def _parse_start(self, item, meeting_type):
        """Parse start datetime as a naive datetime object."""
        return self.find_date(item, meeting_type, True)

    def _parse_end(self, item, meeting_type):
        """Parse end datetime as a naive datetime object. Added by pipeline if None"""
        return self.find_date(item, meeting_type)

    def _parse_time_notes(self, item):
        """Parse any additional notes on the timing of the meeting"""
        return "Please check pdf schedule for exact time of DESC meetings."

    def _parse_location(self, item):
        """Parse or generate location."""
        location_info = item.css("p ::text").get()
        location_info = location_info.replace(" (Location subject to change)", "")
        first_comma_index = location_info.find(", ")
        return {"address": location_info[first_comma_index + 3 :], "name": ""}

    def _parse_links(self, item, meeting_type):
        """Parse or generate links."""
        href = ""
        title = ""
        if meeting_type == "CEAC":
            href = item.css("a::attr(href)").get() or ""
            title = item.css("a ::text").get() or ""
        if meeting_type == "DESC":
            href = item.css("::attr(href)").get()
            title = item.css("strong ::text").get()
        return [{"href": href, "title": title}]
