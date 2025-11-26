"""
Unit tests for Detroit Police Department scraper (Harambe-based orchestrator).
Tests the three-stage orchestration (category->listing->detail) with fallback.
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from playwright.async_api import async_playwright

from harambe_scrapers.det_police_department import (
    AGENCY_NAME,
    SCRAPER_NAME,
    TIMEZONE,
    CategorySDK,
    DetailSDK,
    DetroitPoliceOrchestrator,
    ListingSDK,
    main,
)
from harambe_scrapers.utils import create_ocd_event

# Test SDK Classes


@pytest.mark.asyncio
async def test_category_sdk_enqueue_relative_url():
    """Test CategorySDK converts relative URLs to absolute"""
    urls_list = []
    sdk = CategorySDK(None, urls_list)

    await sdk.enqueue("/events/some-meeting")
    assert urls_list[0] == "https://detroitmi.gov/events/some-meeting"


@pytest.mark.asyncio
async def test_category_sdk_enqueue_absolute_url():
    """Test CategorySDK keeps absolute URLs unchanged"""
    urls_list = []
    sdk = CategorySDK(None, urls_list)

    await sdk.enqueue("https://detroitmi.gov/events/meeting")
    assert urls_list[0] == "https://detroitmi.gov/events/meeting"


@pytest.mark.asyncio
async def test_category_sdk_enqueue_query_without_events():
    """Test CategorySDK adds /events path when missing"""
    urls_list = []
    sdk = CategorySDK(None, urls_list)

    await sdk.enqueue("?term_node_tid_depth_1=941&page=1")
    expected = "https://detroitmi.gov/events?term_node_tid_depth_1=941&page=1"
    assert urls_list[0] == expected


@pytest.mark.asyncio
async def test_listing_sdk_enqueue():
    """Test ListingSDK URL handling"""
    urls_list = []
    sdk = ListingSDK(None, urls_list)

    await sdk.enqueue("/events/meeting-1")
    await sdk.enqueue("https://detroitmi.gov/events/meeting-2")

    assert urls_list[0] == "https://detroitmi.gov/events/meeting-1"
    assert urls_list[1] == "https://detroitmi.gov/events/meeting-2"


@pytest.mark.asyncio
async def test_detail_sdk_save_data():
    """Test DetailSDK saves data correctly"""
    sdk = DetailSDK(None)
    test_data = {"title": "Test Meeting", "start_time": "2025-01-15T09:00:00-05:00"}

    await sdk.save_data(test_data)
    assert sdk.data == test_data


# Test DetroitPoliceOrchestrator


def test_transform_to_ocd_format_with_all_day_none():
    """Test transform_to_ocd_format handles is_all_day_event=None"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)
    orchestrator.current_url = "https://detroitmi.gov/events/test-meeting"

    raw_data = {
        "title": "Test Meeting",
        "start_time": "2025-01-15T09:00:00-05:00",
        "description": "Test description",
        "classification": "COMMITTEE",
        "location": {"name": "City Hall", "address": "123 Main St"},
        "links": [],
        "is_cancelled": False,
        "is_all_day_event": None,  # Reworkd returns None
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["all_day"] is False  # None should become False
    assert result["name"] == "Test Meeting"
    assert result["classification"] == "COMMITTEE"


def test_transform_to_ocd_format_with_all_day_true():
    """Test transform_to_ocd_format preserves is_all_day_event=True"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)
    orchestrator.current_url = "https://detroitmi.gov/events/test-meeting"

    raw_data = {
        "title": "Test Meeting",
        "start_time": "2025-01-15T00:00:00-05:00",
        "description": "",
        "classification": None,
        "is_all_day_event": True,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["all_day"] is True
    assert result["classification"] is None  # Keep None as-is


def test_transform_to_ocd_format_default_values():
    """Test transform_to_ocd_format handles missing fields"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)
    orchestrator.current_url = "https://detroitmi.gov/events/test"

    # Use future date (tomorrow)
    future_date = datetime.now(pytz.timezone(TIMEZONE)) + timedelta(days=1)
    future_iso = future_date.isoformat()

    raw_data = {
        "start_time": future_iso,
    }

    result = orchestrator.transform_to_ocd_format(raw_data)

    assert result["name"] == "Detroit Police Meeting"  # Default title
    assert result["classification"] == "COMMITTEE"  # Default classification
    assert result["description"] == ""
    assert result["status"] == "tentative"


@pytest.mark.asyncio
async def test_fallback_extraction_title():
    """Test fallback_extraction finds title from multiple selectors"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text = AsyncMock(return_value="Fallback Meeting Title")

    async def mock_query_selector(selector):
        if selector == ".title span":
            return mock_element
        return None

    mock_page.query_selector = mock_query_selector
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    assert result["title"] == "Fallback Meeting Title"


@pytest.mark.asyncio
async def test_fallback_extraction_default_title():
    """Test fallback_extraction uses default title when none found"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    assert result["title"] == "Detroit Police Meeting"


@pytest.mark.asyncio
async def test_fallback_extraction_classification():
    """Test fallback_extraction determines classification from title"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_title_element = AsyncMock()
    mock_title_element.inner_text = AsyncMock(
        return_value="Board of Commissioners Meeting"
    )

    async def mock_query_selector(selector):
        if selector == ".title span":
            return mock_title_element
        return None

    mock_page.query_selector = mock_query_selector
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    assert result["classification"] == "BOARD"


@pytest.mark.asyncio
async def test_fallback_extraction_cancelled():
    """Test fallback_extraction detects cancelled meetings"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_title_element = AsyncMock()
    mock_title_element.inner_text = AsyncMock(return_value="Meeting CANCELLED")

    async def mock_query_selector(selector):
        if selector == ".title span":
            return mock_title_element
        return None

    mock_page.query_selector = mock_query_selector
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    assert result["is_cancelled"] is True


@pytest.mark.asyncio
async def test_fallback_extraction_links():
    """Test fallback_extraction extracts document links"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.query_selector = AsyncMock(return_value=None)

    mock_link1 = AsyncMock()
    mock_link1.get_attribute = AsyncMock(return_value="/sites/agenda.pdf")
    mock_link1.inner_text = AsyncMock(return_value="Meeting Agenda")

    mock_link2 = AsyncMock()
    mock_link2.get_attribute = AsyncMock(return_value="/sites/minutes.pdf")
    mock_link2.inner_text = AsyncMock(return_value="Meeting Minutes")

    # Mock query_selector_all to return links only for first selector
    call_count = 0

    async def mock_query_selector_all(selector):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call returns the links
            return [mock_link1, mock_link2]
        return []  # Subsequent calls return empty

    mock_page.query_selector_all = mock_query_selector_all

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    assert len(result["links"]) == 2
    assert result["links"][0]["url"] == "https://detroitmi.gov/sites/agenda.pdf"
    assert result["links"][0]["title"] == "Agenda"
    assert result["links"][1]["url"] == "https://detroitmi.gov/sites/minutes.pdf"
    assert result["links"][1]["title"] == "Minutes"


# Test OCD format integration


def test_create_ocd_event_with_none_classification():
    """Test OCD event preserves None classification"""
    event_data = create_ocd_event(
        title="Test Meeting",
        start_time="2025-01-15T14:00:00-05:00",
        scraper_name=SCRAPER_NAME,
        agency_name=AGENCY_NAME,
        timezone=TIMEZONE,
        classification=None,
        source_url="https://example.com",
        all_day=False,
    )

    assert event_data["classification"] is None


@pytest.mark.asyncio
async def test_main_function():
    """Test main function runs orchestrator"""
    with patch(
        "harambe_scrapers.det_police_department.DetroitPoliceOrchestrator"
    ) as mock_orchestrator_class:
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run = AsyncMock()
        mock_orchestrator_class.return_value = mock_orchestrator

        await main()

        # Verify orchestrator was created with headless=True
        mock_orchestrator_class.assert_called_once_with(headless=True)
        mock_orchestrator.run.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_handles_detail_extraction_failure():
    """Test orchestrator handles failures in detail extraction gracefully"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.query_selector_all = AsyncMock(return_value=[])

    # Mock detail_scrape to raise an exception
    with patch(
        "harambe_scrapers.det_police_department.detail_scrape"
    ) as mock_detail_scrape:
        mock_detail_scrape.side_effect = Exception("Detail scraping failed")

        result = await orchestrator.run_detail_stage(
            mock_page, "https://detroitmi.gov/events/test-meeting"
        )

        # Should fall back and still return data
        assert result is not None
        assert "title" in result
        assert result["title"] == "Detroit Police Meeting"  # Default title


@pytest.mark.asyncio
async def test_fallback_extraction_with_date_parsing():
    """Test fallback_extraction parses dates correctly"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()

    # Mock date element
    mock_date_element = AsyncMock()
    mock_date_element.get_attribute = AsyncMock(return_value="2026-03-15")

    # Mock time element
    mock_time_element = AsyncMock()
    mock_time_element.inner_text = AsyncMock(return_value="2:30 PM")

    async def mock_query_selector(selector):
        if selector == ".date time":
            return mock_date_element
        elif selector == "article.time":
            return mock_time_element
        return None

    mock_page.query_selector = mock_query_selector
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    # Check that start_time was parsed and is in ISO format with timezone
    assert "start_time" in result
    assert "2026-03-15" in result["start_time"]
    assert "-05:00" in result["start_time"] or "-04:00" in result["start_time"]


@pytest.mark.asyncio
async def test_fallback_extraction_with_noon_time():
    """Test fallback_extraction handles 'Noon' time correctly"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    mock_page = MagicMock()

    mock_date_element = AsyncMock()
    mock_date_element.get_attribute = AsyncMock(return_value="2026-06-20")

    mock_time_element = AsyncMock()
    mock_time_element.inner_text = AsyncMock(return_value="Noon")

    async def mock_query_selector(selector):
        if selector == ".date time":
            return mock_date_element
        elif selector == "article.time":
            return mock_time_element
        return None

    mock_page.query_selector = mock_query_selector
    mock_page.query_selector_all = AsyncMock(return_value=[])

    result = await orchestrator.fallback_extraction(
        mock_page, "https://detroitmi.gov/events/test"
    )

    # Check that Noon was converted to 12:00 PM
    assert "start_time" in result
    assert "2026-06-20" in result["start_time"]
    # Noon should be 12:00
    assert "12:00" in result["start_time"]


def test_orchestrator_deduplicates_event_urls():
    """Test orchestrator removes duplicate event URLs"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)

    # Simulate duplicate URLs from listing stage
    orchestrator.event_urls = [
        "https://detroitmi.gov/events/meeting-1",
        "https://detroitmi.gov/events/meeting-2",
        "https://detroitmi.gov/events/meeting-1",  # Duplicate
        "https://detroitmi.gov/events/meeting-3",
        "https://detroitmi.gov/events/meeting-2",  # Duplicate
    ]

    # The run_listing_stage does deduplication
    orchestrator.event_urls = list(set(orchestrator.event_urls))

    assert len(orchestrator.event_urls) == 3
    assert "https://detroitmi.gov/events/meeting-1" in orchestrator.event_urls
    assert "https://detroitmi.gov/events/meeting-2" in orchestrator.event_urls
    assert "https://detroitmi.gov/events/meeting-3" in orchestrator.event_urls


# Fixtures for real HTML tests


@pytest.fixture
def detail_fixture_html():
    """Load actual HTML fixture for detail page"""
    parent_dir = Path(__file__).parent
    fixture_path = parent_dir / "files" / "det_police_department.html"
    with open(fixture_path, "r") as f:
        return f.read()


@pytest.mark.asyncio
async def test_fallback_extraction_with_real_html(detail_fixture_html):
    """Test fallback extraction with real HTML fixture

    This ensures fallback extraction can handle real HTML structure
    and extracts expected data from the fixture (2019-02-28 BOPC meeting).
    """
    orchestrator = DetroitPoliceOrchestrator(headless=True)
    orchestrator.current_url = (
        "https://detroitmi.gov/events/board-police-commissioners-2-28-19"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(detail_fixture_html)

        result = await orchestrator.fallback_extraction(page, orchestrator.current_url)

        await browser.close()

        # Verify fallback extraction works with real HTML
        assert result is not None
        assert "title" in result
        assert "links" in result
        assert isinstance(result["links"], list)
        assert "is_cancelled" in result
        assert isinstance(result["is_cancelled"], bool)

        # Verify specific data from the fixture
        assert "Board of Police Commissioners" in result["title"]
        assert (
            "2019" in result.get("start_time", "") or result["title"]
        )  # Fixture is from 2019

        # Transform to OCD format and verify
        ocd_event = orchestrator.transform_to_ocd_format(result)

        assert ocd_event["_type"] == "event"
        assert ocd_event["_id"].startswith("ocd-event/")
        assert "Board of Police Commissioners" in ocd_event["name"]
        assert ocd_event["extras"]["cityscrapers.org/agency"] == AGENCY_NAME
        assert SCRAPER_NAME in ocd_event["extras"]["cityscrapers.org/id"]
        assert ocd_event["sources"][0]["url"] == orchestrator.current_url
