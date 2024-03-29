import re
from collections import defaultdict
from datetime import datetime

import scrapy
from city_scrapers_core.constants import BOARD, COMMITTEE
from city_scrapers_core.items import Meeting
from dateutil.parser import parse as dateparse


class DetRetirementMixin:
    timezone = "America/Detroit"
    location = {
        "address": "500 Woodward Ave. Suite 300 Detroit, MI 48226",
        "name": "Retirement Systems",
    }
    custom_settings = {"ROBOTSTXT_OBEY": False}

    def __init__(self, *args, **kwargs):
        self.document_date_map = defaultdict(list)
        super().__init__(*args, **kwargs)

    def parse(self, response):
        """
        `parse` should always `yield` Meeting items.

        Change the `_parse_title`, `_parse_start`, etc methods to fit your scraping
        needs.
        """
        if "past" in response.url:
            self._parse_past_documents(response)
            meetings_url = re.sub(
                r"(?<=/)[^\./]*(?=\.php)", "upcoming_meetings", response.url
            )
            yield scrapy.Request(
                meetings_url, callback=self._parse_meetings, dont_filter=True
            )
        else:
            yield from self._parse_meetings(response)

    def _parse_meetings(self, response):
        description = " ".join(response.css("#post p")[0].css("*::text").extract())
        if "500 woodward ave" not in description.lower():
            raise ValueError("Meeting location has changed")

        meetings = []
        mtg_cls = self._parse_classification(response)
        meeting_kwargs = {
            "title": self._parse_title(response),
            "description": "",
            "classification": mtg_cls,
            "end": None,
            "all_day": False,
            "time_notes": "",
            "source": response.url,
        }
        default_start_time = None
        for item in response.css("#post table tr:not(:first-child)"):
            start = self._parse_start(item)
            # Set default meeting start time from first meeting
            if default_start_time is None:
                default_start_time = start.time()
            links = self.document_date_map.pop(start.date(), [])
            item_kwargs = {
                **meeting_kwargs,
                "title": self._parse_title(response, item=item),
                "description": " ".join(item.css("*::text").extract()),
            }
            meetings.append(
                Meeting(
                    **item_kwargs,
                    start=start,
                    location=self._parse_location(item),
                    links=links,
                )
            )

        for doc_date, doc_links in self.document_date_map.items():
            meetings.append(
                Meeting(
                    **meeting_kwargs,
                    start=datetime.combine(doc_date, default_start_time),
                    location=self.location,
                    links=doc_links,
                )
            )

        last_year = datetime.today().replace(year=datetime.today().year - 1)
        for meeting in meetings:
            if meeting["start"] < last_year and not self.settings.getbool(
                "CITY_SCRAPERS_ARCHIVE"
            ):
                continue
            # Unset description since it's used as a placeholder
            meeting["status"] = self._get_status(meeting, text=meeting["description"])
            meeting["description"] = ""
            meeting["id"] = self._get_id(meeting)
            yield meeting

    def _parse_title(self, response, item=None):
        if "board_of_trustees" in response.url:
            meeting_str = "Board of Trustees"
        else:
            meeting_str = "Investment Committee"
        if (
            item is not None
            and "special"
            in " ".join(item.css("td:first-child *::text").extract()).lower()
        ):
            meeting_str += ": Special Meeting"
        return meeting_str

    def _parse_classification(self, response):
        if "board_of_trustees" in response.url:
            return BOARD
        return COMMITTEE

    def _parse_start(self, item):
        date_str = re.sub(
            r"\s+",
            " ",
            re.sub(
                r"\(.+\)",
                "",
                " ".join(item.css("td:first-child *::text").extract()).strip(),
            ),
        )
        date_match = re.search(r"[A-Z][a-z]{2,8} \d{1,2},? \d{4}", date_str)
        if date_match:
            date_str = date_match.group()
        date_str = re.sub(r"cancel[a-z]+", "", date_str, flags=re.I).strip()
        time_str = (
            " ".join(item.css("td:nth-child(2) *::text").extract())
            .strip()
            .replace("Noon", "PM")
            .replace(".", "")
            .replace(" M", "M")
        )
        if "cancel" in time_str.lower():
            time_str = "12:00 am"
        dt_str = re.sub(r"\s+", " ", "{} {}".format(date_str, time_str)).strip()
        return dateparse(dt_str)

    def _parse_location(self, item):
        location = self.location.copy()
        room_str = " ".join(item.css("td:last-child *::text").extract()).strip().title()
        if room_str:
            location["name"] = "{} {}".format(location["name"], room_str)
        return location

    def _parse_past_documents(self, response):
        for row in response.css("#post tr"):
            date_str = row.css("td::text").extract_first().strip()
            doc_date = self._parse_doc_date(date_str.split(" ")[0])
            self.document_date_map[doc_date] = self._parse_doc_links(row, response)

    def _parse_doc_date(self, date_str):
        return datetime.strptime(date_str.strip(), "%m/%d/%y").date()

    def _parse_doc_links(self, row, response):
        links = []
        for link in row.css('a[href]:not([aria-hidden="true"])'):
            links.append(
                {
                    "title": link.xpath("./text()").extract_first(),
                    "href": response.urljoin(link.xpath("@href").extract_first()),
                }
            )
        return links
