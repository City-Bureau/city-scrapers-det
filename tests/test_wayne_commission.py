"""
Unit tests for Wayne County Commission scraper (Harambe-based orchestrator).
Tests the two-stage orchestration (listing->detail).
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from harambe_scrapers.wayne_commission import (
    AGENCY_NAME,
    TIMEZONE,
    DetailSDK,
    ListingSDK,
    WayneCommissionOrchestrator,
)


def get_future_datetime(days_ahead=30):
    """Generate a future datetime for testing"""
    tz = pytz.timezone(TIMEZONE)
    return (datetime.now(tz) + timedelta(days=days_ahead)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )


def test_transform_to_ocd_format_with_all_fields():
    """Test transform_to_ocd_format with complete meeting data"""
    orchestrator = WayneCommissionOrchestrator(headless=True)
    orchestrator.current_url = (
        "https://www.waynecountymi.gov/Government/Elected-Officials/test"
    )

    future_time = get_future_datetime(days_ahead=60).isoformat()
    end_time = (get_future_datetime(days_ahead=60) + timedelta(hours=2)).isoformat()

    raw_data = {
        "title": "Ways & Means Committee",
        "start_time": future_time,
        "end_time": end_time,
        "description": "Regular committee meeting",
        "classification": "COMMITTEE",
        "location": {
            "name": "Conference Room",
            "address": "500 Griswold St, Detroit, MI",
        },
        "links": [{"url": "agenda.pdf", "title": "Agenda"}],
        "is_cancelled": False,
        "is_all_day_event": False,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["name"] == "Ways & Means Committee"
    assert result["classification"] == "COMMITTEE"
    assert result["description"] == "Regular committee meeting"
    assert result["status"] == "tentative"
    assert result["all_day"] is False
    assert result["location"]["name"] == "Conference Room"
    assert len(result["links"]) == 1
    assert result["extras"]["cityscrapers/agency"] == AGENCY_NAME


def test_transform_to_ocd_format_with_cancelled_meeting():
    """Test transform_to_ocd_format correctly handles cancelled meetings"""
    orchestrator = WayneCommissionOrchestrator(headless=True)
    orchestrator.current_url = "https://www.waynecountymi.gov/cancelled"

    past_time = (datetime.now() - timedelta(days=30)).isoformat()

    raw_data = {
        "title": "Cancelled Committee Meeting",
        "start_time": past_time,
        "is_cancelled": True,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["status"] == "canceled"
    assert result["name"] == "Cancelled Committee Meeting"


@pytest.mark.asyncio
async def test_run_listing_stage():
    """Test run_listing_stage collects meeting URLs properly"""
    orchestrator = WayneCommissionOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.set_default_timeout = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.query_selector_all = AsyncMock(return_value=[])

    with patch("harambe_scrapers.wayne_commission.listing_scrape") as mock_listing:

        async def mock_scrape(sdk, url, context):
            await sdk.enqueue("https://meeting1.com", {"isCancelled": "False"})
            await sdk.enqueue("https://meeting2.com", {"isCancelled": "False"})

        mock_listing.side_effect = mock_scrape

        await orchestrator.run_listing_stage(mock_page)

        assert len(orchestrator.detail_urls) == 2
        assert orchestrator.detail_urls[0]["url"] == "https://meeting1.com"


@pytest.mark.asyncio
async def test_orchestrator_with_limit():
    """Test that the orchestrator respects the limit_meetings parameter"""
    orchestrator = WayneCommissionOrchestrator(headless=True, limit_meetings=3)

    orchestrator.detail_urls = [
        {"url": f"https://test{i}.com", "context": {"isCancelled": "False"}}
        for i in range(10)
    ]

    with patch.object(orchestrator, "run_listing_stage") as mock_listing:
        mock_listing.return_value = None

        with patch.object(orchestrator, "run_detail_stage") as mock_detail:
            mock_detail.return_value = {
                "title": "Test",
                "start_time": datetime.now().isoformat(),
            }

            with patch.object(orchestrator.observer, "on_save_data") as mock_save:
                mock_save.return_value = None

                pw_patch = "harambe_scrapers.wayne_commission.async_playwright"
                with patch(pw_patch) as mock_pw:
                    mock_browser = AsyncMock()
                    mock_context = AsyncMock()
                    mock_page = AsyncMock()

                    mock_chromium = (
                        mock_pw.return_value.__aenter__.return_value.chromium
                    )
                    mock_chromium.launch.return_value = mock_browser
                    mock_browser.new_context.return_value = mock_context
                    mock_context.new_page.return_value = mock_page
                    mock_browser.close = AsyncMock()

                    await orchestrator.run()

                    assert mock_detail.call_count == 3


def _build_listing_page(monkeypatch=None):
    """Build a mock Playwright page that mimics the calendar listing page.

    The page reports a live ASP.NET_SessionId cookie and a real user-agent so
    the listing scraper can build its request headers from a live session.
    """
    from bs4 import BeautifulSoup

    fixture_path = Path(__file__).parent / "files" / "wayne_commission_listing.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()

    # Live session: cookies + user-agent come from the browser context.
    mock_context = MagicMock()
    mock_context.cookies = AsyncMock(
        return_value=[{"name": "ASP.NET_SessionId", "value": "live-session-xyz"}]
    )
    mock_page.context = mock_context
    mock_page.evaluate = AsyncMock(return_value="TestBrowser/1.0")

    # Create mock elements for each filter item
    mock_elements = []
    filter_items = soup.select(".calendar-filter-list-item")
    for item in filter_items:
        mock_elem = MagicMock()
        mock_elem.get_attribute = AsyncMock(
            return_value=item.get("data-filter-option-id")
        )

        text_elem = item.select_one(".calendar-filter-list-item-text")
        mock_text = MagicMock()
        mock_text.inner_text = AsyncMock(return_value=text_elem.get_text(strip=True))
        mock_elem.query_selector = AsyncMock(return_value=mock_text)

        mock_elements.append(mock_elem)

    mock_page.query_selector_all = AsyncMock(return_value=mock_elements)
    return mock_page


def _make_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = str(payload)
    return resp


@pytest.mark.asyncio
async def test_listing_scraper_uses_live_session_and_enqueues():
    """Listing scraper builds headers from a live session and enqueues meetings.

    Verifies the fix for the stale-cookie bug: the request must carry the
    live ASP.NET_SessionId pulled from the page (not the old hardcoded one)
    and must NOT carry the frozen Oracle APM trace headers.
    """
    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    detail_urls = []
    mock_page = _build_listing_page()
    sdk = ListingSDK(mock_page, detail_urls)

    def request_side_effect(method, url, **kwargs):
        if "getcalendaritems" in url:
            return _make_response(
                {
                    "data": [
                        {
                            "Items": [
                                {
                                    "CalendarId": 1,
                                    "Id": 2,
                                    "MainContentId": 3,
                                    "DateTime": "2026-05-01",
                                }
                            ]
                        }
                    ]
                }
            )
        return _make_response(
            {
                "data": {
                    "Link": "https://www.waynecountymi.gov/meeting-x",
                    "IsCancelled": False,
                }
            }
        )

    req_patch = "harambe_scrapers.extractor.wayne_commission.listing.requests.request"
    with patch(req_patch) as mock_request:
        mock_request.side_effect = request_side_effect

        await listing_scrape(sdk, "https://test.com", {})

        # Meetings were enqueued (one per year → both years processed)
        assert len(detail_urls) == 2
        assert detail_urls[0]["url"] == "https://www.waynecountymi.gov/meeting-x"

        # The calendar API was called once per year with the fixture IDs
        calendar_calls = [
            c for c in mock_request.call_args_list if "getcalendaritems" in c[0][1]
        ]
        assert len(calendar_calls) == 2
        payload = calendar_calls[0][1]["data"]
        assert "1001" in payload or "1002" in payload

        # Headers must use the LIVE session cookie, not the old hardcoded one,
        # and must have dropped the frozen APM trace headers.
        headers = calendar_calls[0][1]["headers"]
        assert headers["Cookie"] == "ASP.NET_SessionId=live-session-xyz"
        assert "h4ooyutzz33houczonxywo0h" not in headers["Cookie"]
        assert headers["user-agent"] == "TestBrowser/1.0"
        assert "x-b3-traceid" not in headers
        assert "x-b3-spanid" not in headers
        assert "x-oracle-apm-ba-version" not in headers


@pytest.mark.asyncio
async def test_listing_scraper_raises_on_zero_results():
    """A run that enqueues nothing must fail loudly instead of silently."""
    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    detail_urls = []
    mock_page = _build_listing_page()
    sdk = ListingSDK(mock_page, detail_urls)

    req_patch = "harambe_scrapers.extractor.wayne_commission.listing.requests.request"
    with patch(req_patch) as mock_request:
        # Calendar API responds but returns no meetings for every year.
        mock_request.return_value = _make_response({"data": []})

        with pytest.raises(RuntimeError, match="Enqueued 0 meetings"):
            await listing_scrape(sdk, "https://test.com", {})

        # It still attempted both years before giving up.
        assert mock_request.call_count == 2


@pytest.mark.asyncio
async def test_listing_scraper_raises_when_no_filters_found():
    """No meeting-type filters (changed markup) must fail loudly."""
    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    detail_urls = []
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.query_selector_all = AsyncMock(return_value=[])

    sdk = ListingSDK(mock_page, detail_urls)

    req_patch = "harambe_scrapers.extractor.wayne_commission.listing.requests.request"
    with patch(req_patch) as mock_request:
        with pytest.raises(RuntimeError, match="No meeting-type filters"):
            await listing_scrape(sdk, "https://test.com", {})

        # Aborts before making any API calls.
        assert mock_request.call_count == 0


@pytest.mark.asyncio
async def test_detail_scraper_with_html_fixture():
    """Test detail scraper extracts all data correctly from real HTML fixture"""
    from bs4 import BeautifulSoup

    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    fixture_path = Path(__file__).parent / "files" / "wayne_commission.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    mock_page = MagicMock()
    mock_page.wait_for_selector = AsyncMock()

    def create_element_mock(element):
        if element is None:
            return None
        mock_elem = MagicMock()
        text = (
            element.get_text(strip=True)
            if hasattr(element, "get_text")
            else str(element)
        )
        mock_elem.inner_text = AsyncMock(return_value=text)
        if element.name == "a" and element.get("href"):
            mock_elem.get_attribute = AsyncMock(return_value=element.get("href"))
        return mock_elem

    async def mock_query_selector(selector):
        element = soup.select_one(selector)
        return create_element_mock(element)

    async def mock_query_selector_all(selector):
        elements = soup.select(selector)
        mock_elements = []
        for elem in elements:
            mock_elem = MagicMock()
            if "meeting-document" in selector:
                title_elem = elem.select_one(".meeting-document-title")
                link_elem = elem.select_one("a")

                def make_query_selector(title_el, link_el):
                    async def query_doc_element(s):
                        if "title" in s and title_el:
                            return create_element_mock(title_el)
                        elif "a" in s and link_el:
                            return create_element_mock(link_el)
                        return None

                    return query_doc_element

                mock_elem.query_selector = AsyncMock(
                    side_effect=make_query_selector(title_elem, link_elem)
                )
            else:
                mock_elem = create_element_mock(elem)

            mock_elements.append(mock_elem)
        return mock_elements

    mock_page.query_selector = AsyncMock(side_effect=mock_query_selector)
    mock_page.query_selector_all = AsyncMock(side_effect=mock_query_selector_all)

    sdk = DetailSDK(mock_page)
    context = {"isCancelled": "False"}

    await detail_scrape(sdk, "https://test.com", context)

    assert sdk.data is not None
    assert sdk.data["title"] == "Full Commission - February 1, 2024"
    assert sdk.data["description"] == "Standard Meeting"
    assert sdk.data["classification"] == "COMMISION"  # Note: typo in original code

    assert "2024-02-01T10:00:00" in sdk.data["start_time"]
    assert "2024-02-01T12:00:00" in sdk.data["end_time"]

    # The scraper gets the last p tag in meeting-address and splits by first comma
    assert sdk.data["location"]["name"] == "Commission Chambers"
    assert (
        "Mezzanine, Guardian Building, 500 Griswold, Detroit, MI, 48226"
        in sdk.data["location"]["address"]
    )

    assert len(sdk.data["links"]) >= 3
    link_titles = [link["title"] for link in sdk.data["links"]]
    assert "Full Commission Agenda - Feb 1, 2024" in link_titles
    # Video links are filtered out (youtube)
    assert "Full Commission Journal - Feb 1, 2024" in link_titles
    assert "Zoom Meeting Link" in link_titles

    # Check that non-Zoom links have proper Wayne County URLs
    for link in sdk.data["links"]:
        if "zoom" not in link["url"].lower():
            assert link["url"].startswith("https://www.waynecountymi.gov")

    assert sdk.data["is_cancelled"] is None  # False context means None in the code


@pytest.mark.asyncio
async def test_detail_scraper_raises_when_no_layout_matches():
    """Detail scraper must raise (not silently return) when the DOM changed.

    Previously a TimeoutError on both the standard and fallback layouts caused
    a bare `return`, silently dropping the meeting. It should now surface the
    failure so a broken page is visible in the logs.
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    mock_page = MagicMock()

    async def wait_for_selector(selector, *args, **kwargs):
        # The outer container loads fine, but neither the standard
        # (minutes-date) nor the fallback (.small-text) layout is present.
        if selector == "div.main-inner-container":
            return None
        raise PlaywrightTimeoutError("timeout")

    mock_page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)

    title_elem = MagicMock()
    title_elem.inner_text = AsyncMock(return_value="Some Meeting")
    mock_page.query_selector = AsyncMock(return_value=title_elem)

    sdk = DetailSDK(mock_page)

    with pytest.raises(RuntimeError, match="Could not extract meeting details"):
        await detail_scrape(sdk, "https://test.com/broken", {"isCancelled": "False"})

    assert sdk.data is None
