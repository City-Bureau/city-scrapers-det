from datetime import datetime, time
from unittest.mock import MagicMock

import pytest  # noqa
from city_scrapers_core.spiders import CityScrapersSpider
from freezegun import freeze_time
from scrapy import signals
from scrapy.http import HtmlResponse

from city_scrapers.mixins import DetCityMixin
from city_scrapers.mixins.det_city import DetCitySourceError


class MockDetCitySpider(DetCityMixin):
    agency_cal_id = "1000"


def test_start_urls():
    freezer = freeze_time("2019-02-22")
    freezer.start()
    spider = MockDetCitySpider()
    assert "2018-10-25" in spider.start_urls[0]
    assert "1000" in spider.start_urls[0]
    freezer.stop()


def test_parse_title():
    response_mock = MagicMock()
    title_mock = MagicMock()
    title_mock.extract_first.return_value = "Test Meeting 2019-01-01"
    response_mock.css.return_value = title_mock
    spider = MockDetCitySpider()
    assert spider._parse_title(response_mock) == "Test Meeting"


def test_parse_start_end():
    response_mock = MagicMock()
    dt_mock = MagicMock()
    dt_mock.extract_first.return_value = "2019-01-01T10:10:10"
    dt_mock.extract.return_value = ["   \n", " 9:10M - 2:00 p.m."]
    response_mock.css.return_value = dt_mock
    spider = MockDetCitySpider()
    start = datetime(2019, 1, 1, 9, 10)
    assert spider._parse_start(response_mock) == start
    assert spider._parse_end(response_mock, start) == datetime(2019, 1, 1, 14)


def test_parse_time_str():
    spider = MockDetCitySpider()
    assert spider._parse_time_str("from 11:11a.m.") == time(11, 11)
    assert spider._parse_time_str("1pm") == time(13)


def test_create_document_date_map():
    spider = MockDetCitySpider()
    spider.document_links = [
        {"title": "2019 01 01 Test Item", "href": "https://example.com"},
        {"title": "June 1., 2019 Test", "href": "https://example.com"},
    ]
    spider._create_document_date_map()
    assert spider.document_date_map[datetime(2019, 1, 1).date()] == [
        {"title": "2019 01 01 Test Item", "href": "https://example.com"}
    ]
    assert spider.document_date_map[datetime(2019, 6, 1).date()] == [
        {"title": "June 1., 2019 Test", "href": "https://example.com"}
    ]


def test_replace_agency_doc_param():
    spider = MockDetCitySpider()
    spider.agency_doc_id = ["1111", "2222"]
    assert (
        spider._replace_agency_doc_param(
            "https://detroitmi.gov/documents?field_department_target_id_1[0][target_id]=1111&page=2"  # noqa
        )
        == "https://detroitmi.gov/documents?field_department_target_id_1%5B0%5D%5Btarget_id%5D=2222"  # noqa
    )


class MockCalendarSpider(DetCityMixin, CityScrapersSpider):
    name = "mock_det_city"
    agency = "Mock Agency"
    agency_cal_id = "1000"
    agency_doc_id = "2000"


def failure_for(url):
    failure = MagicMock()
    failure.request.url = url
    failure.value = ConnectionRefusedError("refused")
    return failure


def test_create_document_date_map_abbreviated_months(caplog):
    """
    caplog is pytest's built-in fixture that captures log records, so the test
    can check that an unreadable date is logged instead of crashing the run.
    """
    spider = MockCalendarSpider()
    links = [
        {"title": "Minutes - Oct 1, 2026", "href": "https://example.com/1"},
        {"title": "Minutes - Sept 18, 2025", "href": "https://example.com/2"},
        {"title": "Minutes - Jan. 29, 2026", "href": "https://example.com/3"},
        {"title": "Minutes - Nov. 6, 2025 ", "href": "https://example.com/4"},
        {"title": "Minutes - Smarch 40, 2026", "href": "https://example.com/5"},
        {"title": "Minutes without a date", "href": "https://example.com/6"},
    ]
    spider.document_links = links
    spider._create_document_date_map()
    assert dict(spider.document_date_map) == {
        datetime(2026, 10, 1).date(): [links[0]],
        datetime(2025, 9, 18).date(): [links[1]],
        datetime(2026, 1, 29).date(): [links[2]],
        datetime(2025, 11, 6).date(): [links[3]],
    }
    assert "Could not parse date 'Smarch 40, 2026'" in caplog.text


def test_parse_links_does_not_share_date_documents():
    spider = MockCalendarSpider()
    doc = {"title": "Minutes - Oct 1, 2026", "href": "https://example.com/doc"}
    spider.document_date_map[datetime(2026, 10, 1).date()] = [doc]
    body = (
        '<section class="agenda-min-pres"><div class="field">'
        '<div class="field__label">Agendas</div>'
        '<a href="/files/{}.pdf">{} agenda.pdf</a></div></section>'
    )
    start = datetime(2026, 10, 1, 15)
    first = spider._parse_links(
        HtmlResponse(
            "https://detroitmi.gov/events/a",
            body=body.format("a", "a"),
            encoding="utf-8",
        ),
        start,
    )
    second = spider._parse_links(
        HtmlResponse(
            "https://detroitmi.gov/events/b",
            body=body.format("b", "b"),
            encoding="utf-8",
        ),
        start,
    )
    assert first == [
        doc,
        {"title": "Agenda", "href": "https://detroitmi.gov/files/a.pdf"},
    ]
    assert second == [
        doc,
        {"title": "Agenda", "href": "https://detroitmi.gov/files/b.pdf"},
    ]
    assert spider.document_date_map[start.date()] == [doc]


def test_minutes_filed_as_document_skip_duplicate_minutes():
    # Jan 29, 2026: the event page files its minutes under "Documents", and the
    # documents list has the same minutes as a separate page
    spider = MockCalendarSpider()
    doc = {
        "title": "City Planning Commission Minutes - Jan. 29, 2026",
        "href": "https://detroitmi.gov/document/city-planning-commission-minutes-jan-29-2026",  # noqa
    }
    spider.document_date_map[datetime(2026, 1, 29).date()] = [doc]
    body = (
        '<section class="agenda-min-pres"><div class="field">'
        '<div class="field__label">Documents</div>'
        '<a href="/files/1292026CPCMinutesfinal.pdf">1292026CPCMinutesfinal.pdf</a>'
        "</div></section>"
    )
    response = HtmlResponse(
        "https://detroitmi.gov/events/jan-29", body=body, encoding="utf-8"
    )
    assert spider._parse_links(response, datetime(2026, 1, 29, 17)) == [
        {
            "title": "Minutes",
            "href": "https://detroitmi.gov/files/1292026CPCMinutesfinal.pdf",
        }
    ]


def test_parse_event_list_skips_non_event_links(caplog):
    spider = MockCalendarSpider()
    body = (
        '<div class="view-content">'
        '<div class="article-title"><a href="/events/district-4-meeting">x</a></div>'
        '<div class="article-title"><a href="/cdn-cgi/l/email-protection">y</a></div>'
        "</div>"
    )
    response = HtmlResponse(
        "https://detroitmi.gov/Calendar-and-Events?x=1", body=body, encoding="utf-8"
    )
    requests = list(spider.parse_event_list(response))
    assert [r.url for r in requests] == [
        "https://detroitmi.gov/events/district-4-meeting"
    ]
    assert "Skipped non-event link" in caplog.text


def test_start_requests_have_errbacks():
    spider = MockCalendarSpider()
    requests = list(spider.start_requests())
    assert len(requests) == 1
    assert "/documents?" in requests[0].url
    assert requests[0].errback == spider._on_documents_error


def test_failed_documents_page_still_requests_events():
    with freeze_time("2026-11-18"):
        spider = MockCalendarSpider()
        requests = list(
            spider._on_documents_error(
                failure_for("https://detroitmi.gov/documents?x=1")
            )
        )
    assert spider._failed_requests == 1
    assert len(requests) == 1
    assert "Calendar-and-Events" in requests[0].url
    assert requests[0].errback == spider._on_request_error


def make_crawled_spider():
    crawler = MagicMock()
    with freeze_time("2026-11-18"):
        spider = MockCalendarSpider.from_crawler(crawler)
    return spider, crawler


def test_from_crawler_connects_signals():
    spider, crawler = make_crawled_spider()
    connected = {
        call.kwargs["signal"]: call.args[0]
        for call in crawler.signals.connect.call_args_list
        if "signal" in call.kwargs
    }
    assert connected[signals.spider_closed] == spider.spider_closed
    assert connected[signals.item_scraped] == spider._count_meeting


def spider_errors(crawler):
    return [
        call
        for call in crawler.signals.send_catch_log.call_args_list
        if call.kwargs.get("signal") == signals.spider_error
    ]


def test_blocked_run_reports_one_error():
    spider, crawler = make_crawled_spider()
    spider._on_request_error(
        failure_for("https://detroitmi.gov/Calendar-and-Events?a=1")
    )
    spider._on_request_error(failure_for("https://detroitmi.gov/events/b"))
    spider.spider_closed(spider, "finished")
    errors = spider_errors(crawler)
    assert len(errors) == 1
    assert isinstance(errors[0].kwargs["failure"].value, DetCitySourceError)
    crawler.stats.inc_value.assert_called_once_with(
        "spider_exceptions/DetCitySourceError", spider=spider
    )


def test_empty_run_reports_one_error():
    spider, crawler = make_crawled_spider()
    spider.spider_closed(spider, "finished")
    assert len(spider_errors(crawler)) == 1


def test_good_run_reports_no_error():
    spider, crawler = make_crawled_spider()
    spider._count_meeting(item={}, response=None, spider=spider)
    spider.spider_closed(spider, "finished")
    assert spider_errors(crawler) == []
