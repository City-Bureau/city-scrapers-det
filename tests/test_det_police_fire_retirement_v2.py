"""
Unit tests for Detroit Police & Fire Retirement System v2 scraper (Harambe-based).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import async_playwright

from harambe_scrapers.det_police_fire_retirement import (
    AGENCY_NAME,
    START_URL,
    main,
    scrape,
)


@pytest.fixture
def mock_sdk():
    """Create mock SDK"""
    sdk = MagicMock()
    sdk.page = MagicMock()
    sdk.save_data = AsyncMock()
    sdk.enqueue = AsyncMock()
    return sdk


@pytest.fixture
def mock_page_basic():
    """Create mock page with basic meeting data"""
    page = MagicMock()

    # Mock title element
    title_element = MagicMock()
    title_text = (
        "Board of Trustees of the Police and Fire Retirement "
        "System - 2025 Meeting Schedule"
    )
    title_element.inner_text = AsyncMock(return_value=title_text)

    # Mock location element
    location_element = MagicMock()
    location_text = "Meeting Location:\nCity Hall\n123 Main St, Detroit, MI 48201"
    location_element.inner_text = AsyncMock(return_value=location_text)

    async def query_selector_mock(selector):
        if selector == "#post p strong":
            return title_element
        elif "Meeting Location" in selector:
            return location_element
        return None

    page.query_selector = AsyncMock(side_effect=query_selector_mock)
    page.wait_for_selector = AsyncMock()

    return page


@pytest.fixture
def mock_table_rows():
    """Create mock table rows with meeting data"""
    rows = []

    # Header row (should be skipped)
    header_row = MagicMock()
    header_row.query_selector_all = AsyncMock(return_value=[])
    rows.append(header_row)

    # Regular meeting row
    regular_row = MagicMock()
    regular_cols = [
        MagicMock(inner_text=AsyncMock(return_value="January 16, 2025")),
        MagicMock(inner_text=AsyncMock(return_value="9:00 AM")),
        MagicMock(inner_text=AsyncMock(return_value="Room 204")),
    ]
    regular_row.query_selector_all = AsyncMock(return_value=regular_cols)
    regular_row.query_selector = AsyncMock(return_value=None)  # No detail link
    rows.append(regular_row)

    # Cancelled meeting row
    cancelled_row = MagicMock()
    cancelled_cols = [
        MagicMock(inner_text=AsyncMock(return_value="CANCELLED February 6, 2025")),
        MagicMock(inner_text=AsyncMock(return_value="9:00 A.M.")),  # Test A.M. format
        MagicMock(inner_text=AsyncMock(return_value="Room 204")),
    ]
    cancelled_row.query_selector_all = AsyncMock(return_value=cancelled_cols)
    cancelled_row.query_selector = AsyncMock(return_value=None)
    rows.append(cancelled_row)

    # Meeting with detail page link
    detail_row = MagicMock()
    detail_cols = [
        MagicMock(inner_text=AsyncMock(return_value="March 20, 2025")),
        MagicMock(inner_text=AsyncMock(return_value="2:30 P.M.")),  # Test P.M. format
        MagicMock(inner_text=AsyncMock(return_value="Conference Room A")),
    ]
    detail_link = MagicMock()
    detail_link.get_attribute = AsyncMock(return_value="meeting_detail.php?id=123")
    detail_row.query_selector_all = AsyncMock(return_value=detail_cols)
    detail_row.query_selector = AsyncMock(return_value=detail_link)
    rows.append(detail_row)

    return rows


@pytest.mark.asyncio
async def test_scrape_listing_page(mock_sdk, mock_page_basic, mock_table_rows):
    """Test scraping the listing page"""
    mock_page_basic.query_selector_all = AsyncMock(return_value=mock_table_rows)
    mock_sdk.page = mock_page_basic

    await scrape(mock_sdk, START_URL, {})

    # Now all meetings are saved, none are enqueued
    assert mock_sdk.save_data.call_count == 3  # All 3 meetings saved
    assert mock_sdk.enqueue.call_count == 0  # No enqueuing

    first_call = mock_sdk.save_data.call_args_list[0][0][0]
    expected_name = (
        "Board of Trustees of the Police and Fire Retirement "
        "System - 2025 Meeting Schedule"
    )
    assert first_call["name"] == expected_name
    assert first_call["classification"] == "Board"
    assert "City Hall" in first_call["location"]["name"]
    assert first_call["extras"]["cityscrapers.org/agency"] == AGENCY_NAME
    expected_address = "123 Main St, Detroit, MI 48201"
    assert first_call["extras"]["cityscrapers.org/address"] == expected_address

    second_call = mock_sdk.save_data.call_args_list[1][0][0]
    assert second_call["status"] == "canceled"
    assert second_call["all_day"] is True

    # Check third meeting (previously enqueued)
    third_call = mock_sdk.save_data.call_args_list[2][0][0]
    assert third_call["_type"] == "event"
    assert "2025-03-20" in third_call["start_time"]


@pytest.mark.asyncio
async def test_scrape_with_invalid_date(mock_sdk, mock_page_basic):
    """Test handling of invalid date formats"""
    invalid_row = MagicMock()
    invalid_cols = [
        MagicMock(inner_text=AsyncMock(return_value="Invalid Date")),
        MagicMock(inner_text=AsyncMock(return_value="9:00 AM")),
        MagicMock(inner_text=AsyncMock(return_value="Room 204")),
    ]
    invalid_row.query_selector_all = AsyncMock(return_value=invalid_cols)
    invalid_row.query_selector = AsyncMock(return_value=None)

    mock_page_basic.query_selector_all = AsyncMock(
        return_value=[MagicMock(), invalid_row]
    )
    mock_sdk.page = mock_page_basic

    with pytest.raises(ValueError, match="Error parsing date/time"):
        await scrape(mock_sdk, START_URL, {})


@pytest.fixture
def fixture_html():
    """Load actual HTML fixture"""
    parent_dir = Path(__file__).parent
    fixture_path = parent_dir / "files" / "det_police_fire_retirement.html"
    with open(fixture_path, "r") as f:
        return f.read()


@pytest.mark.asyncio
async def test_scrape_with_real_browser_and_html(fixture_html):
    """Integration test using real browser with HTML fixture

    This test actually loads the HTML fixture into a real browser and runs the
    scraper against it, ensuring the selectors and parsing logic work with real HTML.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(fixture_html)

        sdk = MagicMock()
        sdk.page = page  # Real browser page with fixture HTML
        sdk.save_data = AsyncMock()
        sdk.enqueue = AsyncMock()

        await scrape(sdk, START_URL, {})

        assert (
            sdk.save_data.call_count > 0
        ), "Should have processed meetings from real HTML"

        all_meetings = []
        for call in sdk.save_data.call_args_list:
            all_meetings.append(call[0][0])

        assert (
            len(all_meetings) >= 10
        ), f"Should extract at least 10 meetings from fixture, got {len(all_meetings)}"

        first_meeting = all_meetings[0]
        assert first_meeting["_type"] == "event"
        assert (
            "Board of Trustees" in first_meeting["name"]
            or "BOARD" in first_meeting["name"].upper()
        )
        assert "2019" in first_meeting["start_time"]
        assert first_meeting["location"]["name"]
        assert first_meeting["extras"]["cityscrapers.org/agency"] == AGENCY_NAME

        # Verify specific meetings from fixture
        jan10_meetings = [m for m in all_meetings if "2019-01-10" in m["start_time"]]
        assert len(jan10_meetings) == 1, "Should find January 10, 2019 meeting"

        jan10 = jan10_meetings[0]
        assert "09:00" in jan10["start_time"]
        assert "CONFERENCE ROOM" in jan10["location"]["name"].upper()

        jan24_meetings = [m for m in all_meetings if "2019-01-24" in m["start_time"]]
        assert len(jan24_meetings) == 1, "Should find January 24, 2019 meeting"
        # Status assertions removed as they depend on current date

        await browser.close()


@pytest.mark.asyncio
async def test_scrape_empty_table(mock_sdk):
    """Test handling of empty meeting table"""
    page = MagicMock()

    title_element = MagicMock()
    title_element.inner_text = AsyncMock(return_value="Board Meetings")

    async def query_selector_mock(selector):
        if selector == "#post p strong":
            return title_element
        return None

    page.query_selector = AsyncMock(side_effect=query_selector_mock)
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])  # Empty table
    mock_sdk.page = page

    await scrape(mock_sdk, START_URL, {})
    assert mock_sdk.save_data.call_count == 0


@pytest.mark.asyncio
async def test_scrape_malformed_row(mock_sdk, mock_page_basic):
    """Test handling of malformed table row"""
    malformed_row = MagicMock()
    malformed_cols = [
        MagicMock(inner_text=AsyncMock(return_value="January 16, 2025")),
        # Missing time and location columns
    ]
    malformed_row.query_selector_all = AsyncMock(return_value=malformed_cols)

    mock_page_basic.query_selector_all = AsyncMock(
        return_value=[MagicMock(), malformed_row]
    )
    mock_sdk.page = mock_page_basic

    await scrape(mock_sdk, START_URL, {})
    assert mock_sdk.save_data.call_count == 0


@pytest.mark.asyncio
async def test_main_function():
    """Test the main function orchestration"""
    with patch("harambe_scrapers.det_police_fire_retirement.SDK.run") as mock_run:
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            with patch("builtins.open", create=True):
                mock_run.return_value = None

                await main()

                mock_mkdir.assert_called_once_with(exist_ok=True)
                mock_run.assert_called_once()
                call_args = mock_run.call_args

                assert "observer" in call_args[1]
                assert "harness" in call_args[1]
                assert call_args[1]["headless"] is True
