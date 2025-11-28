"""
Unit tests for Michigan Belle Isle Advisory Committee scraper (Harambe-based).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import async_playwright

from harambe_scrapers.mi_belle_isle import AGENCY_NAME, START_URL, main, scrape


@pytest.fixture
def mock_sdk():
    sdk = MagicMock()
    sdk.page = MagicMock()
    sdk.save_data = AsyncMock()
    return sdk


@pytest.mark.asyncio
async def test_scrape_empty_table(mock_sdk):
    """Test handling of empty meeting table"""
    page = MagicMock()

    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    mock_sdk.page = page

    await scrape(mock_sdk, START_URL, {})
    assert mock_sdk.save_data.call_count == 0


@pytest.mark.asyncio
async def test_main_function():
    """Test the main function orchestration"""
    with patch("harambe_scrapers.mi_belle_isle.SDK.run") as mock_run:
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
    fixture_path = parent_dir / "files" / "mi_belle_isle.html"
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

        assert len(all_meetings) == 12

        first_meeting = all_meetings[0]
        assert first_meeting["_type"] == "event"
        assert first_meeting["name"]
        assert (
            "Belle Isle" in first_meeting["name"] or "Advisory" in first_meeting["name"]
        )
        assert first_meeting["classification"] == "ADVISORY"
        assert first_meeting["timezone"] == "America/Detroit"
        assert first_meeting["extras"]["cityscrapers.org/agency"] == AGENCY_NAME
        assert "2018-01-18" in first_meeting["start_time"]
        assert "09:00:00" in first_meeting["start_time"]
        assert first_meeting["location"]["name"] == "Flynn Pavilion"

        meeting_dates = [m["start_time"] for m in all_meetings]
        assert any("2018-01-18" in d for d in meeting_dates)
        assert any("2018-02-15" in d for d in meeting_dates)
        assert any("2018-03-15" in d for d in meeting_dates)
        assert any("2018-04-19" in d for d in meeting_dates)
        assert any("2018-05-17" in d for d in meeting_dates)
        assert any("2018-06-21" in d for d in meeting_dates)
        assert any("2018-07-13" in d for d in meeting_dates)
        assert any("2018-08-16" in d for d in meeting_dates)
        assert any("2018-09-20" in d for d in meeting_dates)
        assert any("2018-10-18" in d for d in meeting_dates)
        assert any("2018-11-15" in d for d in meeting_dates)
        assert any("2018-12-20" in d for d in meeting_dates)

        flynn_pavilion_meetings = [
            m for m in all_meetings if m["location"]["name"] == "Flynn Pavilion"
        ]
        nature_zoo_meetings = [
            m for m in all_meetings if m["location"]["name"] == "Belle Isle Nature Zoo"
        ]
        assert len(flynn_pavilion_meetings) > 0
        assert len(nature_zoo_meetings) > 0

        meetings_with_links = [m for m in all_meetings if m.get("links")]
        assert len(meetings_with_links) > 0

        for meeting in all_meetings:
            assert meeting["_type"] == "event"
            assert meeting["_id"].startswith("ocd-event/")
            assert meeting["timezone"] == "America/Detroit"
            assert meeting["classification"] == "ADVISORY"
            assert meeting["status"] in ["tentative", "passed", "canceled"]

        await browser.close()
