import json
import re
import string
from collections import defaultdict
from datetime import date, datetime, time

import pytz
import scrapy
from city_scrapers_core.constants import ADVISORY_COMMITTEE, BOARD, COMMITTEE, FORUM
from city_scrapers_core.items import Meeting
from dateutil.relativedelta import relativedelta

# Wix Events app that powers the calendar on degc.org/public-authorities
EVENTS_APP_ID = "140603ad-af8d-84a5-2c80-a0f60cb47351"
EVENTS_API_URL = "https://www.wixapis.com/events/v3/events/query"
EVENTS_PAGE_SIZE = 100

# DEGC moved its offices (and board meetings) at the start of FY 2026-2027
OFFICE_MOVE_DATE = date(2026, 7, 1)
GUARDIAN_LOCATION = {
    "name": "DEGC, Guardian Building",
    "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
}
JEFFERSON_LOCATION = {
    "name": "DEGC",
    "address": "150 W Jefferson Ave, Suite 1700, Detroit, MI 48226",
}
TBD_LOCATION = {"name": "TBD", "address": ""}

MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
DATE_RE = re.compile(
    r"\b(?P<month>{})[a-z]*\.?\s+(?P<day>\d{{1,2}}),?\s*(?P<year>\d{{4}})\b".format(
        "|".join(MONTHS)
    ),
    flags=re.I,
)
# Older documents use dates like "06-25-19"
NUMERIC_DATE_RE = re.compile(r"\b(?P<month>\d{2})-(?P<day>\d{2})-(?P<year>\d{2})\b")
# Filters out dated links that aren't meeting documents (budgets, reports, etc.)
MEETING_DOC_RE = re.compile(r"meeting|hearing|agenda|minutes|notice", flags=re.I)
# Words that don't distinguish one meeting body from another
FILLER_WORDS_RE = re.compile(
    r"\b(city of detroit|regular|special|meeting|notice|agenda|minutes|cancell?ation|"
    r"cancell?ed|reschedul\w*|revised|updated|the|of|D-?NMDC|DBRA|DDA|EDC|LDFA|"
    r"EMWCIA|NDC)\b",
    flags=re.I,
)


class DetAuthorityMixin:
    """Mixin for shared behavior on Detroit public authority scrapers.

    Meetings come from two places on degc.org (a Wix site):
    - The Wix Events calendar on the public authorities page, which is queried
      through the Wix Events API using a site visitor token
    - Meeting documents (notices, agendas, minutes) linked on each authority's page
    """

    timezone = "America/Detroit"
    title = "Board of Directors"
    # Acronym used by DEGC for the authority in event titles and categories
    tab_title = ""
    # Extra phrases identifying this authority's events, defaults to the agency name
    event_keywords = []
    start_urls = ["https://www.degc.org/public-authorities"]
    classification = BOARD
    default_start_time = time(0)
    video_link = None

    def parse(self, response):
        """Request a visitor token for querying the calendar's events.

        The calendar page embeds a token too, but the page is served from a cache
        so that token is often expired.
        """
        yield response.follow(
            "/_api/v1/access-tokens",
            callback=self._parse_access_tokens,
            dont_filter=True,
        )

    def _parse_access_tokens(self, response):
        token = response.json()["apps"][EVENTS_APP_ID]["instance"]
        yield self._events_request(token)

    def _events_request(self, token, offset=0, events=None):
        body = {
            "query": {
                "paging": {"limit": EVENTS_PAGE_SIZE, "offset": offset},
                "sort": [{"fieldName": "dateAndTimeSettings.startDate"}],
            }
        }
        return scrapy.Request(
            EVENTS_API_URL,
            method="POST",
            body=json.dumps(body),
            headers={"Authorization": token, "Content-Type": "application/json"},
            callback=self._parse_events,
            cb_kwargs={"token": token, "events": events or []},
            dont_filter=True,
        )

    def _parse_events(self, response, token, events):
        """Collect all pages of events, then request the authority's documents"""
        data = response.json()
        events = events + [e for e in data["events"] if self._is_agency_event(e)]
        paging = data["pagingMetadata"]
        next_offset = paging["offset"] + paging["count"]
        if paging["count"] and next_offset < paging.get("total", 0):
            yield self._events_request(token, offset=next_offset, events=events)
        else:
            if not events:
                self.logger.warning(
                    f"The events API returned no events for {self.tab_title}: "
                    f"{EVENTS_API_URL}"
                )
            yield scrapy.Request(
                self.agency_url,
                callback=self._parse_documents,
                cb_kwargs={"events": events},
            )

    def _is_agency_event(self, event):
        """Check whether an event is for this authority by category or title"""
        categories = [
            c["name"].strip()
            for c in (event.get("categories") or {}).get("categories", [])
            if c.get("type") == "MANUAL"
        ]
        if self.tab_title in categories:
            return True
        keywords = self.event_keywords or [
            self.tab_title,
            re.sub(r"^Detroit ", "", self.agency),
        ]
        # An empty keyword would match every title
        keywords = [k for k in keywords if k]
        pattern = r"\b(?:{})\b".format("|".join(re.escape(k) for k in keywords))
        return bool(re.search(pattern, event["title"], flags=re.I))

    def _parse_documents(self, response, events=()):
        """Combine events with meeting documents.

        Meetings from events are completed from their detail pages, meetings that
        only appear in documents are yielded directly.
        """
        doc_map = self._parse_document_links(response)
        if not doc_map:
            self.logger.warning(f"No dated meeting documents found: {response.url}")
        meetings = self._parse_event_meetings(events)

        # Attach documents to events with the same date and title
        matched = set()
        for meeting in meetings:
            key = (meeting["start"].date(), meeting["title"])
            if key in doc_map:
                meeting["links"] = doc_map.pop(key) + meeting["links"]
                matched.add(id(meeting))
        # Titles can differ between events and documents (mostly public hearings),
        # so fall back to an unmatched event on the same date with the same type
        for (doc_date, doc_title), links in list(doc_map.items()):
            candidates = [
                m
                for m in meetings
                if m["start"].date() == doc_date
                and id(m) not in matched
                and m["classification"] == self._parse_classification(doc_title)
            ]
            if len(candidates) == 1:
                candidates[0]["links"] = links + candidates[0]["links"]
                matched.add(id(candidates[0]))
                del doc_map[(doc_date, doc_title)]

        for (doc_date, doc_title), links in doc_map.items():
            meetings.append(self._parse_document_meeting(doc_date, doc_title, links))

        now = datetime.now(pytz.timezone(self.timezone)).replace(tzinfo=None)
        last_year = now - relativedelta(years=1)
        for meeting in meetings:
            if meeting["start"] < last_year and not self.settings.getbool(
                "CITY_SCRAPERS_ARCHIVE"
            ):
                continue
            detail_url = meeting.pop("_detail_url", None)
            if detail_url:
                yield scrapy.Request(
                    detail_url,
                    callback=self._parse_event_detail,
                    errback=self._handle_detail_error,
                    cb_kwargs={"meeting": meeting},
                    dont_filter=True,
                )
            else:
                yield self._finish_meeting(meeting)

    def _parse_event_detail(self, response, meeting):
        """Add the description and attachments shown on an event's detail page.

        The events API leaves the description out for occurrences of recurring
        events, but the detail page always has it. The page's "About the event"
        section is collapsed behind "Show More" in the rendered HTML, so the full
        text is read from the event data embedded in the page, with the rendered
        section as a fallback.
        """
        event = self._detail_page_event(response)
        if event:
            description = self._description_text(
                event.get("description"), event.get("longDescription")
            )
            links = self._parse_event_links(event.get("longDescription"))
        else:
            about = response.css('[data-hook="about-section"]')
            description = "\n".join(
                re.sub(r"\s+", " ", " ".join(p.css("*::text").getall())).strip()
                for p in about.css("p, li, h3, h4")
            ).strip()
            links = [
                {"href": response.urljoin(a.attrib["href"]), "title": "Document"}
                for a in about.css('a[href*="/_files/"]')
            ]
        if description:
            meeting["description"] = description
        hrefs = [link["href"] for link in meeting["links"]]
        meeting["links"] += [link for link in links if link["href"] not in hrefs]
        yield self._finish_meeting(meeting)

    def _handle_detail_error(self, failure):
        """Keep the meeting from the events API if its detail page can't be read"""
        meeting = failure.request.cb_kwargs["meeting"]
        self.logger.warning(
            f"Could not read the event page, keeping the events API data: "
            f"{failure.request.url} ({failure.value})"
        )
        yield self._finish_meeting(meeting)

    def _detail_page_event(self, response):
        """Return the event data embedded in a Wix event detail page"""
        warmup_data = json.loads(response.css("#wix-warmup-data::text").get() or "{}")
        page_state = (
            warmup_data.get("appsWarmupData", {})
            .get(EVENTS_APP_ID, {})
            .get("EventsPageInitialState", {})
        )
        event = (page_state.get("event") or {}).get("event")
        if not event:
            self.logger.warning(
                f"No event data found on the event page, using its rendered "
                f"About the event section: {response.url}"
            )
        return event

    def _finish_meeting(self, meeting):
        """Add the video link, status and id to a meeting dict"""
        if self.video_link:
            meeting["links"].append(
                {"href": self.video_link, "title": "YouTube channel"}
            )
        status_text = " ".join(
            [meeting.pop("_status_text")] + [link["title"] for link in meeting["links"]]
        )
        meeting = Meeting(**meeting)
        meeting["status"] = self._get_status(meeting, text=status_text)
        meeting["id"] = self._get_id(meeting)
        return meeting

    def _parse_event_meetings(self, events):
        """Create meeting dicts from events, dropping duplicates.

        When an occurrence of a recurring event is edited on the site the original
        is marked as canceled and a copy is created, so prefer events that aren't.
        """
        meeting_map = {}
        for event in sorted(events, key=lambda e: e["status"] == "CANCELED"):
            meeting = self._parse_event_meeting(event)
            key = (meeting["start"], meeting["title"])
            if key not in meeting_map:
                meeting_map[key] = meeting
        return list(meeting_map.values())

    def _parse_event_meeting(self, event):
        title = self._parse_title(event["title"])
        status_text = event["title"]
        if event["status"] == "CANCELED":
            status_text += " Cancelled"
        page_url = event.get("eventPageUrl") or {}
        detail_url = page_url.get("base", "") + page_url.get("path", "")
        return dict(
            title=title,
            description=self._description_text(
                event.get("shortDescription"), event.get("description")
            ),
            classification=self._parse_classification(title),
            start=self._parse_event_start(event),
            end=None,
            time_notes="",
            all_day=False,
            location=self._parse_event_location(event),
            links=self._parse_event_links(event.get("description")),
            source=detail_url or self.start_urls[0],
            _status_text=status_text,
            _detail_url=detail_url,
        )

    def _parse_document_meeting(self, doc_date, title, links):
        """Create a meeting from documents that don't match an event"""
        classification = self._parse_classification(title)
        if classification == FORUM:
            # Public hearings are often held outside the DEGC offices
            location = TBD_LOCATION
        elif doc_date < OFFICE_MOVE_DATE:
            location = GUARDIAN_LOCATION
        else:
            location = JEFFERSON_LOCATION
        return dict(
            title=title,
            description="",
            classification=classification,
            start=datetime.combine(doc_date, self.default_start_time),
            end=None,
            time_notes="See source to confirm meeting time",
            all_day=False,
            location=location,
            links=links,
            source=self.agency_url,
            _status_text="",
        )

    def _parse_event_start(self, event):
        """Parse start datetime in the event's local time zone

        The DEGC API used for fetching the events provides date
        and time in UTC format. This method converts UTC dt to
        the scraper's timezone.
        """
        settings = event["dateAndTimeSettings"]
        start_utc = datetime.fromisoformat(settings["startDate"].replace("Z", "+00:00"))
        tz = pytz.timezone(settings.get("timeZoneId") or self.timezone)
        return start_utc.astimezone(tz).replace(tzinfo=None)

    def _parse_event_location(self, event):
        location = event.get("location") or {}
        if location.get("locationTbd"):
            return TBD_LOCATION
        address = (location.get("address") or {}).get("formattedAddress") or ""
        if "500 Griswold" in address:
            return GUARDIAN_LOCATION
        if re.search(r"150 W\.? Jefferson", address):
            return JEFFERSON_LOCATION
        address = re.sub(r",\s*USA$", "", address.strip())
        name = (location.get("name") or "").strip()
        # Location names are sometimes just the city or the address itself
        if name.lower() == "detroit" or address.startswith(name):
            name = ""
        if not address:
            return TBD_LOCATION
        return {"name": name, "address": address}

    def _description_text(self, summary, rich_text):
        """Return an event's description as it's shown on its detail page.

        This is the summary under the title followed by the "About the event"
        text, which is where attendance details like Zoom links, passcodes and
        dial-in numbers are posted. Paragraphs that are only an attachment link
        are left out since those are added to links instead.
        """
        lines = []
        for node in (rich_text or {}).get("nodes", []):
            for block in self._description_blocks(node):
                text = self._rich_text(block).replace("\xa0", " ").strip()
                links = list(self._parse_description_links(block))
                if (
                    text
                    and links
                    and all("/_files/" in href for _, href in links)
                    and text == " ".join(link_text for link_text, _ in links)
                ):
                    continue
                # Collapse runs of empty paragraphs into a single blank line
                if text or (lines and lines[-1]):
                    lines.append(text)
        about = "\n".join(lines).strip()
        summary = (summary or "").strip()
        return "\n\n".join(part for part in (summary, about) if part)

    def _description_blocks(self, node):
        """Split a rich text node into the blocks displayed as separate lines"""
        if node.get("type", "").endswith("_LIST"):
            for item in node.get("nodes", []):
                yield from self._description_blocks(item)
        elif node.get("type") == "LIST_ITEM":
            for child in node.get("nodes", []):
                yield from self._description_blocks(child)
        else:
            yield node

    def _rich_text(self, node):
        text = (node.get("textData") or {}).get("text", "")
        return text + "".join(self._rich_text(c) for c in node.get("nodes", []))

    def _parse_event_links(self, rich_text):
        """Parse attachment links from an event's rich text description"""
        links = []
        for text, href in self._parse_description_links(rich_text):
            if "/_files/" not in href:
                continue
            title = text if text and not text.startswith("http") else "Document"
            if href not in [link["href"] for link in links]:
                links.append({"href": href, "title": title})
        return links

    def _parse_description_links(self, node):
        """Recursively find (text, url) pairs in a Wix rich text node"""
        if isinstance(node, list):
            for child in node:
                yield from self._parse_description_links(child)
        elif isinstance(node, dict):
            text_data = node.get("textData") or {}
            for decoration in text_data.get("decorations", []):
                url = ((decoration.get("linkData") or {}).get("link") or {}).get("url")
                if url:
                    yield text_data.get("text", "").strip(), url
            for child in node.get("nodes", []):
                yield from self._parse_description_links(child)

    def _parse_document_links(self, response):
        """Group meeting document links by date and meeting title"""
        link_map = defaultdict(list)
        for link in response.css("a[href]"):
            link_text = re.sub(
                r"[\s\u200b]+", " ", " ".join(link.css("*::text").extract())
            ).strip()
            if not MEETING_DOC_RE.search(link_text):
                continue
            doc_date, date_str = self._parse_date(link_text)
            if not doc_date:
                continue
            link_title = re.sub(r"\s+", " ", link_text.replace(date_str, " ")).strip(
                " -–,"
            )
            key = (doc_date, self._parse_title(link_title))
            href = response.urljoin(link.attrib["href"])
            if href not in [doc["href"] for doc in link_map[key]]:
                link_map[key].append({"href": href, "title": link_title})
        return link_map

    def _parse_date(self, text):
        """Return the first date in a string and the matched text"""
        match = DATE_RE.search(text)
        if match:
            month = MONTHS.index(match.group("month").lower()) + 1
            year = int(match.group("year"))
        else:
            match = NUMERIC_DATE_RE.search(text)
            if not match:
                self.logger.warning(
                    f"No date found in the attachment record {text!r}: "
                    f"{self.agency_url}"
                )
                return None, None
            month = int(match.group("month"))
            year = 2000 + int(match.group("year"))
        try:
            return date(year, month, int(match.group("day"))), match.group()
        except ValueError:
            self.logger.warning(
                f"Error occurred while parsing the date of the attachment record "
                f"{text!r}: {self.agency_url}"
            )
            return None, None

    def _parse_title(self, text):
        """Return a consistent meeting title for event titles and document names,
        can be overridden in spiders for authority-specific meetings"""
        text = re.sub(r"\s+", " ", text).strip()
        upper_text = text.upper()
        if "PUBLIC HEARING" in upper_text:
            return self._parse_hearing_title(text)
        if "PUBLIC INFORMA" in upper_text:
            return "Public Information Meeting"
        committee_match = re.search(r"^(.*?)\bCOMMITTE+\b", text, flags=re.I)
        if committee_match:
            name = self._clean_title_text(committee_match.group(1))
            return "{} Committee".format(name).strip()
        if "SPECIAL" in upper_text:
            return "Special Board Meeting"
        return self.title

    def _parse_hearing_title(self, text):
        """Return title for a public hearing including the project name"""
        name = re.split(r"public hearing", text, flags=re.I)[0]
        name = re.sub(r"\b(transformational )?brownfield plan\b", "", name, flags=re.I)
        return "{} Public Hearing".format(self._clean_title_text(name)).strip()

    def _clean_title_text(self, text):
        text = FILLER_WORDS_RE.sub(" ", text)
        text = re.sub(r"[^\w\s]", " ", text)
        text = string.capwords(text.lower())
        # Keep roman numerals in project names like "COE II" capitalized
        return re.sub(r"\b[IV]{2,4}\b", lambda m: m.group().upper(), text, flags=re.I)

    def _parse_classification(self, title):
        """Return classification based on the parsed meeting title"""
        if "Advisory" in title:
            return ADVISORY_COMMITTEE
        if "Committee" in title:
            return COMMITTEE
        if "Hearing" in title or "Public Information" in title:
            return FORUM
        return self.classification
