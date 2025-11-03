"""
Unit tests for Detroit Wayne County Port Authority v2 scraper (Harambe-based).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import async_playwright

from harambe_scrapers.det_dwcpa import AGENCY_NAME, START_URL, main, scrape
from harambe_scrapers.observers import DataCollector


@pytest.fixture
def mock_sdk():
    sdk = MagicMock()
    sdk.page = MagicMock()
    sdk.save_data = AsyncMock()
    return sdk


@pytest.fixture
def mock_page_basic():
    page = MagicMock()

    title_element = MagicMock()
    title_element.inner_text = AsyncMock(return_value="Board of Directors Meetings")

    year_element = MagicMock()
    year_element.inner_text = AsyncMock(return_value="2025 Meeting Schedule")

    location_element = MagicMock()
    location_text = (
        "Meetings are held at Port Detroit Conference Room located at "
        "130 E. Atwater Street, Detroit, MI 48226, beginning at 10:00 am"
    )
    location_element.inner_text = AsyncMock(return_value=location_text)

    async def query_selector_mock(selector):
        if ".heading-text.el-text h2.h1 span" in selector:
            return title_element
        elif "div h2:has-text('Meeting Schedule')" in selector:
            return year_element
        elif "div:has-text('Meeting Schedule') em" in selector:
            return location_element
        return None

    page.query_selector = AsyncMock(side_effect=query_selector_mock)
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()

    return page


@pytest.fixture
def mock_meeting_elements():
    elements = []

    element1 = MagicMock()
    element1.inner_text = AsyncMock(return_value="Thursday, January 16th")
    elements.append(element1)

    element2 = MagicMock()
    element2.inner_text = AsyncMock(return_value="Friday, February 21st")
    elements.append(element2)

    element3 = MagicMock()
    element3.inner_text = AsyncMock(return_value="Monday, March 3rd")
    elements.append(element3)

    return elements


@pytest.mark.asyncio
async def test_scrape_listing_page(mock_sdk, mock_page_basic, mock_meeting_elements):
    """Test scraping the listing page"""
    mock_page_basic.query_selector_all = AsyncMock(return_value=mock_meeting_elements)
    mock_sdk.page = mock_page_basic

    await scrape(mock_sdk, START_URL, {})

    assert mock_sdk.save_data.call_count == 3

    first_call = mock_sdk.save_data.call_args_list[0][0][0]
    assert first_call["name"] == "Board of Directors Meetings"
    assert first_call["classification"] == "Board"
    assert "2025-01-16" in first_call["start_time"]
    assert first_call["extras"]["cityscrapers.org/agency"] == AGENCY_NAME

    second_call = mock_sdk.save_data.call_args_list[1][0][0]
    assert "2025-02-21" in second_call["start_time"]

    third_call = mock_sdk.save_data.call_args_list[2][0][0]
    assert "2025-03-03" in third_call["start_time"]


@pytest.mark.asyncio
async def test_scrape_with_time_parsing(mock_sdk, mock_page_basic):
    """Test time parsing from location text"""
    page = MagicMock()

    title_element = MagicMock()
    title_element.inner_text = AsyncMock(return_value="Board of Directors Meetings")

    year_element = MagicMock()
    year_element.inner_text = AsyncMock(return_value="2025 Meeting Schedule")

    location_element = MagicMock()
    location_text = (
        "Meetings are held at Conference Room located at "
        "130 E. Atwater, beginning at 10:30 am"
    )
    location_element.inner_text = AsyncMock(return_value=location_text)

    async def query_selector_mock(selector):
        if ".heading-text.el-text h2.h1 span" in selector:
            return title_element
        elif "div h2:has-text('Meeting Schedule')" in selector:
            return year_element
        elif "div:has-text('Meeting Schedule') em" in selector:
            return location_element
        return None

    page.query_selector = AsyncMock(side_effect=query_selector_mock)
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()

    meeting_element = MagicMock()
    meeting_element.inner_text = AsyncMock(return_value="Monday, January 20th")
    page.query_selector_all = AsyncMock(return_value=[meeting_element])

    mock_sdk.page = page

    await scrape(mock_sdk, START_URL, {})

    assert mock_sdk.save_data.call_count == 1
    call = mock_sdk.save_data.call_args_list[0][0][0]
    assert "T10:30" in call["start_time"]


@pytest.mark.asyncio
async def test_scrape_default_time(mock_sdk, mock_page_basic):
    """Test default time when no time is found"""
    page = MagicMock()

    title_element = MagicMock()
    title_element.inner_text = AsyncMock(return_value="Board of Directors Meetings")

    year_element = MagicMock()
    year_element.inner_text = AsyncMock(return_value="2025 Meeting Schedule")

    location_element = MagicMock()
    location_text = "Meetings are held at Conference Room"
    location_element.inner_text = AsyncMock(return_value=location_text)

    async def query_selector_mock(selector):
        if ".heading-text.el-text h2.h1 span" in selector:
            return title_element
        elif "div h2:has-text('Meeting Schedule')" in selector:
            return year_element
        elif "div:has-text('Meeting Schedule') em" in selector:
            return location_element
        return None

    page.query_selector = AsyncMock(side_effect=query_selector_mock)
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()

    meeting_element = MagicMock()
    meeting_element.inner_text = AsyncMock(return_value="Tuesday, January 14th")
    page.query_selector_all = AsyncMock(return_value=[meeting_element])

    mock_sdk.page = page

    await scrape(mock_sdk, START_URL, {})

    assert mock_sdk.save_data.call_count == 1
    call = mock_sdk.save_data.call_args_list[0][0][0]
    assert "T09:00" in call["start_time"]


@pytest.mark.asyncio
async def test_scrape_location_parsing(
    mock_sdk, mock_page_basic, mock_meeting_elements
):
    """Test location parsing from location text"""
    mock_page_basic.query_selector_all = AsyncMock(return_value=mock_meeting_elements)
    mock_sdk.page = mock_page_basic

    await scrape(mock_sdk, START_URL, {})

    call = mock_sdk.save_data.call_args_list[0][0][0]
    assert "Port Detroit Conference Room" in call["location"]["name"]
    assert (
        "130 E. Atwater Street, Detroit, MI 48226"
        in call["extras"]["cityscrapers.org/address"]
    )


@pytest.mark.asyncio
async def test_scrape_empty_elements(mock_sdk, mock_page_basic):
    """Test handling of empty meeting elements"""
    mock_page_basic.query_selector_all = AsyncMock(return_value=[])
    mock_sdk.page = mock_page_basic

    await scrape(mock_sdk, START_URL, {})
    assert mock_sdk.save_data.call_count == 0


# DataCollector tests


@pytest.fixture
def mock_azure_env():
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
@patch("harambe_scrapers.observers.BlobServiceClient")
async def test_data_collector_with_azure(mock_blob_client, mock_azure_env):
    """Test DataCollector with Azure configuration"""
    mock_container = MagicMock()
    mock_blob = MagicMock()
    mock_blob.download_blob.side_effect = Exception("Not found")
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
    assert blob_path_call.count("/") == 4


@pytest.mark.asyncio
async def test_main_function():
    """Test the main function orchestration"""
    with patch("harambe_scrapers.det_dwcpa.SDK.run") as mock_run:
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


@pytest.fixture
def fixture_html():
    parent_dir = Path(__file__).parent
    fixture_path = parent_dir / "files" / "det_dwcpa.html"
    with open(fixture_path, "r") as f:
        return f.read()


@pytest.mark.asyncio
async def test_scrape_with_real_browser_and_html(fixture_html):
    """Integration test using real browser with HTML fixture"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(fixture_html)

        sdk = MagicMock()
        sdk.page = page
        sdk.save_data = AsyncMock()

        await scrape(sdk, START_URL, {})

        all_meetings = [call[0][0] for call in sdk.save_data.call_args_list]

        assert len(all_meetings) == 6

        first_meeting = all_meetings[0]
        assert first_meeting["_type"] == "event"
        assert first_meeting["name"] == "Board Meeting"
        assert first_meeting["classification"] == "Board"
        assert first_meeting["timezone"] == "America/Detroit"
        assert "130 E. Atwater" in first_meeting["extras"]["cityscrapers.org/address"]
        assert first_meeting["extras"]["cityscrapers.org/agency"] == AGENCY_NAME
        assert "2025-01-17" in first_meeting["start_time"]
        assert "09:00:00" in first_meeting["start_time"]

        meeting_dates = [m["start_time"] for m in all_meetings]
        assert any("2025-01-17" in d for d in meeting_dates)
        assert any("2025-03-21" in d for d in meeting_dates)
        assert any("2025-05-16" in d for d in meeting_dates)
        assert any("2025-07-18" in d for d in meeting_dates)
        assert any("2025-09-19" in d for d in meeting_dates)
        assert any("2025-11-21" in d for d in meeting_dates)

        await browser.close()
