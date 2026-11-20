import re
from collections import defaultdict
from datetime import datetime, timedelta
from urllib import parse

import scrapy
from city_scrapers_core.items import Meeting
from dateutil.parser import parse as dateutil_parser
from scrapy import signals
from twisted.python.failure import Failure


class DetCitySourceError(Exception):
    """A run of a detroitmi.gov calendar spider that couldn't read its source"""


class DetCityMixin:
    timezone = "America/Detroit"
    # detroitmi.gov's robots.txt disallows every URL with a query string, which
    # covers all of its calendar and document filter pages
    custom_settings = {"ROBOTSTXT_OBEY": False}
    dept_cal_id = None  # Agency URL param on calendar page with "Department" drop down
    dept_doc_id = (
        ""  # Agency URL param when filtering documents page with "Department" drop down
    )
    agency_cal_id = None  # Agency URL param when filtering the calendar page
    agency_doc_id = (
        None  # Agency URL param (or list of params) when filtering the documents page
    )
    start_days_prev = 120  # Number of days before today to start searching
    doc_query_param_dept = "field_department_target_id[0][target_id]"
    doc_query_param = "field_department_target_id_1[0][target_id]"

    # Dates at the start of a document title: "2019-01-17", "2019 01 17"
    doc_numeric_date_re = re.compile(r"^\d{4}[ -]\d{1,2}[ -]\d{1,2}")
    # Dates anywhere in a document title: "Oct 1, 2026", "Jan. 29, 2026", "June 4 2026"
    doc_month_date_re = re.compile(r"[a-zA-Z]{3,9}\.? \d{1,2}\.?,? \d{4}")

    def __init__(self, *args, **kwargs):
        """Initialize spider document link list and doc date defaultdict for matching"""
        self.document_links = []
        self.document_date_map = defaultdict(list)
        self._failed_requests = 0
        self._meeting_count = 0
        super().__init__(*args, **kwargs)

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider._count_meeting, signal=signals.item_scraped)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider

    @property
    def start_urls(self):
        """Start with documents if provided, otherwise from events"""
        if self.agency_doc_id or self.dept_doc_id:
            agency_doc_id = self.agency_doc_id
            if isinstance(agency_doc_id, list):
                agency_doc_id = agency_doc_id[0]
            return [
                "https://detroitmi.gov/documents?{}={}&{}={}".format(
                    self.doc_query_param_dept,
                    self.dept_doc_id,
                    self.doc_query_param,
                    agency_doc_id or "",
                )
            ]
        else:
            return [self.get_event_start_url()]

    def start_requests(self):
        """Request the start URL with an errback, which the default request lacks"""
        for url in self.start_urls:
            errback = self._on_request_error
            if "/documents?" in url:
                errback = self._on_documents_error
            yield scrapy.Request(url, callback=self.parse, errback=errback)

    def get_event_start_url(self):
        """
        Get the initial calendar filter URL based on start_days_prev and agency_cal_id
        """
        start_date = (datetime.now() - timedelta(days=self.start_days_prev)).strftime(
            "%Y-%m-%d"
        )

        # If no department filter is specified, use the "Government" filter only
        if self.dept_cal_id is None:
            return (
                "https://detroitmi.gov/Calendar-and-Events?"
                "field_start_value={}&term_node_tid_depth_1={}"
            ).format(start_date, self.agency_cal_id)

        # Else filter add the Department filter
        else:
            return (
                "https://detroitmi.gov/Calendar-and-Events?"
                "field_start_value={}&term_node_tid_depth={}&term_node_tid_depth_1={}"
            ).format(start_date, self.dept_cal_id or "All", self.agency_cal_id or "All")

    def parse(self, response):
        """Set parse method based on the response URL"""
        if "Calendar-and-Events" in response.url:
            return self.parse_event_list(response)
        elif "/events/" in response.url:
            return self.parse_event_page(response)
        else:
            return self.parse_documents_page(response)

    def parse_documents_page(self, response):
        """Parse the document search result page"""
        # Add links if available
        self.document_links.extend(self._parse_document_links(response))
        # Continue iterating through results if not at the end
        next_url = self._response_next_url(response)
        # Create next_url for documents if additional agency doc IDs
        if not next_url and isinstance(self.agency_doc_id, list):
            next_url = self._replace_agency_doc_param(response.url)
        if next_url:
            yield scrapy.Request(
                response.urljoin(next_url),
                callback=self.parse_documents_page,
                errback=self._on_documents_error,
                dont_filter=True,
            )
        else:
            yield self._events_request()

    def _events_request(self):
        """
        Map the documents read so far to dates, then request the events. Documents
        only add links, so this runs even when a documents page failed.
        """
        self._create_document_date_map()
        return scrapy.Request(
            self.get_event_start_url(),
            callback=self.parse_event_list,
            errback=self._on_request_error,
            dont_filter=True,
        )

    def parse_event_list(self, response):
        """Iterate through the event results page results"""
        for event in response.css(".view-content .article-title a::attr(href)"):
            event_url = response.urljoin(event.extract())
            # Cloudflare swaps an email address in a listing for an
            # /cdn-cgi/l/email-protection link, which isn't an event
            if "/events/" not in event_url:
                self.logger.warning("Skipped non-event link %s", event_url)
                continue
            yield scrapy.Request(
                event_url,
                callback=self.parse_event_page,
                errback=self._on_request_error,
                dont_filter=True,
            )
        next_url = self._response_next_url(response)
        if next_url:
            yield scrapy.Request(
                response.urljoin(next_url),
                callback=self.parse_event_list,
                errback=self._on_request_error,
                dont_filter=True,
            )

    def parse_event_page(self, response):
        """Yield a meeting from an individual event page"""
        start = self._parse_start(response)
        if not start:
            self.logger.warning("No start date parsed from %s", response.url)
            return

        meeting = Meeting(
            title=self._parse_title(response),
            description=self._parse_description(response),
            classification=self._parse_classification(response),
            start=start,
            end=self._parse_end(response, start),
            time_notes="",
            all_day=False,
            location=self._parse_location(response),
            links=self._parse_links(response, start),
            source=self._parse_source(response),
        )
        # The raw title keeps words like "CANCELLED" that the clean title drops
        meeting["status"] = self._get_status(meeting, text=self._raw_title(response))
        meeting["id"] = self._get_id(meeting)
        return meeting

    def _raw_title(self, response):
        """The event title as the page shows it"""
        return (response.css(".title > span::text").extract_first() or "").strip()

    def _parse_title(self, response):
        """Parse the title, removing the date if included"""
        title_text = self._raw_title(response)
        return re.sub(r"( - )?\d{1,4}-\d{1,2}-\d{1,4}$", "", title_text).strip()

    def _parse_description(self, response):
        """Parse the event description"""
        return " ".join(response.css("article.description > *::text").extract()).strip()

    def _parse_start(self, response):
        """Parse the start datetime"""
        date_str = response.css(".date time::attr(datetime)").extract_first()
        time_str = "".join(response.css("article.time::text").extract()).strip()
        if not time_str:
            time_str = "".join(response.css("article.time *::text").extract()).strip()
        time_split = re.split(r"-|(?<=m)(?: to)?\s+(?=\d)", time_str)
        start_str = time_split[0].strip()
        start_str = re.sub(r"\.|from", "", start_str.lower())
        if date_str is None:
            return

        start_dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        # If start str doesn't have numbers, return midnight
        if not re.search(r"\d+", start_str):
            return start_dt

        if "am" not in start_str and "pm" not in start_str:
            if len(time_split) > 1:
                end_str = time_split[1].lower().replace(".", "")
                if "am" in end_str or "pm" in end_str:
                    start_str += "am" if "a" in end_str else " pm"
            # Create int by getting the first number (excluding minutes)
            start_int = int(re.search(r"\d+", start_str).group())
            start_nums = re.search(r"[\d:]+", start_str).group()
            start_str = start_nums + ("pm" if start_int < 8 else "am")
        return datetime.combine(start_dt.date(), self._parse_time_str(start_str))

    def _parse_end(self, response, start):
        """
        Parse the end datetime.
        """
        time_str = re.sub(
            r"[Nn]oon",
            "12:00 p.m.",
            "".join(response.css("article.time::text").extract()).strip(),
        )
        time_split = re.split(r"-|(?<=m)(?: to)?\s+(?=\d)", time_str)
        if len(time_split) > 1:
            end_str = time_split[1].strip()
            end_num = re.search(r"[\d:]+", end_str).group()
            apm_match = re.search(r"[ap]m", end_str.replace(".", ""))
            if apm_match:
                end_str = end_num + apm_match.group()
            else:
                end_int = int(re.search(r"\d+", end_str).group())
                end_str = end_num + ("pm" if end_int < 8 else "am")
            return datetime.combine(start.date(), self._parse_time_str(end_str))
        return None

    def _parse_time_notes(self, has_end):
        """
        Parse time notes based on whether the end datetime was scraped or a default
        """
        return ""

    def _parse_location(self, response):
        """Parse the location name and address from the page"""
        # Current markup: <article class="contact-info"><span>Name</span><br>Address
        info = response.css(".item.location .contact-info")
        name = " ".join(" ".join(info.css("span::text").extract()).split())
        address = " ".join(" ".join(info.xpath("./text()").extract()).split())
        if not name and not address:
            # Markup used before the site's redesign
            loc_info = response.css(".location-info")
            name = (loc_info.css("p strong span::text").extract_first() or "").strip()
            address = (
                loc_info.css(".field--name-field-address::text").extract_first() or ""
            ).strip()
        if not name and not address:
            venue = self._parse_location_from_description(response)
            if venue:
                return venue
            # A blank pair means a page with no location or selectors the
            # site's markup has moved past - either way, say so.
            self.logger.warning("No location parsed from %s", response.url)
            return {"name": "TBD", "address": ""}
        return {"name": name, "address": address}

    def _parse_location_from_description(self, response):
        """
        Some events have no location block and name the venue in the description.
        Spiders that know their agency's venues override this; None means unknown.
        """
        return None

    def _parse_links(self, response, start):
        """Parse links from the event page, then add matching documents by date"""
        page_links = []
        page_hrefs = set()
        for field in response.css(".agenda-min-pres .field"):
            label = (field.css(".field__label::text").extract_first() or "").strip()
            for link in field.css("a"):
                href = link.xpath("@href").extract_first()
                title = re.sub(
                    r"\s+", " ", link.xpath("./text()").extract_first() or ""
                )
                if not href:
                    continue
                href = response.urljoin(href)
                # The same file can be attached under two headings; list it once
                if href in page_hrefs:
                    continue
                page_hrefs.add(href)
                page_links.append(
                    {"title": self._link_title(label, title.strip()), "href": href}
                )
        # Copy the date's documents rather than appending to the shared list, so
        # two events on the same day don't collect each other's links
        links = []
        page_titles = {link["title"] for link in page_links}
        for doc in self._date_documents(response, start):
            if doc["href"] in page_hrefs:
                continue
            # The same minutes are often both a document and an event attachment
            if "Minutes" in page_titles and "minutes" in doc["title"].lower():
                continue
            # Title documents like page links ("Agenda", "Minutes")
            links.append(
                {"title": self._link_title("", doc["title"]), "href": doc["href"]}
            )
        return links + page_links

    def _link_title(self, label, title):
        """Call agendas and minutes by their kind; keep other files' own names"""
        if label == "Agendas" or title.startswith("Agenda"):
            return "Agenda"
        # Minutes are sometimes filed under "Documents" ("1292026CPCMinutesfinal.pdf")
        if label == "Minutes" or "minutes" in title.lower():
            return "Minutes"
        return title

    def _date_documents(self, response, start):
        """Documents from the documents pages dated the day of the event"""
        return self.document_date_map.get(start.date(), [])

    def _parse_source(self, response):
        """Parse the event source URL"""
        return response.url

    def _parse_document_links(self, response):
        """Parse document links from the document search results page"""
        document_links = []
        for link in response.css(".view-site-documents .view-content .field-content a"):
            document_links.append(
                {
                    "title": (link.xpath("./text()").extract_first() or "").strip(),
                    "href": response.urljoin(link.xpath("@href").extract_first()),
                }
            )
        return document_links

    def _parse_time_str(self, time_str):
        """Handle parsing a variety of time strings"""
        time_fmt = "%I:%M%p"
        time_str = re.sub(
            r":+",
            ":",
            re.sub(r"\s+", "", re.sub(r"to|from|\.", "", time_str.lower())).replace(
                "o", "0"
            ),
        )
        if ":" not in time_str:
            time_fmt = "%I%p"
        elif len(time_str) < 6:
            time_fmt = "%I%p"
            time_str = time_str.replace(":", "")
        return datetime.strptime(time_str, time_fmt).time()

    def _response_next_url(self, response):
        """Return the next URL for filter results if it's available"""
        return response.css(
            "ul.pagination .pager__item--next a::attr(href)"
        ).extract_first()

    def _create_document_date_map(self):
        """Create a mapping of document dates and documents to match with meetings"""
        self.document_date_map = defaultdict(list)
        for doc_link in self.document_links:
            doc_title = doc_link["title"].strip()
            date_match = self.doc_numeric_date_re.search(doc_title)
            if date_match:
                date_str = date_match.group().replace(" ", "-")
            else:
                date_match = self.doc_month_date_re.search(doc_title)
                if not date_match:
                    continue
                date_str = date_match.group().replace(".", "")
            try:
                # Titles abbreviate months several ways ("Oct", "Sept", "Jan.")
                doc_date = dateutil_parser(date_str).date()
            except (ValueError, OverflowError):
                self.logger.warning(
                    "Could not parse date %r in document title %r", date_str, doc_title
                )
                continue
            self.document_date_map[doc_date].append(doc_link)

    def _replace_agency_doc_param(self, response_url):
        """Replace agency_doc_id and page in query parameters for next_url"""
        scheme, netloc, path, query_string, fragment = parse.urlsplit(response_url)
        query_dict = parse.parse_qs(query_string)
        if self.doc_query_param in query_dict:
            url_agency_doc_id = query_dict[self.doc_query_param][0]
            doc_id_index = self.agency_doc_id.index(url_agency_doc_id)
            if doc_id_index < len(self.agency_doc_id) - 1:
                query_dict[self.doc_query_param] = [
                    self.agency_doc_id[doc_id_index + 1]
                ]
                query_dict.pop("page", None)
                qs = parse.urlencode(query_dict, doseq=True)
                return parse.urlunsplit((scheme, netloc, path, qs, fragment))

    def _on_request_error(self, failure):
        """Log and count a failed request; the run reports it when it closes"""
        self._failed_requests += 1
        self.logger.warning(
            "Request failed: %s (%s)", failure.request.url, repr(failure.value)
        )

    def _on_documents_error(self, failure):
        """
        A failed documents page only loses links, so still request the events.
        Without this, one bad documents page would stop the whole run.
        """
        self._on_request_error(failure)
        yield self._events_request()

    def _count_meeting(self, item, response, spider):
        self._meeting_count += 1

    def spider_closed(self, spider, reason):
        """Report one error for a run with failed requests or no meetings"""
        if self._failed_requests:
            self._report_error(
                DetCitySourceError(
                    "{} request(s) failed; {} meeting(s) parsed".format(
                        self._failed_requests, self._meeting_count
                    )
                )
            )
        elif reason == "finished" and self._meeting_count == 0:
            self._report_error(
                DetCitySourceError("Run finished without parsing any meetings")
            )

    def _report_error(self, exc):
        """Log, count and send the error to Sentry through spider_error"""
        self.logger.error("%s: %s", type(exc).__name__, exc)
        self.crawler.stats.inc_value(
            "spider_exceptions/{}".format(type(exc).__name__), spider=self
        )
        self.crawler.signals.send_catch_log(
            signal=signals.spider_error,
            failure=Failure(exc),
            response=None,
            spider=self,
        )
