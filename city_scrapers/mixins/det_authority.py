import json
import re
from collections import defaultdict
from datetime import datetime, time

from city_scrapers_core.constants import BOARD
from city_scrapers_core.items import Meeting


class DetAuthorityMixin:
    """Mixin for shared behavior on Detroit public authority scrapers"""

    timezone = "America/Detroit"
    title = "Board of Directors"
    tab_title = ""
    start_urls = ["https://www.degc.org/public-authorities/"]
    classification = BOARD
    default_start_time = time(0)
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def parse(self, response):
        """Parse both the upcoming and previous meetings"""
        yield from self._next_meetings(response)
        yield response.follow(self.agency_url, callback=self._parse_prev_meetings)

    def _next_meetings(self, response):
        """Parse upcoming meetings"""
        page_text = " ".join(response.css(".et_pb_text_inner *::text").extract())
        self._validate_location(page_text)

        events = [
            i for i in response.css("script").extract() if '"@type":"Event"' in i
        ][0]
        events = re.sub("<[^<]+?>", "", events)
        events = json.loads(events)

        for event in events:
            if self.tab_title.lower() in event["url"]:
                meeting = self._set_meeting_defaults(response)
                meeting["start"] = datetime.fromisoformat(event["startDate"]).replace(
                    tzinfo=None
                )
                meeting["links"] = self._parse_event_links(event)
                meeting["status"] = self._get_status(meeting, text=event["name"])
                meeting["id"] = self._get_id(meeting)
                yield meeting

    def _parse_event_links(self, event):
        """Parse links in a given event dictionary"""
        links = [{"href": event["url"], "title": ""}]
        if event["description"]:
            print(event["description"])
            zoom_link = event["description"].split()[3]
            links.append({"href": zoom_link, "title": "Zoom Meeting"})
        if "location" in event.keys() and event["location"]["url"]:
            links.append({"href": event["location"]["url"], "title": ""})

        return links

    def _parse_prev_meetings(self, response):
        """Parse all previous meetings"""
        link_map = self._parse_prev_links(response)
        last_year = datetime.today().replace(year=datetime.today().year - 1)
        for dt, links in link_map.items():
            link_text = " ".join(link["title"] for link in links)
            meeting = self._set_meeting_defaults(response)
            meeting["start"] = dt
            meeting["links"] = links
            meeting["title"] = self._parse_title(meeting)
            meeting["classification"] = self._parse_classification(meeting)
            meeting["status"] = self._get_status(meeting, text=link_text)
            meeting["id"] = self._get_id(meeting)
            if meeting["start"] < last_year and not self.settings.getbool(
                "CITY_SCRAPERS_ARCHIVE"
            ):
                continue
            yield meeting

    @staticmethod
    def _parse_start_time(text):
        """Parse start time from text"""
        time_str = re.search(r"\d{1,2}:\d{1,2}\s*[apmAPM\.]{2,4}", text).group()
        return datetime.strptime(
            re.sub(r"[\.\s]", "", time_str, flags=re.I).upper(), "%I:%M%p"
        ).time()

    @staticmethod
    def _parse_start(date_text, time_obj):
        """Parse date string and combine with start time"""
        date_str = (
            re.search(r"\w{3,10}\s+\d{1,2},?\s+\d{4}", date_text)
            .group()
            .replace(",", "")
        )
        date_obj = datetime.strptime(date_str, "%B %d %Y").date()
        return datetime.combine(date_obj, time_obj)

    def _parse_title(self, meeting):
        """Return title, included for overriding in spiders"""
        return self.title

    def _parse_classification(self, meeting):
        """Return classification, included for overriding in spiders"""
        return self.classification

    def _validate_location(self, text):
        """Check that the location hasn't changed"""
        if "500 Griswold" not in text:
            raise ValueError("Meeting location has changed")

    def _parse_next_links(self, start, response):
        """Parse links for upcoming meetings"""
        links = []
        for link in response.css("a.accordion-label"):
            link_text, link_date = self._parse_link_text_date(link)
            # Ignore if link date is None or doesn't match start date
            if start.date() != link_date:
                continue
            link_title = re.sub(
                r"\s+",
                " ",
                re.sub(r"[a-z]{3,10}\s+\d{1,2},?\s+\d{4}", "", link_text, flags=re.I),
            ).strip()
            links.append(
                {"href": response.urljoin(link.attrib["href"]), "title": link_title}
            )
        return links

    def _parse_prev_links(self, response):
        """Parse links from previous meeting pages"""
        link_map = defaultdict(list)
        for link in response.css(".et_pb_tab_content a"):
            link_text, link_date = self._parse_link_text_date(link)
            if not link_date:
                continue
            link_dt = datetime.combine(link_date, self.default_start_time)
            link_title = re.sub(
                r"\s+",
                " ",
                re.sub(r"[a-z]{3,10}\s+\d{1,2},?\s+\d{4}", "", link_text, flags=re.I),
            ).strip()
            link_map[link_dt].append(
                {"href": response.urljoin(link.attrib["href"]), "title": link_title}
            )
        return link_map

    def _parse_link_text_date(self, link):
        """Parse the text of a link as well as the date (if available)"""
        link_text = " ".join(link.css("*::text").extract()).strip()
        link_date_match = re.search(
            r"[a-z]{3,10}\s+\d{1,2},?\s+\d{4}", link_text, flags=re.I
        )
        if not link_date_match:
            return link_text, None
        link_date_str = link_date_match.group().replace(",", "")
        try:
            link_date = datetime.strptime(link_date_str, "%B %d %Y").date()
        except ValueError:
            return None, None
        return link_text, link_date

    def _set_meeting_defaults(self, response):
        """Return default meeting object"""
        return Meeting(
            title=self.title,
            description="",
            classification=self.classification,
            end=None,
            time_notes="See source to confirm meeting time",
            all_day=False,
            location=self.location,
            links=[],
            source=response.url,
        )
