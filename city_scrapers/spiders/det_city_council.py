import re
from datetime import datetime

from city_scrapers_core.constants import CITY_COUNCIL, COMMITTEE
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider
from scrapy import Selector


class DetCityCouncilSpider(CityScrapersSpider):
    name = "det_city_council"
    agency = "Detroit City Council"
    timezone = "America/Detroit"
    start_urls = ["https://pub-detroitmi.escribemeetings.com/Meetings.aspx"]

    def parse(self, response):
        if "Expanded" in response.request.url:
            yield from self._parse_past_meetings(response)
        else:
            yield from self._parse_upcoming_meetings(response)
            for past_link in response.css(".MeetingListPast a[role='button']"):
                yield response.follow(past_link.attrib["href"])

    def _parse_upcoming_meetings(self, response):
        for item in response.css(".MeetingListFuture .meeting"):
            title = self._parse_title(item)
            meeting = Meeting(
                title=title,
                description="",
                classification=self._parse_classification(title),
                start=self._parse_start(item),
                end=None,
                time_notes="",
                all_day=False,
                location=self._parse_location(item),
                links=self._parse_links(response, item),
                source=self._parse_source(response, item),
            )
            meeting["status"] = self._parse_status(meeting, item)
            meeting["id"] = self.get_id(meeting)
            yield meeting

    def _parse_past_meetings(self, response):
        for item_group in response.css(".MeetingListPast .MeetingTypeList"):
            if len(item_group.css(".panel-collapse[aria-expanded='true']")) > 0:
                continue
            title = (
                item_group.css(".panel-title span:not(.MeetingTypeMeetingCount)::text")
                .get()
                .strip()
            )
            for item in item_group.css(".meeting"):
                meeting = Meeting(
                    title=title,
                    description="",
                    classification=self._parse_classification(title),
                    start=self._parse_start(item),
                    end=None,
                    time_notes="",
                    all_day=False,
                    location=self._parse_location(item),
                    links=self._parse_links(response, item),
                    source=self._parse_source(response, item),
                )
                meeting["status"] = self._parse_status(meeting, item)
                meeting["id"] = self.get_id(meeting)
                yield meeting

    def _parse_title(self, item):
        return " ".join(item.css(".MeetingTitle *::text").getall()).strip()

    def _parse_start(self, item):
        start_str = re.sub(
            r"\s+", " ", " ".join(item.css(".visible-md *::text").getall()).strip()
        )
        return datetime.strptime(start_str, "%B %d %Y %I:%M%p")

    def _parse_classification(self, title):
        if "committee" in title.lower():
            return COMMITTEE
        return CITY_COUNCIL

    def _parse_location(self, item):
        tooltip_el = item.css(".Location-Tooltip")[0]
        tooltip_str = tooltip_el.css("*::text").get().strip()
        title_sel = Selector(text=tooltip_el.attrib["data-original-title"])
        # Remove extra spaces and phone number
        title_str = re.sub(
            r"\(\d+\)\s?\d+\-\d+", " ", " ".join(title_sel.css("*::text").getall())
        )
        clean_title_str = re.sub(r"\s+", " ", title_str)
        return {
            "name": tooltip_str,
            "address": clean_title_str.replace(tooltip_str, "").strip(),
        }

    def _parse_links(self, response, item):
        links = []
        for link in item.css(".links a"):
            if not link.attrib["href"] or "Sharing" in link.attrib["href"]:
                continue
            links.append(
                {
                    "title": " ".join(link.xpath("./text()").getall()).strip(),
                    "href": response.urljoin(link.attrib["href"]),
                }
            )
        return links

    def _parse_status(self, meeting, item):
        return self.get_status(
            meeting, text=" ".join(item.css(".col-xs-12:not(.hidden) *::text").getall())
        )

    def _parse_source(self, response, item):
        title_links = item.css(".MeetingTitle a")
        if len(title_links) > 0:
            return response.urljoin(title_links[0].attrib["href"])
        return response.url
