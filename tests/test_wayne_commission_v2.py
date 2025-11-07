"""
Unit tests for Wayne County Commission v2 scraper (Harambe-based orchestrator).
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
    assert result["extras"]["cityscrapers.org/agency"] == AGENCY_NAME


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


@pytest.mark.asyncio
async def test_listing_scraper_with_mock_api():
    """Test listing scraper correctly filters meeting types and calls API"""
    from bs4 import BeautifulSoup

    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    # Load the listing HTML fixture
    fixture_path = Path(__file__).parent / "files" / "wayne_commission_listing.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    detail_urls = []
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()

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

    sdk = ListingSDK(mock_page, detail_urls)

    req_patch = "harambe_scrapers.extractor.wayne_commission.listing.requests.request"
    with patch(req_patch) as mock_request:
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"data": []}

        await listing_scrape(sdk, "https://test.com", {})

        # Verify API was called for both years (current and previous)
        assert mock_request.called
        assert mock_request.call_count == 2

        # Verify the scraper identified the correct meeting types from the HTML
        call_args = mock_request.call_args_list[0][1]["data"]
        # The payload should contain the IDs for the expected meeting types
        # Full Commission or Ways & Means
        assert "1001" in call_args or "1002" in call_args


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
