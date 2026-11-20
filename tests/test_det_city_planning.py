from datetime import date, datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import CANCELLED, COMMISSION, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.http import HtmlResponse

from city_scrapers.spiders.det_city_planning import DetCityPlanningSpider

FILES = join(dirname(__file__), "files")
EVENT_URL = "https://detroitmi.gov/events/city-planning-commission-meeting-oct-1-2026"
LIST_URL = "https://detroitmi.gov/Calendar-and-Events?field_start_value=2024-11-18&term_node_tid_depth_1=1591"  # noqa
DOCS_URL = "https://detroitmi.gov/documents?field_department_target_id%5B0%5D%5Btarget_id%5D=&field_department_target_id_1%5B0%5D%5Btarget_id%5D=3761"  # noqa
FILE_URL = "https://detroitmi.gov/sites/detroitmi.localhost/files/events/"

# Event pages in the live page's structure, for variants that differ in a few
# lines: the title, the description and whether there is a location block
EVENT_HTML = """
<h1 class="title page-title"><span>{title}</span></h1>
<div class="event-node">
  <section class="event-preview-top">
    <div>
      <article class="date"><time datetime="{date}T12:00:00Z">x</time></article>
    </div>
    <article class="tag-time"><article class="time">
      <span class="fa fa-clock-o" aria-hidden="true"></span>
      <time datetime="{date}T21:00:00Z">{time}</time>
    </article></article>
  </section>
  <section class="desc-contacts">
    <article class="description">{description}</article>
    <article class="extra-info">{location}</article>
  </section>
  <section class="agenda-min-pres">{files}</section>
</div>
"""
LOCATION_HTML = """
<article class="item location"><article class="location teaser clearfix">
  <div class="content"><article class="contact-item"><article class="box">
    <article class="contact-info">
      <span>Committee of the Whole Room</span>
      <br>
      2 Woodward Avenue, Suite 1300 Detroit, MI 48226
    </article>
  </article></article></div>
</article></article>
"""
DOCUMENTS_FIELD_HTML = """
<article class="item"><div class="field field--name-field-documents">
  <div class="field__label">Documents</div>
  <div class="field__items"><div class="field__item"><span class="file">
    <a href="/sites/detroitmi.localhost/files/events/2026-06/{href}">{name}</a>
  </span></div></div>
</div></article>
"""


def event_response(slug, title, description, location="", files="", day="2026-06-04"):
    body = EVENT_HTML.format(
        title=title,
        date=day,
        time="3:00 PM" if "workshop" in slug else "5:00 PM",
        description=description,
        location=location,
        files=files,
    )
    return HtmlResponse(
        url="https://detroitmi.gov/events/" + slug,
        body=body.encode("utf-8"),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def spider():
    with freeze_time("2026-11-18"):
        spider = DetCityPlanningSpider()
        docs = file_response(
            join(FILES, "det_city_planning_documents.html"), url=DOCS_URL
        )
        spider.document_links = spider._parse_document_links(docs)
        spider._create_document_date_map()
        return spider


@pytest.fixture(scope="module")
def item(spider):
    with freeze_time("2026-11-18"):
        response = file_response(join(FILES, "det_city_planning.html"), url=EVENT_URL)
        return spider.parse_event_page(response)


@pytest.fixture(scope="module")
def cancelled_item(spider):
    with freeze_time("2026-11-18"):
        return spider.parse_event_page(
            event_response(
                "city-planning-commission-meeting-september-3-2026-cancelled",
                "City Planning Commission Meeting - September 3, 2026 - CANCELLED",
                "<p>THIS MEETING WAS CANCELLED DUE TO SEVERE WEATHER</p>",
                location=LOCATION_HTML,
                day="2026-09-03",
            )
        )


@pytest.fixture(scope="module")
def june_4_items(spider):
    """The June 4, 2026 meeting and a workshop the same day, both off-site"""
    with freeze_time("2026-11-18"):
        meeting = spider.parse_event_page(
            event_response(
                "city-planning-commission-meeting-june-4-2026",
                "City Planning Commission Meeting - June 4, 2026",
                "<h6><strong>Regular meeting of the City Planning Commission. The "
                "meeting will be held in the Simmons Conference Room, Dauch Scout "
                "Center, 1776 W. Warren Ave., Detroit, Michigan 48208</strong></h6>",
            )
        )
        workshop = spider.parse_event_page(
            event_response(
                "plan-detroit-workshop-city-planning-commission",
                "Plan Detroit Workshop with the City Planning Commission",
                "<p><span>In person: 1776 W. Warren Ave. Dauch Scout Center (Boy "
                "Scouts) Simmons Room</span></p>",
                files=DOCUMENTS_FIELD_HTML.format(
                    href="Workshop%20Boards.pdf", name="Workshop Boards.pdf"
                ),
            )
        )
        return meeting, workshop


def test_start_urls(spider):
    with freeze_time("2026-11-18"):
        assert spider.start_urls == [
            "https://detroitmi.gov/documents?field_department_target_id[0][target_id]=&field_department_target_id_1[0][target_id]=3761"  # noqa
        ]
        # 2 years in the past through all future meetings
        assert spider.get_event_start_url() == LIST_URL


def test_robots_txt_ignored(spider):
    # detroitmi.gov's robots.txt disallows every URL with a query string
    assert spider.custom_settings["ROBOTSTXT_OBEY"] is False


def test_document_date_map(spider):
    # "Oct 1, 2026" crashed the old "%B %d %Y" parsing and stopped the whole run
    assert len(spider.document_links) == 18
    assert sum(len(docs) for docs in spider.document_date_map.values()) == 18
    assert spider.document_date_map[date(2026, 10, 1)] == [
        {
            "title": "City Planning Commission Minutes - Oct 1, 2026",
            "href": "https://detroitmi.gov/document/city-planning-commission-minutes-oct-1-2026",  # noqa
        }
    ]
    for day in [date(2025, 9, 18), date(2026, 1, 29), date(2025, 11, 6)]:
        assert len(spider.document_date_map[day]) == 1


def test_parse_documents_page_continues_to_next_page(spider):
    response = file_response(
        join(FILES, "det_city_planning_documents.html"), url=DOCS_URL
    )
    with freeze_time("2026-11-18"):
        fresh = DetCityPlanningSpider()
        requests = list(fresh.parse_documents_page(response))
    assert len(requests) == 1
    assert "3761" in requests[0].url and "page=1" in requests[0].url
    assert requests[0].errback == fresh._on_documents_error


def test_parse_event_list(spider):
    response = file_response(join(FILES, "det_city_planning_list.html"), url=LIST_URL)
    requests = list(spider.parse_event_list(response))
    event_requests = [r for r in requests if "/events/" in r.url]
    assert len(event_requests) == 10
    assert event_requests[0].url == (
        "https://detroitmi.gov/events/city-planning-commission-meeting-nov-20-2025-cancelled"  # noqa
    )
    assert len(requests) == 11  # and the next calendar page
    assert all(r.errback == spider._on_request_error for r in requests)


def test_title(item):
    assert item["title"] == "City Planning Commission"


def test_description(item):
    assert item["description"] == (
        "Regular meeting of the City Planning Commission. To participate virtually "
        "in the CPC meeting, please use the following options. Online: "
        "https://cityofdetroit.zoom.us/j/96355593579?pwd=TTloMzN5M3pmU1RKNXp1MjJlczN3UT09 "  # noqa
        "Or iPhone one-tap: US: +12678310333,96355593579# or +13017158592,,96355593579# "  # noqa
        "Or by Telephone: Dial (for higher quality, dial a number based on your "
        "current location): US: +1 267 831 0333 or +1 301 715 8592 or +1 312 626 6799 "  # noqa
        "or +1 213 338 8477 or +1 253 215 8782 or +1 346 248 7799 Webinar ID: 963 5559 3579"  # noqa
    )


def test_description_reads_text_outside_tags(spider):
    # Description text not wrapped in a tag is kept, along with tagged text
    with freeze_time("2026-11-18"):
        item = spider.parse_event_page(
            event_response(
                "city-planning-commission-meeting-june-4-2026",
                "City Planning Commission Meeting - June 4, 2026",
                "Regular meeting of the City Planning Commission. "
                "<p>Join online at Zoom.</p>",
                location=LOCATION_HTML,
            )
        )
    assert item["description"] == (
        "Regular meeting of the City Planning Commission. Join online at Zoom."
    )


def test_nested_description_read_once(spider):
    # March 5, 2026: the description pasted from another page nests a second
    # article.description, and its text must not be repeated
    with freeze_time("2026-11-18"):
        item = spider.parse_event_page(
            event_response(
                "city-planning-commission-meeting-march-5-2026",
                "City Planning Commission Meeting - March 5, 2026",
                '<article class="description"><p>Regular meeting of the City '
                "Planning Commission.</p></article>",
                location=LOCATION_HTML,
                day="2026-03-05",
            )
        )
    assert item["description"] == "Regular meeting of the City Planning Commission."


def test_classification(item):
    assert item["classification"] == COMMISSION


def test_start(item):
    assert item["start"] == datetime(2026, 10, 1, 17, 0)


def test_end(item):
    assert item["end"] is None


def test_time_notes(item):
    assert item["time_notes"] == ""


def test_all_day(item):
    assert item["all_day"] is False


def test_id(item):
    assert item["id"] == "det_city_planning/202610011700/x/city_planning_commission"


def test_status(item):
    assert item["status"] == PASSED


def test_location(item):
    # The suite moves from the street address to the room
    assert item["location"] == {
        "name": "Committee of the Whole Room, Suite 1300",
        "address": "2 Woodward Avenue, Detroit, MI 48226",
    }


def test_source(item):
    assert item["source"] == EVENT_URL


def test_links(item):
    # The "Minutes - Oct 1, 2026" document is left out: it is the same minutes
    # as the event page's own Minutes file
    assert item["links"] == [
        {
            "title": "Agenda",
            "href": FILE_URL + "2026-09/10%201%202026%20CPC%20Meeting%20agenda.pdf",
        },
        {
            "title": "Minutes",
            "href": FILE_URL + "2026-10/10%201%202026%20CPC%20Minutes%20final.pdf",
        },
        {
            "title": "PHN 4850 Conner rescheduled.pdf",
            "href": FILE_URL + "2026-09/PHN%204850%20Conner%20rescheduled.pdf",
        },
        {
            "title": "Staff Report - 4850 Conner rezoning 10126.pdf",
            "href": FILE_URL
            + "2026-09/Staff%20Report%20-%204850%20Conner%20rezoning%2010126.pdf",
        },
        {
            "title": "Staff Recommendation - JLG downzone D3.pdf",
            "href": FILE_URL
            + "2026-09/Staff%20Recommendation%20-%20JLG%20downzone%20D3.pdf",
        },
    ]


def test_cancelled(cancelled_item):
    # The title drops "- CANCELLED" but the status still reads it
    assert cancelled_item["title"] == "City Planning Commission"
    assert cancelled_item["status"] == CANCELLED
    assert cancelled_item["start"] == datetime(2026, 9, 3, 17, 0)


def test_venue_from_description(june_4_items):
    for item in june_4_items:
        assert item["location"] == {
            "name": "Simmons Conference Room, Dauch Scout Center",
            "address": "1776 W. Warren Ave., Detroit, MI 48208",
        }


def test_campus_venue_from_description(spider):
    # April 3, 2025: held at WCCCD, named only in the description
    with freeze_time("2026-11-18"):
        item = spider.parse_event_page(
            event_response(
                "city-planning-commission-meeting-april-3-2025",
                "City Planning Commission Meeting - April 3, 2025",
                "<p>Regular meeting of the City Planning Commission. This meeting "
                "will be held at the Wayne County Community College District "
                "Northwest Campus, Denise Wellons-Glover Welcome Center, 2nd "
                "floor, 8200 W. Outer Drive</p>",
                day="2025-04-03",
            )
        )
    assert item["location"] == {
        "name": "Denise Wellons-Glover Welcome Center, 2nd Floor, "
        "Wayne County Community College District Northwest Campus",
        "address": "8200 W. Outer Drive, Detroit, MI 48219",
    }


def test_workshop_same_day_as_meeting(june_4_items):
    meeting, workshop = june_4_items
    assert meeting["title"] == "City Planning Commission"
    assert workshop["title"] == (
        "Plan Detroit Workshop with the City Planning Commission"
    )
    assert workshop["start"] == datetime(2026, 6, 4, 15, 0)
    assert meeting["id"] != workshop["id"]
    # The June 4 minutes document goes to the meeting only
    assert meeting["links"] == [
        {
            "title": "Minutes",
            "href": "https://detroitmi.gov/document/city-planning-commission-minutes-june-4-2026",  # noqa
        }
    ]
    assert workshop["links"] == [
        {
            "title": "Workshop Boards.pdf",
            "href": FILE_URL + "2026-06/Workshop%20Boards.pdf",
        }
    ]


def test_unknown_venue_is_tbd(spider, caplog):
    """
    caplog is pytest's built-in fixture that captures log records, so the test
    can check the spider warns instead of passing over a page with no location.
    """
    with freeze_time("2026-11-18"):
        item = spider.parse_event_page(
            event_response(
                "city-planning-commission-special-meeting",
                "City Planning Commission Special Meeting",
                "<p>Held at a location to be announced.</p>",
            )
        )
    assert item["location"] == {"name": "TBD", "address": ""}
    assert "No location parsed" in caplog.text
