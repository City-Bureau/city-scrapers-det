import re

from city_scrapers_core.constants import COMMISSION
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider
from dateutil.parser import parse


class WayneElectionCommissionSpider(CityScrapersSpider):
    name = "wayne_election_commission"
    agency = "Wayne County Election Commission"
    timezone = "America/Detroit"
    start_urls = ["https://www.waynecounty.com/elected/clerk/election-commission.aspx"]
    location = {
        "name": "Coleman A. Young Municipal Center, Conference Room 700A",
        "address": "2 Woodward Ave, Detroit, MI 48226",
    }

    def parse(self, response):
        year_str = ""
        for table in response.css("article table"):
            header_str = " ".join(table.css("th *::text").extract())
            year_match = re.search(r"\d{4}", header_str)
            # Override the year if provided, otherwise use the last year in the loop
            if year_match:
                year_str = year_match.group()
            for item in table.css("tr"):
                start = self._parse_start(item, year_str)
                if start is None:
                    continue
                meeting = Meeting(
                    title="Election Commission",
                    description="",
                    classification=COMMISSION,
                    start=start,
                    end=None,
                    time_notes="",
                    all_day=False,
                    location=self.location,
                    links=self._parse_links(item, response),
                    source=response.url,
                )
                meeting["status"] = self._get_status(
                    meeting, text=" ".join(item.css("td *::text").extract())
                )
                meeting["id"] = self._get_id(meeting)
                yield meeting

    @staticmethod
    def _parse_start(item, year_str):
        """Parse start datetime."""
        date_cell_str = item.xpath("td[1]//text()").extract_first() or ""
        date_match = re.search(r"[A-Z][a-z]{2,9} \d\d?", date_cell_str)
        if not date_match:
            return
        return parse(f"{date_match.group()} {year_str}")

    def _parse_links(self, item, response):
        """
        Parse or generate documents.
        """
        tds = item.xpath("td[position() >1]")
        return [self._build_document(td, response) for td in tds if self._has_url(td)]

    @staticmethod
    def _has_url(td):
        return td.xpath(".//@href").extract_first()

    @staticmethod
    def _build_document(td, response):
        document_url = response.urljoin(td.xpath(".//@href").extract_first())
        text = td.xpath(".//text()").extract_first()
        return {"href": document_url, "title": text}
