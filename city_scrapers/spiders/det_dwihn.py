import re
from datetime import time
from urllib.parse import urlparse

import pytz
from city_scrapers_core.constants import (
    ADVISORY_COMMITTEE,
    BOARD,
    COMMITTEE,
    FORUM,
    NOT_CLASSIFIED,
)
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import CityScrapersSpider
from dateutil.parser import ParserError, parse
from scrapy import Request


class DetDwihnSpider(CityScrapersSpider):
    name = "det_dwihn"
    agency = "Detroit Wayne Integrated Health Network"
    timezone = "America/Detroit"
    base_url = "https://dwihn.org"

    start_urls = [
        "https://dwihn.org/news-events/events?field_categories_target_id=14&event_time=All"  # noqa
    ]
    youtube_link = {
        "title": "YouTube channel",
        "href": "https://www.youtube.com/channel/UCnIswzB1YZzx0BgnsUFZKcg",
    }

    common_location = {
        "name": "DWIHN Administration Building",
        "address": "8726 Woodward Ave, Detroit, MI 48202",
    }

    # Canonical titles for the recurring meetings, matched against the title
    # once date change and cancellation markers have been removed
    title_map = [
        (
            r"^program compliance committee( \(pcc\))?( meeting)?$",
            "Program Compliance Committee (PCC) Meeting",
        ),
        (
            r"^policy ?/ ?bylaw committee( meeting)?$",
            "Policy / Bylaw Committee Meeting",
        ),
        (r"^budget hearing$", "Budget Hearing"),
        (r"^finance committee( meeting)?$", "Finance Committee Meeting"),
        (r"^full board( of directors)?( meeting)?$", "Full Board of Directors Meeting"),
        (
            r"^board executive committee( meeting)?$",
            "Board Executive Committee Meeting",
        ),
        (
            r"^sud oversight policy board( meeting)?$",
            "SUD Oversight Policy Board Meeting",
        ),
        (
            r"^board building ad-?hoc committee( meeting)?$",
            "Board Building AD-HOC Committee Meeting",
        ),
    ]

    # Paragraphs describing how to attend remotely
    join_re = re.compile(
        r"\bjoin\b|dial(ing)? in|meeting id|passcode|zoom\.us|teams\.microsoft|webex",
        re.I,
    )
    login_link_re = re.compile(r"log\s*-?\s*in|meeting details", re.I)

    def parse(self, response):
        """Parse the events listing and follow each event to its detail page."""
        cards = response.css("a.event-cards-row__link")
        if not cards:
            self.logger.warning(f"No events found on the listing page: {response.url}")
        for card in cards:
            href = card.attrib.get("href")
            if href:
                yield response.follow(href, callback=self.parse_event)

        next_page = response.css("a.js-views-infinite-scroll-load-more::attr(href)")
        if next_page:
            yield response.follow(next_page.get(), callback=self.parse)

    def parse_event(self, response):
        """
        Parse an event detail page into a meeting.

        Links to Drupal media pages are followed one level further down to
        reach the document file before the meeting is yielded.
        """
        raw_title = self._clean_text(
            " ".join(response.css("h1.interior-hero__h1 ::text").getall())
        )
        start, end = self._parse_times(response)
        if not raw_title or start is None:
            self.logger.warning(
                f"Could not parse the title or start of the event: {response.url}"
            )
            return

        body_text = self._clean_text(
            " ".join(response.css(".evt-body ::text").getall())
        )
        if start.time() == time(0):
            start = self._parse_body_time(start, body_text)
        title = self._parse_title(raw_title)
        meeting = Meeting(
            title=title,
            description=self._parse_description(response),
            classification=self._parse_classification(title),
            start=start,
            end=end,
            all_day=False,
            time_notes="",
            location=self._parse_location(response),
            links=self._parse_links(response),
            source=response.url,
        )
        meeting["status"] = self._get_status(
            meeting, text=self._status_text(raw_title, body_text, start)
        )
        meeting["id"] = self._get_id(meeting)

        yield from self._resolve_links(meeting, 0)

    def _resolve_links(self, meeting, index):
        """Request the next unresolved media page, or yield the finished meeting."""
        for i in range(index, len(meeting["links"])):
            href = meeting["links"][i]["href"]
            if self._is_media_page(href):
                yield Request(
                    href,
                    callback=self._parse_media_page,
                    errback=self._media_page_failed,
                    cb_kwargs={"meeting": meeting, "index": i},
                    dont_filter=True,
                )
                return
        yield meeting

    def _parse_media_page(self, response, meeting, index):
        """Swap a media page link for the document it offers for download."""
        file_href = response.css("a.media-doc-page__download::attr(href)").get()
        if file_href:
            meeting["links"][index]["href"] = self._absolute_url(
                response.urljoin(file_href)
            )
        else:
            self.logger.warning(
                f"No document found on the media page, keeping its link: {response.url}"
            )
        yield from self._resolve_links(meeting, index + 1)

    def _media_page_failed(self, failure):
        """Keep the media page link as is if it can't be fetched."""
        request = failure.request
        self.logger.warning(
            f"Could not fetch the media page, keeping its link: {request.url} "
            f"({failure.value})"
        )
        yield from self._resolve_links(
            request.cb_kwargs["meeting"], request.cb_kwargs["index"] + 1
        )

    def _parse_title(self, raw_title):
        """Remove date change and cancellation markers, then normalize."""
        title = re.sub(r"\*?\s*rescheduled\s*:?", "", raw_title, flags=re.I)
        title = re.sub(
            r"[\s\-–]*\*?\s*(cancell?ed|new date|new time)\b\s*",
            " ",
            title,
            flags=re.I,
        )
        title = re.sub(r"\s+", " ", title).strip(" -–*")
        for pattern, canonical in self.title_map:
            if re.search(pattern, title, re.I):
                return canonical
        return title

    def _parse_times(self, response):
        """Parse start and end from the event's time elements."""
        values = response.css(".evt-meta time::attr(datetime)").getall()
        if not values:
            self.logger.warning(f"No event times found: {response.url}")
            return None, None
        try:
            parsed = [parse(value) for value in values]
        except (ParserError, ValueError, OverflowError):
            self.logger.warning(
                f"Could not parse the event times {values}: {response.url}"
            )
            return None, None
        local = [self._to_local(value) for value in parsed]
        start = local[0]
        if len(local) < 2:
            self.logger.warning(f"No end time found: {response.url}")
            return start, None
        end = local[1]
        if end <= start:
            self.logger.warning(
                f"End time {end} is not after the start {start}, dropping it: "
                f"{response.url}"
            )
            return start, None
        return start, end

    def _parse_body_time(self, start, body_text):
        """Take the time from the body text for events posted without one."""
        match = re.search(
            r"(\w+ \d{1,2},? \d{4}),?\s*(?:at|@)\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m)",
            body_text,
            re.I,
        )
        if match:
            try:
                parsed = parse(" ".join(match.groups()))
            except (ParserError, ValueError, OverflowError):
                self.logger.warning(f"Could not parse the time from {match.group(0)!r}")
                return start
            if parsed.date() == start.date():
                return parsed
        self.logger.warning(
            f"No start time found for the event on {start.date()}, using midnight"
        )
        return start

    def _to_local(self, value):
        """Convert an offset aware datetime to naive Detroit time."""
        if value.tzinfo is None:
            return value
        return value.astimezone(pytz.timezone(self.timezone)).replace(tzinfo=None)

    def _parse_description(self, response):
        """Return information on joining the meeting online, if any."""
        blocks = []
        for block in response.css(".evt-body").xpath(
            ".//*[self::p or self::li][not(.//p) and not(.//li)]"
        ):
            text = self._clean_text(" ".join(block.css("::text").getall()))
            if text and self.join_re.search(text):
                blocks.append(text)
        if blocks:
            # URLs are often written out and then repeated as the link text
            return re.sub(r"(https?://\S+)\s*\1", r"\1", " ".join(blocks))

        for link in response.css(".evt-body a"):
            text = self._clean_text(" ".join(link.css("::text").getall()))
            if self.login_link_re.search(text):
                return 'Virtual login details are available in the "{}" link.'.format(
                    self._parse_link_title(text)
                )
        return ""

    def _parse_classification(self, title):
        lowered = title.lower()
        if "advisory" in lowered:
            return ADVISORY_COMMITTEE
        if "committee" in lowered:
            return COMMITTEE
        if "hearing" in lowered:
            return FORUM
        if "board" in lowered:
            return BOARD
        return NOT_CLASSIFIED

    def _parse_location(self, response):
        """Parse the location line, using the admin building as the default."""
        items = [
            self._clean_text(text)
            for text in response.css(".evt-meta__text").xpath("string()").getall()
        ]
        # The first item is always the date
        location_text = next((text for text in items[1:] if text), "")
        if not location_text:
            self.logger.warning(
                f"No location found, using the admin building: {response.url}"
            )
            return self.common_location
        if "8726 woodward" in location_text.lower():
            return self.common_location
        match = re.match(r"^(?P<name>.*?)[,\s]*(?P<address>\d.*)$", location_text)
        if not match:
            self.logger.warning(
                f"No address found in the location {location_text!r}: {response.url}"
            )
            return {"name": location_text, "address": ""}
        return {
            "name": match.group("name").strip(),
            "address": re.sub(r"\s+,", ",", match.group("address")).strip(),
        }

    def _parse_links(self, response):
        links = []
        seen = set()
        for link in response.css(".evt-body a"):
            href = link.attrib.get("href", "").strip()
            if not href or href.startswith(("mailto:", "tel:", "#")):
                continue
            href = self._absolute_url(response.urljoin(href))
            if href in seen or "zoom.us" in href:
                continue
            seen.add(href)
            title = self._parse_link_title(
                self._clean_text(" ".join(link.css("::text").getall()))
            )
            if "qualtrics.com" in href:
                title = "Good & Welfare Registration"
            links.append({"title": title or "Link", "href": href})
        links.append(dict(self.youtube_link))
        return links

    def _parse_link_title(self, text):
        """Turn "Click HERE for the Agenda" style link text into a title."""
        if re.match(r"cancell?ed\b", text, re.I):
            return "Cancellation Notice"
        title = re.sub(r"^click here( for)?( the)?\s*", "", text, flags=re.I)
        title = title.rstrip(". ")
        return title[:1].upper() + title[1:] if title else text

    def _status_text(self, raw_title, body_text, start):
        """Text for _get_status.

        A meeting moved *to* this date says it was "rescheduled to be held on"
        its own date, which isn't a cancellation of this meeting.
        """
        text = " ".join([raw_title, body_text])
        match = re.search(
            r"rescheduled to be held on (?:\w+,\s*)?(\w+ \d{1,2},? \d{4})", text, re.I
        )
        if match:
            try:
                new_date = parse(match.group(1)).date()
            except (ParserError, ValueError, OverflowError):
                self.logger.warning(f"Could not parse the new date {match.group(1)!r}")
                return text
            if new_date == start.date():
                return re.sub(r"rescheduled", "", text, flags=re.I)
        return text

    def _is_media_page(self, href):
        """Internal links outside the files directory are Drupal media pages."""
        parsed = urlparse(href)
        return parsed.netloc.endswith("dwihn.org") and not parsed.path.startswith(
            ("/sites/default/files/", "/events/", "/news-events")
        )

    def _absolute_url(self, href):
        """Point links on the backend host at the public site."""
        return re.sub(r"^https?://live-dwihn\.pantheonsite\.io", self.base_url, href)

    def _clean_text(self, text):
        return re.sub(r"\s+", " ", text or "").strip()
