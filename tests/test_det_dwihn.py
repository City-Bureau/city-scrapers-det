import logging
from datetime import datetime
from os.path import dirname, exists, join

import pytest
from city_scrapers_core.constants import (
    ADVISORY_COMMITTEE,
    BOARD,
    CANCELLED,
    COMMITTEE,
    FORUM,
    NOT_CLASSIFIED,
    PASSED,
    TENTATIVE,
)
from city_scrapers_core.items import Meeting
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy import Request
from twisted.python.failure import Failure

from city_scrapers.spiders.det_dwihn import DetDwihnSpider

FILES_DIR = join(dirname(__file__), "files")
FROZEN_DATE = "2026-09-30"
EVENT_URL = "https://dwihn.org/events/{}"
MEDIA_URL = "https://dwihn.org/media/document/{}"
VIDEO_LINK = {
    "title": "YouTube channel",
    "href": "https://www.youtube.com/channel/UCnIswzB1YZzx0BgnsUFZKcg",
}
# Saved event detail pages, by the slug of their URL
EVENT_FILES = {
    "full-board": "det_dwihn_detail_zoom.html",
    "full-board-directors-meeting-0": "det_dwihn_detail_media.html",
    "full-board-directors-annual-meeting": "det_dwihn_detail_annual.html",
    "policy-bylaw-committee-meeting-cancelled": "det_dwihn_detail_cancelled.html",
    "full-board-directors-meeting-6": "det_dwihn.html",
    "rescheduled-ad-hoc-policy-committee-meeting": "det_dwihn_detail_rescheduled.html",  # noqa
    "ad-hoc-policy-committee-meeting-new-date": "det_dwihn_detail_new_date.html",
}


def listing_response(spider):
    return file_response(
        join(FILES_DIR, "det_dwihn_listing.html"), url=spider.start_urls[0]
    )


def event_response(slug):
    return file_response(join(FILES_DIR, EVENT_FILES[slug]), url=EVENT_URL.format(slug))


def media_file(url):
    """Saved media pages are named after the slug of their URL"""
    path = join(FILES_DIR, "det_dwihn_media_{}.html".format(url.split("/")[-1]))
    return path if exists(path) else None


def run_callbacks(spider, results):
    """Follow media page requests the way Scrapy would.

    Requests for saved media pages are answered with that page, others go
    through the errback as a media page that failed to load.
    """
    items = []
    pending = list(results)
    while pending:
        result = pending.pop(0)
        if not isinstance(result, Request):
            items.append(result)
            continue
        path = media_file(result.url)
        if path:
            response = file_response(path, url=result.url)
            pending.extend(result.callback(response, **result.cb_kwargs))
        else:
            failure = Failure(Exception("404 Not Found"))
            failure.request = result
            pending.extend(result.errback(failure))
    return items


def parse_items(spider, slugs=tuple(EVENT_FILES)):
    items = []
    with freeze_time(FROZEN_DATE):
        for slug in slugs:
            items.extend(
                run_callbacks(spider, spider.parse_event(event_response(slug)))
            )
    return sorted(items, key=lambda i: (i["start"], i["title"]))


def find_item(items, start):
    return next(i for i in items if i["start"] == start)


@pytest.fixture
def spider():
    return DetDwihnSpider()


@pytest.fixture(scope="module")
def parsed_items():
    return parse_items(DetDwihnSpider())


@pytest.fixture(scope="module")
def board_item(parsed_items):
    """Full board meeting with its documents linked directly"""
    return find_item(parsed_items, datetime(2026, 9, 16, 12))


@pytest.fixture(scope="module")
def zoom_item(parsed_items):
    """Older event page with the Zoom details written out"""
    return find_item(parsed_items, datetime(2025, 11, 19, 13))


@pytest.fixture(scope="module")
def media_item(parsed_items):
    """Event whose documents are linked through media pages"""
    return find_item(parsed_items, datetime(2026, 2, 18, 13))


@pytest.fixture(scope="module")
def annual_item(parsed_items):
    """Annual meeting held away from the admin building"""
    return find_item(parsed_items, datetime(2026, 6, 17, 11))


@pytest.fixture(scope="module")
def cancelled_item(parsed_items):
    """Cancelled meeting posted as all day, time is in the body text"""
    return find_item(parsed_items, datetime(2026, 9, 9, 15, 10))


@pytest.fixture(scope="module")
def rescheduled_item(parsed_items):
    """Meeting moved away from this date"""
    return find_item(parsed_items, datetime(2026, 9, 16, 14, 15))


@pytest.fixture(scope="module")
def new_date_item(parsed_items):
    """Meeting moved to this date"""
    return find_item(parsed_items, datetime(2026, 10, 21, 14, 15))


def test_count(parsed_items):
    assert len(parsed_items) == 7


def test_listing_requests(spider):
    results = list(spider.parse(listing_response(spider)))
    event_requests = [r for r in results if r.callback == spider.parse_event]
    assert len(event_requests) == 12
    assert event_requests[0].url == EVENT_URL.format("sud-oversight-policy-board")


def test_listing_pagination(spider):
    results = list(spider.parse(listing_response(spider)))
    next_pages = [r for r in results if r.callback == spider.parse]
    assert [r.url for r in next_pages] == [
        "https://dwihn.org/news-events/events"
        "?field_categories_target_id=14&event_time=All&page=1"
    ]


def test_empty_listing_is_logged(spider, caplog):
    response = listing_response(spider).replace(body=b"")
    with caplog.at_level(logging.WARNING):
        assert list(spider.parse(response)) == []
    assert "No events found on the listing page" in caplog.text


def test_title(parsed_items, board_item, cancelled_item, rescheduled_item):
    assert board_item["title"] == "Full Board of Directors Meeting"
    # Cancellation and date change markers are removed
    assert cancelled_item["title"] == "Policy / Bylaw Committee Meeting"
    assert rescheduled_item["title"] == "(Ad HOC) Policy Committee Meeting"
    assert [i["title"] for i in parsed_items] == [
        "Full Board of Directors Meeting",
        "Full Board of Directors Meeting",
        "Full Board of Directors ANNUAL Meeting",
        "Policy / Bylaw Committee Meeting",
        "Full Board of Directors Meeting",
        "(Ad HOC) Policy Committee Meeting",
        "(Ad HOC) Policy Committee Meeting",
    ]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "Program Compliance Committee (PCC)",
            "Program Compliance Committee (PCC) Meeting",
        ),  # noqa
        (
            "Program Compliance Committee Meeting",
            "Program Compliance Committee (PCC) Meeting",
        ),  # noqa
        ("Policy/Bylaw Committee", "Policy / Bylaw Committee Meeting"),
        (
            "Policy / Bylaw Committee Meeting - CANCELLED",
            "Policy / Bylaw Committee Meeting",
        ),  # noqa
        ("Budget Hearing", "Budget Hearing"),
        ("Finance Committee ", "Finance Committee Meeting"),
        ("Full Board", "Full Board of Directors Meeting"),
        (
            "Board Executive Committee Meeting - *New Date",
            "Board Executive Committee Meeting",
        ),  # noqa
        ("SUD Oversight Policy Board", "SUD Oversight Policy Board Meeting"),
        (
            "Board Building AD-HOC Committee-CANCELLED",
            "Board Building AD-HOC Committee Meeting",
        ),  # noqa
        (
            "Board Building Ad-HOC Committee Meeting",
            "Board Building AD-HOC Committee Meeting",
        ),  # noqa
        (
            "*RESCHEDULED: (Ad HOC) Policy Committee Meeting",
            "(Ad HOC) Policy Committee Meeting",
        ),  # noqa
        (
            "Recipient Rights Advisory Committee Meeting - New Time",
            "Recipient Rights Advisory Committee Meeting",
        ),  # noqa
    ],
)
def test_parse_title(spider, raw, expected):
    assert spider._parse_title(raw) == expected


def test_description(board_item, zoom_item, cancelled_item):
    """Online attendance details go in the description"""
    assert board_item["description"] == (
        'Virtual login details are available in the "Virtual Login / '
        'Good & Welfare Registration" link.'
    )
    assert zoom_item["description"] == (
        "PLEASE FEEL FREE TO JOIN BY DIALING IN AT: 1.833.548.0282 MEETING ID: "
        "985 1251 8872 OR JOIN BY COMPUTER - ZOOM please click on the link below, "
        "or copy and paste it into your browser) "
        "https://dwihn-org.zoom.us/j/98512518872"
    )
    assert cancelled_item["description"] == ""


def test_no_attendance_links(parsed_items):
    """Zoom links are in the description rather than links"""
    assert all(
        "zoom.us" not in link["href"] for i in parsed_items for link in i["links"]
    )


def test_start(parsed_items, cancelled_item):
    assert parsed_items[0]["start"] == datetime(2025, 11, 19, 13)
    # Posted as all day, the time is taken from the body text
    assert cancelled_item["start"] == datetime(2026, 9, 9, 15, 10)


def test_end(board_item, cancelled_item):
    assert board_item["end"] == datetime(2026, 9, 16, 14)
    assert cancelled_item["end"] is None


def test_missing_end_is_logged(spider, caplog):
    with caplog.at_level(logging.WARNING):
        parse_items(spider, slugs=["policy-bylaw-committee-meeting-cancelled"])
    assert "No end time found" in caplog.text


def test_missing_times_are_logged(spider, caplog):
    response = event_response("full-board-directors-meeting-6")
    response = response.replace(body=response.body.replace(b"<time", b"<span"))
    with caplog.at_level(logging.WARNING):
        assert list(spider.parse_event(response)) == []
    assert "No event times found" in caplog.text
    assert "Could not parse the title or start of the event" in caplog.text


def test_time_notes(parsed_items):
    assert all(item["time_notes"] == "" for item in parsed_items)


def test_id(board_item):
    assert (
        board_item["id"] == "det_dwihn/202609161200/x/full_board_of_directors_meeting"
    )


def test_status(board_item, cancelled_item, rescheduled_item, new_date_item):
    assert board_item["status"] == PASSED
    assert cancelled_item["status"] == CANCELLED
    # Moved away from this date
    assert rescheduled_item["status"] == CANCELLED
    # "Rescheduled to be held on" this meeting's own date
    assert new_date_item["status"] == TENTATIVE


def test_location(board_item, annual_item, spider):
    assert board_item["location"] == spider.common_location
    assert annual_item["location"] == {
        "name": "Wayne County Community College District Northwest Campus",
        "address": "8200 W. Outer Drive, Detroit MI 48219",
    }


def test_missing_location_is_logged(spider, caplog):
    response = event_response("full-board-directors-meeting-6")
    response = response.replace(
        body=response.body.replace(
            b"DWIHN (Admin Building), 8726 Woodward Ave", b""
        ).replace(b", Detroit MI 48202</span>", b"</span>")
    )
    with caplog.at_level(logging.WARNING):
        meeting = run_callbacks(spider, spider.parse_event(response))[0]
    assert meeting["location"] == spider.common_location
    assert "No location found" in caplog.text


def test_source(board_item):
    assert board_item["source"] == EVENT_URL.format("full-board-directors-meeting-6")


def test_links(board_item, zoom_item, cancelled_item):
    # Links on the backend host point at the public site
    assert board_item["links"] == [
        {
            "title": "Virtual Login / Good & Welfare Registration",
            "href": "https://dwihn.org/sites/default/files/2026-08/Full_Board_Meeting_OMA_Posting_-_September_16%2C_2026Post.pdf",  # noqa
        },
        {
            "title": "Agenda",
            "href": "https://dwihn.org/sites/default/files/2026-09/Full_Board_Agenda_-_September_16%2C_2026BE.pdf",  # noqa
        },
        VIDEO_LINK,
    ]
    assert zoom_item["links"] == [
        {
            "title": "Good & Welfare Registration",
            "href": "https://dwmha.az1.qualtrics.com/jfe/form/SV_bgwPD3uvQr2euHP",
        },
        VIDEO_LINK,
    ]
    assert cancelled_item["links"] == [
        {
            "title": "Cancellation Notice",
            "href": "https://dwihn.org/sites/default/files/2026-09/Cancelled_Policy_Bylaw_Committee_Meeting_Wednesday%2C_September_9%2C_2026PostV.2.pdf",  # noqa
        },
        VIDEO_LINK,
    ]


def test_media_page_links(media_item, annual_item):
    """Media pages are followed to the document they offer for download"""
    assert media_item["links"] == [
        {
            "title": "Login / Good & Welfare Registration",
            "href": "https://dwihn.org/sites/default/files/2026-01/Full_Board__Meeting_OMA_Posting_-_February_18%2C_2026Post.pdf",  # noqa
        },
        {
            "title": "Agenda",
            "href": "https://dwihn.org/sites/default/files/2026-02/Full_Board_Agenda_-_February_18%2C_2026Post.pdf",  # noqa
        },
        VIDEO_LINK,
    ]
    assert annual_item["links"] == [
        {
            "title": "Virtual Login / Good & Welfare Registration",
            "href": "https://dwihn.org/sites/default/files/2026-06/Full_Board_ANNUAL_Meeting_OMA_Posting_-_June_17%2C_2026Post._docx.pdf",  # noqa
        },
        {
            "title": "Agenda",
            "href": "https://dwihn.org/sites/default/files/2026-06/Full_Board_Agenda_-_June_17%2C_2026BE.pdf",  # noqa
        },
        VIDEO_LINK,
    ]


def test_media_page_error_keeps_link(spider, caplog):
    request = next(spider.parse_event(event_response("full-board-directors-meeting-0")))
    failure = Failure(Exception("timed out"))
    failure.request = request
    with caplog.at_level(logging.WARNING):
        results = list(spider._media_page_failed(failure))
    # Moves on to the next media page, keeping the one that failed as it is
    assert [r.url for r in results] == [
        MEDIA_URL.format("full-board-meeting-agenda-february-16-2026")
    ]
    assert request.cb_kwargs["meeting"]["links"][0]["href"] == MEDIA_URL.format(
        "full-board-meeting-feb-18-2026-oma"
    )
    assert "Could not fetch the media page" in caplog.text


def test_media_page_without_document_is_logged(spider, caplog):
    request = next(spider.parse_event(event_response("full-board-directors-meeting-0")))
    response = event_response("full-board").replace(url=request.url)
    with caplog.at_level(logging.WARNING):
        next(request.callback(response, **request.cb_kwargs))
    assert "No document found on the media page" in caplog.text


def test_classification(parsed_items, board_item, cancelled_item, spider):
    assert board_item["classification"] == BOARD
    assert cancelled_item["classification"] == COMMITTEE
    assert spider._parse_classification("Budget Hearing") == FORUM
    assert (
        spider._parse_classification("Recipient Rights Advisory Committee")
        == ADVISORY_COMMITTEE
    )
    assert spider._parse_classification("Board Study Session") == BOARD
    assert spider._parse_classification("Town Hall") == NOT_CLASSIFIED


def test_all_day(parsed_items):
    assert all(item["all_day"] is False for item in parsed_items)


def test_video_link(parsed_items):
    assert all(item["links"][-1] == VIDEO_LINK for item in parsed_items)


def test_items_are_meetings(parsed_items):
    assert all(isinstance(item, Meeting) for item in parsed_items)
