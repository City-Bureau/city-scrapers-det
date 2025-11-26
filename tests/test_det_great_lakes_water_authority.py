"""
Unit tests for Great Lakes Water Authority scraper (Harambe-based orchestrator).
Tests the three-stage orchestration (category->listing->detail).
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from playwright.async_api import async_playwright

from harambe_scrapers.det_great_lakes_water_authority import (
    AGENCY_NAME,
    TIMEZONE,
    CategorySDK,
    DetailSDK,
    GLWAOrchestrator,
    ListingSDK,
)
from harambe_scrapers.extractor.det_great_lakes_water_authority.listing import (
    scrape as listing_scrape,
)


def get_future_datetime(days_ahead=30):
    """Generate a future datetime for testing"""
    tz = pytz.timezone(TIMEZONE)
    return (datetime.now(tz) + timedelta(days=days_ahead)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )


def get_past_datetime(days_ago=365):
    """Generate a past datetime for testing"""
    tz = pytz.timezone(TIMEZONE)
    return (datetime.now(tz) - timedelta(days=days_ago)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )


@pytest.mark.asyncio
async def test_category_sdk_enqueue():
    """Test CategorySDK URL collection"""
    month_urls = []
    sdk = CategorySDK(None, month_urls)

    current_year = datetime.now().year
    await sdk.enqueue(f"https://www.glwater.org/events/month/{current_year}-01/")
    await sdk.enqueue(f"https://www.glwater.org/events/month/{current_year}-02/")

    assert len(month_urls) == 2
    assert f"{current_year}-01" in month_urls[0]
    assert f"{current_year}-02" in month_urls[1]


@pytest.mark.asyncio
async def test_listing_sdk_enqueue():
    """Test ListingSDK URL collection"""
    event_urls = []
    sdk = ListingSDK(None, event_urls)

    await sdk.enqueue("https://www.glwater.org/event/board-meeting/")
    await sdk.enqueue("https://www.glwater.org/event/committee-meeting/")

    assert len(event_urls) == 2
    assert "board-meeting" in event_urls[0]
    assert "committee-meeting" in event_urls[1]


@pytest.mark.asyncio
async def test_detail_sdk_save_data():
    """Test DetailSDK data storage"""
    sdk = DetailSDK(None)
    test_data = {
        "title": "Board Meeting",
        "start_time": get_future_datetime(days_ahead=30).isoformat(),
        "classification": "BOARD",
    }

    await sdk.save_data(test_data)
    assert sdk.data == test_data


def test_transform_to_ocd_format_with_all_fields():
    """Test transform_to_ocd_format with all fields present"""
    orchestrator = GLWAOrchestrator(headless=True)
    orchestrator.current_url = "https://www.glwater.org/event/test-meeting/"

    future_time = get_future_datetime(days_ahead=60).isoformat()
    end_time = (get_future_datetime(days_ahead=60) + timedelta(hours=2)).isoformat()

    raw_data = {
        "title": "Board of Directors Meeting",
        "start_time": future_time,
        "end_time": end_time,
        "description": "Regular board meeting",
        "classification": "BOARD",
        "location": {"name": "Conference Room", "address": "123 Main St, Detroit, MI"},
        "links": [{"url": "agenda.pdf", "title": "Agenda"}],
        "is_cancelled": False,
        "is_all_day_event": False,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["name"] == "Board of Directors Meeting"
    assert result["classification"] == "BOARD"
    assert result["description"] == "Regular board meeting"
    assert result["status"] == "tentative"
    assert result["all_day"] is False
    assert result["location"]["name"] == "Conference Room"
    assert len(result["links"]) == 1
    assert result["extras"]["cityscrapers.org/agency"] == AGENCY_NAME


def test_transform_to_ocd_format_with_minimal_fields():
    """Test transform_to_ocd_format with minimal fields"""
    orchestrator = GLWAOrchestrator(headless=True)
    orchestrator.current_url = "https://www.glwater.org/event/test/"

    future_time = get_future_datetime(days_ahead=90).isoformat()

    raw_data = {
        "start_time": future_time,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["name"] == "Great Lakes Water Authority Meeting"
    assert result["classification"] is None
    assert result["description"] == ""
    assert result["all_day"] is False
    assert result["location"]["name"] == ""
    assert result["location"]["url"] == ""
    assert result["location"]["coordinates"] is None


def test_transform_to_ocd_format_with_cancelled_meeting():
    """Test transform_to_ocd_format with cancelled meeting"""
    orchestrator = GLWAOrchestrator(headless=True)
    orchestrator.current_url = "https://www.glwater.org/event/cancelled/"

    past_time = get_past_datetime(days_ago=730).isoformat()

    raw_data = {
        "title": "Cancelled Meeting",
        "start_time": past_time,
        "is_cancelled": True,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["status"] == "canceled"
    assert result["name"] == "Cancelled Meeting"


@pytest.mark.asyncio
async def test_run_detail_stage_success():
    """Test run_detail_stage successfully extracts meeting data"""
    orchestrator = GLWAOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()

    test_data = {
        "title": "Test Meeting",
        "start_time": get_future_datetime(days_ahead=30).isoformat(),
    }

    with patch(
        "harambe_scrapers.det_great_lakes_water_authority.detail_scrape"
    ) as mock_detail_scrape:

        async def mock_scrape(sdk, url, context):
            await sdk.save_data(test_data)

        mock_detail_scrape.side_effect = mock_scrape

        result = await orchestrator.run_detail_stage(
            mock_page, "https://www.glwater.org/event/test/"
        )

        assert result == test_data
        assert orchestrator.current_url == "https://www.glwater.org/event/test/"
        mock_page.goto.assert_called_once_with(
            "https://www.glwater.org/event/test/", wait_until="domcontentloaded"
        )


@pytest.mark.asyncio
async def test_run_detail_stage_error():
    """Test run_detail_stage handles errors gracefully"""
    orchestrator = GLWAOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.goto = AsyncMock(side_effect=Exception("Network error"))

    with patch("builtins.print") as mock_print:
        result = await orchestrator.run_detail_stage(
            mock_page, "https://www.glwater.org/event/test/"
        )

        assert result is None
        mock_print.assert_called_once()
        error_msg = str(mock_print.call_args[0][0])
        assert "Error extracting" in error_msg
        assert "Network error" in error_msg


@pytest.fixture
def fixture_html():
    """Load GLWA HTML fixture"""
    parent_dir = Path(__file__).parent
    fixture_path = parent_dir / "files" / "det_great_lakes_water_authority.html"
    with open(fixture_path, "r") as f:
        return f.read()


@pytest.mark.asyncio
async def test_listing_scrape_with_real_html(fixture_html):
    """Integration test using real browser with HTML fixture for listing stage

    This test loads the HTML fixture into a real browser and runs the
    listing scraper against it, ensuring selectors work with real HTML.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(fixture_html)

        event_urls = []
        sdk = ListingSDK(page, event_urls)

        await listing_scrape(sdk, "https://www.glwater.org/events/month/2025-11/", {})

        # Assert exactly 5 events from November 2025 fixture
        assert len(event_urls) == 5, f"Expected 5 events, got {len(event_urls)}"

        # Verify each extracted URL matches actual fixture data
        expected_urls = [
            "https://www.glwater.org/event/operations-and-resources-32/?y=2025",
            "https://www.glwater.org/event/legal-committee-84/?y=2025",
            "https://www.glwater.org/event/board-of-directors-workshop-96/?y=2025",
            "https://www.glwater.org/event/audit-committee-99/?y=2025",
            "https://www.glwater.org/event/special-audit-committee-meeting-13/?y=2025",
        ]

        for expected_url in expected_urls:
            assert expected_url in event_urls, f"Missing expected URL: {expected_url}"

        await browser.close()


@pytest.mark.asyncio
async def test_orchestrator_with_real_html_fixture(fixture_html):
    """End-to-end test with real HTML fixture through orchestrator

    Tests the complete flow from listing to detail extraction
    using real HTML structures.
    """
    orchestrator = GLWAOrchestrator(headless=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(fixture_html)

        event_urls = []
        listing_sdk = ListingSDK(page, event_urls)

        await listing_scrape(
            listing_sdk, "https://www.glwater.org/events/month/2025-11/", {}
        )

        # Assert exactly 5 events from November 2025 fixture
        assert (
            len(event_urls) == 5
        ), f"Should extract 5 event URLs, got {len(event_urls)}"

        # Verify all expected URLs from actual fixture
        base_url = "https://www.glwater.org/event"
        expected_urls = {
            "operations-and-resources-32": (
                f"{base_url}/operations-and-resources-32/?y=2025"
            ),
            "legal-committee-84": f"{base_url}/legal-committee-84/?y=2025",
            "board-of-directors-workshop-96": (
                f"{base_url}/board-of-directors-workshop-96/?y=2025"
            ),
            "audit-committee-99": f"{base_url}/audit-committee-99/?y=2025",
            "special-audit-committee-meeting-13": (
                f"{base_url}/special-audit-committee-meeting-13/?y=2025"
            ),
        }

        for event_key, expected_url in expected_urls.items():
            assert expected_url in event_urls, f"Missing URL for {event_key}"

        # Test OCD transformation for each real event
        # Real event data based on fixture: Operations and Resources on Nov 12
        test_events = [
            {
                "url": expected_urls["operations-and-resources-32"],
                "title": "Operations and Resources",
                "start_time": "2025-11-12T11:00:00-05:00",
                "classification": "COMMITTEE",
            },
            {
                "url": expected_urls["legal-committee-84"],
                "title": "Legal Committee",
                "start_time": "2025-11-20T12:00:00-05:00",
                "classification": "COMMITTEE",
            },
            {
                "url": expected_urls["board-of-directors-workshop-96"],
                "title": "Board of Directors Workshop",
                "start_time": "2025-11-20T13:00:00-05:00",
                "classification": "BOARD",
            },
            {
                "url": expected_urls["audit-committee-99"],
                "title": "Audit Committee",
                "start_time": "2025-11-21T08:00:00-05:00",
                "classification": "COMMITTEE",
            },
            {
                "url": expected_urls["special-audit-committee-meeting-13"],
                "title": "Special Audit Committee Meeting",
                "start_time": "2025-12-03T08:00:00-05:00",
                "classification": "COMMITTEE",
            },
        ]

        for event_data in test_events:
            orchestrator.current_url = event_data["url"]
            ocd_event = orchestrator.transform_to_ocd_format(
                {
                    "title": event_data["title"],
                    "start_time": event_data["start_time"],
                    "classification": event_data["classification"],
                    "location": {
                        "name": "Zoom Telephonic",
                        "address": "Virtual Meeting",
                    },
                }
            )

            assert ocd_event["_type"] == "event"
            assert ocd_event["name"] == event_data["title"]
            assert ocd_event["classification"] == event_data["classification"]
            assert ocd_event["extras"]["cityscrapers.org/agency"] == AGENCY_NAME
            assert ocd_event["sources"][0]["url"] == event_data["url"]

        await browser.close()
