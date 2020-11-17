import re
from collections import defaultdict
from datetime import datetime, time

from city_scrapers_core.constants import COMMISSION
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider
from dateutil.parser import parse as dateparse


class MiRedistrictingCommissionSpider(CityScrapersSpider):
    name = "mi_redistricting_commission"
    agency = "Michigan Independent Citizens Redistricting Commission"
    timezone = "America/Detroit"
    start_urls = [
        "https://www.michigan.gov/sos/0,4670,7-127-1633_91141-540204--,00.html"
    ]
    # TODO: Will need to look into this later
    location = {"name": "Remote", "address": ""}

    def parse(self, response):
        """
        `parse` should always `yield` Meeting items.

        Change the `_parse_title`, `_parse_start`, etc methods to fit your scraping
        needs.
        """
        self.document_date_map = self._parse_documents(response)
        yield response.follow(
            "/sos/0,4670,7-127-1633_91141-540541--,00.html",
            callback=self._parse_meetings,
            dont_filter=True,
        )

    def _parse_documents(self, response):
        document_date_map = defaultdict(list)
        last_date = None
        for line in response.css(".fullContent > p, .fullContent > div"):
            doc_date = self._parse_document_date(line.css("*::text").get())

            if len(line.css("a")) > 0:
                line_link = line.css("a")
                # Default to last-used section date if link date not present
                link_date = doc_date or last_date
                if link_date:
                    document_date_map[link_date.strftime("%Y-%m-%d")].append(
                        {
                            "title": re.sub(
                                r"\s+", " ", line_link.css("*::text").get()
                            ).strip(),
                            "href": response.urljoin(line_link.attrib["href"]),
                        }
                    )
            elif doc_date:
                last_date = doc_date
        return document_date_map

    def _parse_document_date(self, document_text):
        clean_text = re.sub(r"\s+", " ", document_text)
        date_match = re.search(r"[A-Z][a-z]{2,9}\.? \d\d?,? \d{2,4}", clean_text)
        alt_date_match = re.search(r"\d\d?[\.-]\d\d?[\.-]\d{2,4}", clean_text)
        short_date_match = re.search(r"\d\d?/\d\d?/\d{2,4}", clean_text)

        if date_match:
            return dateparse(date_match.group()).date()
        elif alt_date_match:
            return dateparse(alt_date_match.group()).date()
        elif short_date_match:
            return dateparse(short_date_match.group()).date()

    def _parse_meetings(self, response):
        for meeting_group in response.css(".fullContent > p"):
            date_str, *meeting_details = [
                s.strip() for s in meeting_group.css("*::text").extract()
            ]
            for detail in meeting_details:
                if not detail.strip():
                    continue
                start, end = self._parse_start_end(date_str, detail)

                meeting = Meeting(
                    title=self._parse_title(date_str, detail),
                    description=self._parse_description(detail),
                    classification=COMMISSION,
                    start=start,
                    end=end,
                    all_day=False,
                    time_notes="",
                    location=self.location,
                    links=self.document_date_map[start.strftime("%Y-%m-%d")],
                    source=response.url,
                )

                meeting["status"] = self._get_status(
                    meeting, text=" ".join([date_str, detail])
                )
                meeting["id"] = self._get_id(meeting)

                yield meeting

    def _parse_title(self, date_str, detail):
        """Parse or generate meeting title."""
        if "Advisory Commitee" in detail:
            return "Advisory Committee"
        if "Full Commission" in detail:
            return "Full Commission"
        return "Commission"

    def _parse_description(self, detail):
        """Parse or generate meeting description."""
        return re.sub(r"\s+", " ", " ".join(detail.split(" - ")[1:]))

    def _parse_start_end(self, date_str, detail_str):
        """Parse start datetime as a naive datetime object."""
        date_obj = dateparse(re.sub(r"\(.*\)", "", date_str)).date()
        time_strs = re.findall(r"(\d\d?(?::\d\d)?\s?[apm\.]{2,4})", detail_str)
        if len(time_strs) == 0:
            return datetime.combine(date_obj, time(0)), None
        elif len(time_strs) == 1:
            return datetime.combine(date_obj, dateparse(time_strs[0]).time()), None
        else:
            return (
                datetime.combine(date_obj, dateparse(time_strs[0]).time()),
                datetime.combine(date_obj, dateparse(time_strs[1]).time()),
            )
