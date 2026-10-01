import calendar
import re
from collections import defaultdict
from functools import partial

import scrapy
from city_scrapers_core.constants import (
    ADVISORY_COMMITTEE,
    BOARD,
    CANCELLED,
    COMMITTEE,
    FORUM,
    NOT_CLASSIFIED,
)
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import LegistarSpider

from city_scrapers.mixins import DetCityMixin

BOARD_TITLE = "Board of Water Commissioners"
COMMITTEE_TITLE = BOARD_TITLE + " Committee Meeting"
MONTH_YEAR_RE = re.compile(
    r"\b({})\s+\d{{4}}\b".format("|".join(calendar.month_name[1:])),
    flags=re.IGNORECASE,
)


class DetWaterSewageDepartmentSpider(DetCityMixin, LegistarSpider):
    """
    Combines two sources:

    - detroitmi.gov calendar (primary): every event tagged with the DWSD
      department or the Board of Water Commissioners. It is the only source for
      the monthly combined committee meeting and for physical locations.
    - dwsd.legistar.com (secondary): each board and committee meeting with its
      agenda and minutes, and the only place cancellations are shown.

    A primary board meeting and the Legistar board meeting on the same date are
    the same meeting, so they are merged. Everything is held until both sources
    have been read, since a match can arrive from either side last.
    """

    name = "det_water_sewage_department"
    agency = "Detroit Water and Sewerage Department"
    timezone = "America/Detroit"
    start_urls = ["https://dwsd.legistar.com/Calendar.aspx"]
    # detroitmi.gov's robots.txt disallows every URL with a query string, which
    # covers all of its calendar filter pages
    custom_settings = {"ROBOTSTXT_OBEY": False}

    # detroitmi.gov calendar filters: the DWSD "Department" and the Board of
    # Water Commissioners "Government" entry. Setting both would AND them, so
    # each is queried on its own and the results are combined.
    dept_cal_id = "171"
    agency_cal_id = "All"
    board_cal_id = "1361"

    youtube_link = {
        "title": "YouTube channel",
        "href": "https://www.youtube.com/@DWSD/streams",
    }
    water_board_address = "735 Randolph St, Detroit, MI 48226"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending = 0
        self._seen_event_urls = set()
        self._primary_meetings = []
        self._legistar_meetings = []

    def start_requests(self):
        # Built as a list so all three are counted before Scrapy takes the first.
        # It pulls start requests lazily, so one could otherwise finish while the
        # count is still 1 and release the meetings before the rest are read.
        requests = [scrapy.Request(self.start_urls[0], callback=self.parse)] + [
            scrapy.Request(url, callback=self.parse_event_list)
            for url in self._event_start_urls()
        ]
        yield from [self._track(request) for request in requests]

    def _event_start_urls(self):
        """The department query from DetCityMixin, then the same for the board"""
        dept_url = self.get_event_start_url()
        board_url = dept_url.replace(
            f"term_node_tid_depth={self.dept_cal_id}&term_node_tid_depth_1=All",
            f"term_node_tid_depth=All&term_node_tid_depth_1={self.board_cal_id}",
        )
        return [dept_url, board_url]

    # ----------------------------------------------------------------------
    # Request bookkeeping
    # ----------------------------------------------------------------------

    def _track(self, request):
        """
        Count a request as in flight. Every tracked request settles exactly once,
        through its callback or its errback, so the count reaching zero means both
        sources are fully read. dont_filter keeps the dupefilter from dropping a
        request without calling either.
        """
        self._pending += 1
        return request.replace(dont_filter=True, errback=self._on_error)

    def _settle(self, read, response):
        """
        Run a reader over the response, pass through the requests it yields, then
        settle this one. The reader is called in here, not by the caller, so a
        page that fails to parse still settles instead of stalling every meeting.
        """
        try:
            for result in read(response) or []:
                if isinstance(result, scrapy.Request):
                    yield self._track(result)
        except Exception:
            self.logger.exception("Failed to parse %s", response.url)
        yield from self._request_done()

    def _on_error(self, failure):
        self.logger.error("Request failed: %s", repr(failure.value))
        yield from self._request_done()

    def _request_done(self):
        self._pending -= 1
        if self._pending == 0:
            yield from self._merge_meetings(
                self._primary_meetings, self._legistar_meetings
            )

    # ----------------------------------------------------------------------
    # Legistar (secondary)
    # ----------------------------------------------------------------------

    def parse(self, response):
        # Named explicitly: DetCityMixin.parse comes first in the MRO and routes
        # by detroitmi.gov URL, so super() would never request the Legistar years
        yield from self._settle(partial(LegistarSpider.parse, self), response)

    def _parse_legistar_events_page(self, response):
        yield from self._settle(self._read_legistar_page, response)

    def _read_legistar_page(self, response):
        events = self._parse_legistar_events(response)
        self._legistar_meetings.extend(self.parse_legistar(events))
        yield from self._parse_next_page(response)

    def _parse_legistar_events(self, response):
        """
        Replaces the core parser, which drops every row on this site. The calendar
        icon column has a blank header whose hidden input holds a single space, so
        the core never labels it "iCalendar", then skips each row for having no
        iCalendar URL. Here the column is recognised by its link, and a row without
        one is kept rather than dropped.
        """
        events_tables = response.css("table.rgMasterTable")
        if not events_tables:
            self.logger.warning("No Legistar events table found on %s", response.url)
            return []
        events_table = events_tables[0]

        headers = []
        for header in events_table.css("th[class^='rgHeader']"):
            header_text = " ".join(header.css("*::text").getall()).strip()
            header_inputs = [
                value.strip() for value in header.css("input::attr(value)").getall()
            ]
            header_alts = header.css("img::attr(alt)").getall()
            headers.append(
                header_text
                or next(filter(None, header_inputs), "")
                or next(iter(header_alts), "")
            )

        events = []
        for row in events_table.css("tr.rgRow, tr.rgAltRow"):
            try:
                data = {}
                for header, field in zip(headers, row.css("td")):
                    field_text = " ".join(
                        " ".join(field.css("*::text").getall()).split()
                    )
                    url = None
                    link = field.css("a")
                    if link:
                        attrs = link[0].attrib
                        if "href" in attrs:
                            url = response.urljoin(attrs["href"])
                        # Some Legistar links open a popup instead, as the core allows
                        elif attrs.get("onclick", "").startswith(
                            ("radopen('", "window.open", "OpenTelerikWindow")
                        ):
                            url = response.urljoin(attrs["onclick"].split("'")[1])
                    if url and "View.ashx?M=IC" in url:
                        data["iCalendar"] = {"url": url}
                    elif url:
                        data[header] = {"label": field_text, "url": url}
                    else:
                        data[header] = field_text

                ical_url = data.get("iCalendar", {}).get("url")
                if ical_url:
                    if ical_url in self._scraped_urls:
                        continue
                    self._scraped_urls.add(ical_url)
                events.append(data)
            except Exception:
                self.logger.exception(
                    "Failed to parse a Legistar row on %s", response.url
                )
        return events

    def parse_legistar(self, events):
        if not events:
            self.logger.warning("No Legistar events to parse")
        meetings = []
        for event in events:
            title = self._legistar_label(event, "Name")
            start = self._legistar_start(event)
            if start is None:
                continue
            meeting = Meeting(
                title=title,
                # Legistar's location column holds the virtual attendance details
                description=self._legistar_label(event, "Meeting Location"),
                # Every body on this Legistar site belongs to DWSD. Those that aren't
                # the board or an advisory council are board committees, some
                # without the word in their name.
                classification=self._classify(title, default=COMMITTEE),
                start=start,
                end=None,
                time_notes="",
                all_day=False,
                location=self._water_board_location(
                    self._legistar_label(event, "Meeting Location")
                ),
                links=self.legistar_links(event) + [dict(self.youtube_link)],
                source=self.legistar_source(event),
            )
            meeting["status"] = self._get_status(
                meeting, text=self._legistar_label(event, "Meeting Time")
            )
            meeting["id"] = self._get_id(meeting)
            meetings.append(meeting)
        return meetings

    def _legistar_start(self, event):
        try:
            return self.legistar_start(event)
        except (TypeError, ValueError):
            self.logger.warning(
                "Unparseable Legistar date %r for %r",
                event.get("Meeting Date"),
                event.get("Name"),
            )
            return None

    def _legistar_label(self, event, key):
        value = event.get(key) or ""
        if isinstance(value, dict):
            value = value.get("label", "")
        return value.strip()

    def _water_board_location(self, text):
        """The board's usual venue, when the text names it, otherwise TBD"""
        if "water board building" in text.lower():
            return {"name": "Water Board Building", "address": self.water_board_address}
        return {"name": "TBD", "address": ""}

    # ----------------------------------------------------------------------
    # detroitmi.gov calendar (primary)
    # ----------------------------------------------------------------------

    def parse_event_list(self, response):
        yield from self._settle(self._read_event_list, response)

    def _read_event_list(self, response):
        for href in response.css(".view-content .article-title a::attr(href)").getall():
            event_url = response.urljoin(href)
            if event_url in self._seen_event_urls:
                continue
            self._seen_event_urls.add(event_url)
            yield scrapy.Request(event_url, callback=self.parse_primary_event)
        next_url = self._response_next_url(response)
        if next_url:
            yield scrapy.Request(
                response.urljoin(next_url), callback=self.parse_event_list
            )

    def parse_primary_event(self, response):
        yield from self._settle(self._read_primary_event, response)

    def _read_primary_event(self, response):
        meeting = self.parse_event_page(response)
        if meeting:
            self._primary_meetings.append(meeting)

    def _parse_title(self, response):
        """Drop the month and year: "Board of Water Commissioners June 2026 Meeting" """
        title = MONTH_YEAR_RE.sub("", super()._parse_title(response))
        title = " ".join(title.split())
        if title == BOARD_TITLE + " Meeting":
            return BOARD_TITLE
        # The site uses "Committee Meeting" and "Committee Meetings" for the same
        # monthly meeting, so settle on one to keep it a single series
        if title == COMMITTEE_TITLE + "s":
            return COMMITTEE_TITLE
        return title

    def _parse_description(self, response):
        """
        Only the "Attend Meeting Virtually" block, which has no other field. It is
        the run of centered paragraphs starting at that heading; the public comment
        instructions after it are left out.
        """
        heading = response.xpath(
            "//article[contains(@class, 'description')]"
            "/p[starts-with(normalize-space(), 'Attend Meeting Virtually')]"
        )
        if not heading:
            return ""
        lines = []
        for el in [heading[0]] + heading[0].xpath("./following-sibling::*"):
            if "text-align-center" not in el.attrib.get("class", ""):
                break
            line = " ".join(" ".join(el.css("*::text").getall()).split())
            if line:
                lines.append(line)
        return "\n".join(lines)

    def _description_text(self, response):
        text = " ".join(response.css("article.description *::text").getall())
        return " ".join(text.split())

    def _parse_classification(self, response):
        return self._classify(self._parse_title(response))

    def _parse_location(self, response):
        """
        The location block sits below the event's description. DetCityMixin's own
        parser doesn't match this block and returns nothing for every event.
        """
        info = response.css(".item.location .contact-info")
        name = " ".join(" ".join(info.css("span::text").getall()).split())
        # The address lines are followed by the building's office hours
        lines = "\n".join(info.xpath("./text()").getall()).splitlines()
        address = " ".join(
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith(tuple(calendar.day_abbr))
        )
        if not name and not address:
            # Some events leave the block empty and name the venue in the
            # description instead
            return self._water_board_location(self._description_text(response))
        return {"name": name, "address": address}

    def _parse_links(self, response, start):
        """Attachments only exist on Legistar; they are added when merging"""
        return [dict(self.youtube_link)]

    # ----------------------------------------------------------------------
    # Combining the two sources
    # ----------------------------------------------------------------------

    def _merge_meetings(self, primary_meetings, legistar_meetings):
        """
        Yield every primary meeting, taking attachments and cancellation from the
        Legistar board meeting on the same date, then every Legistar meeting that
        matched nothing.
        """
        board_by_date = defaultdict(list)
        for meeting in legistar_meetings:
            if meeting["title"] == BOARD_TITLE:
                board_by_date[meeting["start"].date()].append(meeting)

        matched = set()
        for meeting in primary_meetings:
            match = None
            if meeting["title"] == BOARD_TITLE:
                candidates = [
                    m
                    for m in board_by_date[meeting["start"].date()]
                    if id(m) not in matched
                ]
                if candidates:
                    match = min(
                        candidates, key=lambda m: abs(m["start"] - meeting["start"])
                    )
            if match:
                matched.add(id(match))
                meeting = meeting.copy()
                meeting["links"] = match["links"]
                if match["status"] == CANCELLED:
                    meeting["status"] = CANCELLED
            yield meeting

        for meeting in legistar_meetings:
            if id(meeting) not in matched:
                yield meeting

    def _get_status(self, item, text=""):
        """
        Leave the description out. Both sources put notes like "The meeting has
        been rescheduled to ..." on the meeting that was moved to, which the core
        reads as a cancellation. Legistar's Meeting Time column, passed as text,
        is where cancellations are actually shown.
        """
        return super()._get_status({**item, "description": ""}, text=text)

    def _classify(self, title, default=NOT_CLASSIFIED):
        lowered = title.lower()
        if "advisory" in lowered:
            return ADVISORY_COMMITTEE
        if "committee" in lowered:
            return COMMITTEE
        if title.startswith(BOARD_TITLE):
            return BOARD
        if "community" in lowered or "town hall" in lowered:
            return FORUM
        return default
