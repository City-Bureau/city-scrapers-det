"""
Unit tests for Detroit Police & Fire Retirement System v2 scraper (Harambe-based).
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from freezegun import freeze_time
from playwright.async_api import async_playwright

from harambe_scrapers.det_police_fire_retirement import (
    AGENCY_NAME,
    OUTPUT_DIR,
    SCRAPER_NAME,
    START_URL,
    TIMEZONE,
    main,
    scrape,
)
from harambe_scrapers.observers import DataCollector
from harambe_scrapers.utils import (
    determine_status,
    generate_id,
    generate_ocd_id,
    slugify,
)

# Helper function tests


def test_slugify():
    """Test slugify function with various inputs"""
    assert slugify("Board of Trustees") == "board_of_trustees"
    assert slugify("Meeting #123") == "meeting_123"
    assert slugify("   Spaces   ") == "spaces"
    assert slugify("Special-Characters!@#") == "special-characters"  # Hyphens are kept
    assert slugify("Multiple   Spaces") == "multiple_spaces"
    assert slugify("under_score") == "under_score"
    assert slugify("") == ""
    assert slugify("CAPS-and-lower") == "caps-and-lower"  # Hyphens are kept
    assert slugify("123-numbers") == "123-numbers"  # Hyphens are kept


def test_slugify_edge_cases():
    """Test slugify with edge cases"""
    assert slugify(None) == "none"
    assert slugify(123) == "123"
    assert slugify("---test---") == "test"  # Leading/trailing hyphens removed
    assert slugify("___test___") == "_test_"  # Underscores are kept
    assert slugify("test-") == "test"  # Trailing hyphen removed
    assert slugify("-test") == "test"  # Leading hyphen removed


def test_generate_id():
    """Test ID generation"""
    # Normal meeting
    result = generate_id("Board Meeting", "2025-01-15T09:00:00-05:00", SCRAPER_NAME)
    assert result == f"{SCRAPER_NAME}/202501150900/x/board_meeting"

    # Complex name (hyphen in middle is kept)
    result = generate_id(
        "Board of Trustees - Special Meeting #123",
        "2025-12-31T23:59:00-05:00",
        SCRAPER_NAME,
    )
    assert (
        result
        == f"{SCRAPER_NAME}/202512312359/x/board_of_trustees_-_special_meeting_123"
    )

    # UTC timezone
    result = generate_id("Test Meeting", "2025-01-15T14:00:00Z", SCRAPER_NAME)
    assert result == f"{SCRAPER_NAME}/202501151400/x/test_meeting"


def test_generate_ocd_id():
    """Test OCD ID generation"""
    scraper_id = f"{SCRAPER_NAME}/202501150900/x/board_meeting"
    result = generate_ocd_id(scraper_id)

    # Verify format
    assert result.startswith("ocd-event/")
    parts = result.replace("ocd-event/", "").split("-")
    assert len(parts) == 5
    assert len(parts[0]) == 8  # First segment
    assert len(parts[1]) == 4  # Second segment
    assert len(parts[2]) == 4  # Third segment
    assert len(parts[3]) == 4  # Fourth segment
    assert len(parts[4]) == 12  # Fifth segment

    # Verify deterministic - same input always produces same output
    result2 = generate_ocd_id(scraper_id)
    assert result == result2

    # Different input produces different output
    different_id = f"{SCRAPER_NAME}/202501160900/x/different_meeting"
    result3 = generate_ocd_id(different_id)
    assert result3 != result


@freeze_time("2025-01-10T12:00:00-05:00")
def test_determine_status():
    """Test status determination"""
    # Cancelled meetings always return "canceled"
    assert determine_status(True, "2025-01-15T09:00:00-05:00") == "canceled"
    assert determine_status(True, "2024-01-15T09:00:00-05:00") == "canceled"
    assert determine_status(True, "2025-01-10T12:00:00-05:00") == "canceled"

    # Future meeting (tentative)
    assert determine_status(False, "2025-01-15T09:00:00-05:00") == "tentative"
    assert determine_status(False, "2025-12-31T23:59:00-05:00") == "tentative"

    # Past meeting
    assert determine_status(False, "2025-01-05T09:00:00-05:00") == "passed"
    assert determine_status(False, "2024-12-31T23:59:00-05:00") == "passed"

    # Edge case: meeting happening now (should be passed)
    assert determine_status(False, "2025-01-10T12:00:00-05:00") == "passed"


# Fixtures for scraper tests


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


# Scraper function tests


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


# DataCollector tests


@pytest.fixture
def mock_azure_env():
    """Mock Azure environment variables"""
    with patch.dict(
        "os.environ",
        {
            "AZURE_ACCOUNT_NAME": "testaccount",
            "AZURE_ACCOUNT_KEY": "testkey",
            "AZURE_CONTAINER": "testcontainer",
        },
    ):
        yield


@pytest.mark.asyncio
async def test_data_collector_without_azure():
    """Test DataCollector without Azure configuration"""
    collector = DataCollector("test_scraper", "America/Detroit")
    assert collector.scraper_name == "test_scraper"
    assert collector.timezone == "America/Detroit"
    assert collector.data == []
    assert collector.azure_client is None

    test_data = {"name": "Test Meeting", "start_time": "2025-01-15T09:00:00-05:00"}

    await collector.on_save_data(test_data)

    assert len(collector.data) == 1
    assert collector.data[0] == test_data


@pytest.mark.asyncio
@patch("harambe_scrapers.observers.BlobServiceClient")
async def test_data_collector_with_azure(mock_blob_client, mock_azure_env):
    """Test DataCollector with Azure configuration"""
    mock_container = MagicMock()
    mock_blob = MagicMock()
    mock_blob.download_blob.side_effect = Exception("Not found")  # Simulate new blob
    mock_blob.upload_blob = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob
    blob_client = mock_blob_client.from_connection_string.return_value
    blob_client.get_container_client.return_value = mock_container

    collector = DataCollector("test_scraper_v2", "America/Detroit")

    test_data = {"name": "Test Meeting", "start_time": "2025-01-15T09:00:00-05:00"}

    await collector.on_save_data(test_data)

    assert mock_container.get_blob_client.called
    assert mock_blob.upload_blob.called

    blob_path_call = mock_container.get_blob_client.call_args[0][0]
    assert "test_scraper_v2.json" in blob_path_call
    assert blob_path_call.count("/") == 4  # year/month/day/hourmin/file.json


def test_meeting_data_structure():
    """Verify meeting data structure matches expected format"""
    title = "Board Meeting"
    start_time_iso = "2025-01-15T09:00:00-05:00"
    scraper_id = generate_id(title, start_time_iso, SCRAPER_NAME)
    ocd_id = generate_ocd_id(scraper_id)

    meeting = {
        "_type": "event",
        "_id": ocd_id,
        "updated_at": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
        "name": title,
        "description": "",
        "classification": "Board",
        "status": "tentative",
        "all_day": False,
        "start_time": start_time_iso,
        "end_time": None,
        "timezone": TIMEZONE,
        "location": {
            "url": "",
            "name": "City Hall",
            "coordinates": None,
        },
        "documents": [],
        "links": [],
        "sources": [{"url": START_URL, "note": ""}],
        "participants": [
            {
                "note": "host",
                "name": AGENCY_NAME,
                "entity_type": "organization",
                "entity_name": AGENCY_NAME,
                "entity_id": "",
            }
        ],
        "extras": {
            "cityscrapers.org/id": scraper_id,
            "cityscrapers.org/agency": AGENCY_NAME,
            "cityscrapers.org/time_notes": "",
            "cityscrapers.org/address": "123 Main St",
        },
    }

    assert meeting["_type"] == "event"
    assert meeting["_id"].startswith("ocd-event/")
    assert meeting["name"] == title
    assert meeting["classification"] in [
        "Board",
        "Committee",
        "Commission",
        "Advisory Committee",
    ]
    assert meeting["status"] in ["tentative", "passed", "canceled"]
    assert isinstance(meeting["all_day"], bool)
    assert meeting["timezone"] == TIMEZONE
    assert meeting["extras"]["cityscrapers.org/id"] == scraper_id
    assert meeting["extras"]["cityscrapers.org/agency"] == AGENCY_NAME


@pytest.mark.parametrize(
    "date_str,time_str,expected_hour",
    [
        ("January 15, 2025", "9:00 AM", 9),
        ("January 15, 2025", "9:00 A.M.", 9),
        ("January 15, 2025", "2:30 PM", 14),
        ("January 15, 2025", "2:30 P.M.", 14),
        ("January 15, 2025", "12:00 PM", 12),
        ("January 15, 2025", "12:00 AM", 0),
    ],
)
def test_time_parsing_variations(date_str, time_str, expected_hour):
    """Test parsing various time formats"""
    normalized_time = time_str.replace("A.M.", "AM").replace("P.M.", "PM")

    dt = datetime.strptime(f"{date_str} {normalized_time}", "%B %d, %Y %I:%M %p")

    assert dt.hour == expected_hour


def test_constants():
    """Test that all required constants are defined correctly"""
    expected_url = (
        "https://www.rscd.org/member_resources/"
        "board_of_trustees/upcoming_meetings.php"
    )
    assert START_URL == expected_url
    assert SCRAPER_NAME == "det_police_fire_retirement_v2"
    assert AGENCY_NAME == "Detroit Police & Fire Retirement System"
    assert TIMEZONE == "America/Detroit"
    assert OUTPUT_DIR == Path("harambe_scrapers/output")


@pytest.fixture
def fixture_html():
    """Load actual HTML fixture"""
    parent_dir = Path(__file__).parent
    fixture_path = parent_dir / "files" / "det_police_fire_retirement.html"
    with open(fixture_path, "r") as f:
        return f.read()


@pytest.fixture
async def browser_page_with_fixture():
    """Create a real browser page with fixture HTML loaded"""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    yield page

    await browser.close()
    await playwright.stop()


@pytest.mark.asyncio
@freeze_time("2019-01-05T12:00:00-05:00")
async def test_scrape_with_real_browser_and_html(fixture_html):
    """Integration test using real browser with HTML fixture - similar to Scrapy tests

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
        assert jan24_meetings[0]["status"] == "tentative"  # Future from Jan 5
        assert jan10_meetings[0]["status"] == "tentative"  # Future from Jan 5

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


@pytest.mark.parametrize(
    "url,base_url,expected",
    [
        (
            "meeting.php",
            "https://example.com/path",
            "https://example.com/path/meeting.php",
        ),
        (
            "http://example.com/doc.pdf",
            "https://other.com",
            "http://example.com/doc.pdf",
        ),
        (
            "/absolute/path.pdf",
            "https://example.com/sub",
            "https://example.com/absolute/path.pdf",
        ),
        (
            "../parent/file.pdf",
            "https://example.com/sub/path",
            "https://example.com/sub/parent/file.pdf",
        ),
    ],
)
def test_url_resolution(url, base_url, expected):
    """Test URL resolution logic"""
    if not url.startswith("http"):
        if url.startswith("/"):
            base_parts = base_url.split("/")[:3]  # Get protocol and domain
            result = "/".join(base_parts) + url
        else:
            base_parts = base_url.split("/")[:-1]  # Remove last segment
            result = "/".join(base_parts) + "/" + url
    else:
        result = url

    assert "://" in result or result.startswith("/")
