import re
from datetime import datetime, time

from city_scrapers_core.constants import BOARD, COMMITTEE
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider
from dateutil.parser import parse


class DetRegionalConventionSpider(CityScrapersSpider):
    name = "det_regional_convention"
    agency = "Detroit Regional Convention Facility Authority"
    timezone = "America/Detroit"
    start_urls = [
        "https://www.huntingtonplacedetroit.com/about/detroit-regional-convention-facility-authority/upcoming-drcfa-meetings"  # noqa
    ]

    def parse(self, response):
        """
        This agency's HTML doesn't have great hierarchy. We parse by
        looking for header nodes and then checking if the next sibling
        is a  "faq content_item" node, which indicates a list of meetings.
        """
        for item in response.css("div.textarea.content_item"):
            meeting_list = item.xpath(
                "./following-sibling::div[1][contains(@class, 'faq') and contains(@class, 'content_item')]"  # noqa
            )
            if meeting_list:
                # get title from parent node's header
                title = self._parse_title(item)
                for meeting in meeting_list.css("div.faq_list_item"):
                    info_str = meeting.css("p::text").extract_first()
                    if not info_str:
                        # some nodes are empty, skip them
                        continue
                    start = self.parse_start(info_str)
                    if not start:
                        self.log(
                            f"Failed to parse start time from text: {info_str}"
                        )  # noqa
                        continue
                    meeting = Meeting(
                        title=title,
                        description="",
                        classification=self._parse_classification(title),
                        start=start,
                        end=None,
                        all_day=False,
                        time_notes="",
                        location=self._parse_location(info_str),
                        links=[],
                        source=response.url,
                    )
                    meeting["status"] = self._get_status(meeting)
                    meeting["id"] = self._get_id(meeting)
                    yield meeting

    def _parse_title(self, item):
        header = item.css("div.content.clearfix > h2::text").extract_first()
        if header is None:
            raise ValueError(
                "Header not found – page structure may have changed"
            )  # noqa
        # Remove "schedule" from title to get a clean meeting title
        title = re.sub(r"(?i)schedule", "", header).strip()
        return title

    def parse_start(self, input_str):
        """
        Searches text for a date in format "February 1, 2024"
        or similar and a time in format "12:00 PM" or similar
        """
        # parse date
        date_match = re.search(r"([A-Z][a-z]+ \d{1,2},? \d{4})", input_str)
        if not date_match:
            return None
        try:
            date_obj = parse(date_match.group(), fuzzy=True)
            date_obj = date_obj.date()
        except ValueError:
            return None
        except AttributeError:
            return None

        # parse time in formats
        time_match = re.search(
            r"\b([0-9]|1[0-2]):?([0-5][0-9])?\s?(am|pm|AM|PM)\b", input_str
        )
        try:
            time_obj = parse(time_match.group())
            time_obj = time_obj.time()
        # default to 12:00 AM if no time found
        except ValueError:
            time_obj = time(0, 0)
        except AttributeError:
            time_obj = time(0, 0)

        return datetime.combine(date_obj, time_obj)

    def _parse_location(self, info_str):
        """
        Assume location is whatever text is after "in" and
        collapse whitespace to single spaces so it's cleaner
        """
        location_match = re.search(r"in (.+)", info_str)
        if not location_match:
            return {"name": "TBD", "address": ""}
        # clean up whitespace
        location = re.sub(r"\s+", " ", location_match.group(1)).strip()
        if "huntington" in location.lower():
            return {"name": "Huntingdon Place", "address": location}
        return {"name": "", "address": location}

    def _parse_classification(self, title):
        if "committee" in title.lower():
            return COMMITTEE
        return BOARD
