"""
Unit tests for Wayne County Commission scraper (Harambe-based orchestrator).
Tests the two-stage orchestration (listing->detail) over plain HTTP.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def make_response(json_data=None, text=None, status_code=200):
    """Build a mock requests response"""
    response = MagicMock()
    response.status_code = status_code
    response.text = text or (json.dumps(json_data) if json_data else "")
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def test_transform_to_ocd_format_with_all_fields():
    """Test transform_to_ocd_format with complete meeting data"""
    orchestrator = WayneCommissionOrchestrator()
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
    orchestrator = WayneCommissionOrchestrator()
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
    orchestrator = WayneCommissionOrchestrator()

    with patch("harambe_scrapers.wayne_commission.listing_scrape") as mock_listing:

        async def mock_scrape(sdk, url, context, **kwargs):
            await sdk.enqueue("https://meeting1.com", {"isCancelled": "False"})
            await sdk.enqueue("https://meeting2.com", {"isCancelled": "False"})

        mock_listing.side_effect = mock_scrape

        await orchestrator.run_listing_stage()

        assert len(orchestrator.detail_urls) == 2
        assert orchestrator.detail_urls[0]["url"] == "https://meeting1.com"


@pytest.mark.asyncio
async def test_orchestrator_with_limit():
    """Test that the orchestrator respects the limit_meetings parameter"""
    orchestrator = WayneCommissionOrchestrator(limit_meetings=3)

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

                await orchestrator.run()

                assert mock_detail.call_count == 3


@pytest.mark.asyncio
async def test_listing_scraper_with_mock_api():
    """Test listing scraper walks the calendar API and enqueues detail URLs"""
    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    calendar_page_html = (
        "<div data-entity-id='126c63c0-c42f-43aa-8168-1867f0ae80f1' "
        "data-entity-type=combinedCalendar class='oc-calendar'></div>"
    )
    calendars_response = {
        "success": True,
        "data": [
            {"Id": "cal-full-commission", "Label": "Full Commission Meeting"},
            {"Id": "cal-ways-means", "Label": "Ways & Means Committee"},
        ],
    }
    items_response = {
        "success": True,
        "data": [
            {
                "Items": [
                    {
                        "CalendarId": "cal-full-commission",
                        "Id": "item-1",
                        "MainContentId": "item-1",
                        "Name": "Full Commission - January 8, 2026",
                        "DateTime": "1/8/2026 10:00:00 AM",
                    }
                ]
            }
        ],
    }
    empty_items_response = {"success": True, "data": []}
    content_info_response = {
        "success": True,
        "data": {
            "Title": "Full Commission - January 8, 2026",
            "Link": "https://www.waynecountymi.gov/meeting-detail",
            "IsCancelled": False,
        },
    }

    session = MagicMock()

    def fake_get(url, **kwargs):
        if "County-Calendar" in url:
            return make_response(text=calendar_page_html)
        if "getcalendars" in url:
            return make_response(json_data=calendars_response)
        if "contentinfo" in url:
            return make_response(json_data=content_info_response)
        raise AssertionError(f"Unexpected GET {url}")

    post_responses = iter([empty_items_response, items_response, empty_items_response])

    def fake_post(url, **kwargs):
        assert "getcalendaritems" in url
        payload = kwargs["json"]
        assert payload["Ids"] == ["cal-full-commission", "cal-ways-means"]
        return make_response(json_data=next(post_responses))

    session.get.side_effect = fake_get
    session.post.side_effect = fake_post

    detail_urls = []
    sdk = ListingSDK(detail_urls)

    with patch(
        "harambe_scrapers.extractor.wayne_commission.listing."
        "ITEM_REQUEST_DELAY_SECONDS",
        0,
    ):
        await listing_scrape(sdk, "https://test.com", {}, session=session)

    # One POST per year: previous, current, next
    assert session.post.call_count == 3
    assert len(detail_urls) == 1
    assert detail_urls[0]["url"] == "https://www.waynecountymi.gov/meeting-detail"
    assert detail_urls[0]["context"]["isCancelled"] == "False"


@pytest.mark.asyncio
async def test_listing_scraper_dedupes_urls():
    """Duplicate detail links across items should only be enqueued once"""
    from harambe_scrapers.extractor.wayne_commission.listing import (
        scrape as listing_scrape,
    )

    item = {
        "CalendarId": "cal-1",
        "Id": "item-1",
        "MainContentId": "item-1",
        "Name": "Meeting",
        "DateTime": "1/8/2026 10:00:00 AM",
    }
    items_response = {"success": True, "data": [{"Items": [item, dict(item)]}]}
    empty_items_response = {"success": True, "data": []}

    session = MagicMock()

    def fake_get(url, **kwargs):
        if "County-Calendar" in url:
            return make_response(text="<html></html>")
        if "getcalendars" in url:
            return make_response(
                json_data={"success": True, "data": [{"Id": "cal-1", "Label": "X"}]}
            )
        if "contentinfo" in url:
            return make_response(
                json_data={
                    "success": True,
                    "data": {"Link": "https://example.com/same", "IsCancelled": False},
                }
            )
        raise AssertionError(f"Unexpected GET {url}")

    post_responses = iter([empty_items_response, items_response, empty_items_response])
    session.get.side_effect = fake_get
    session.post.side_effect = lambda url, **kwargs: make_response(
        json_data=next(post_responses)
    )

    detail_urls = []
    with patch(
        "harambe_scrapers.extractor.wayne_commission.listing."
        "ITEM_REQUEST_DELAY_SECONDS",
        0,
    ):
        await listing_scrape(
            ListingSDK(detail_urls), "https://test.com", {}, session=session
        )

    assert len(detail_urls) == 1


@pytest.mark.asyncio
async def test_detail_scraper_with_html_fixture():
    """Test detail scraper extracts all data correctly from real HTML fixture"""
    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    fixture_path = Path(__file__).parent / "files" / "wayne_commission.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    session = MagicMock()
    session.get.return_value = make_response(text=html_content)

    sdk = DetailSDK()
    context = {"isCancelled": "False"}

    await detail_scrape(sdk, "https://test.com", context, session=session)

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
async def test_detail_scraper_cancelled_context():
    """Cancelled context flag should carry through to the saved data"""
    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    fixture_path = Path(__file__).parent / "files" / "wayne_commission.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    session = MagicMock()
    session.get.return_value = make_response(text=html_content)

    sdk = DetailSDK()
    await detail_scrape(
        sdk, "https://test.com", {"isCancelled": "True"}, session=session
    )

    assert sdk.data is not None
    assert sdk.data["is_cancelled"] is True


@pytest.mark.asyncio
async def test_detail_scraper_plain_text_zoom_and_cancellation():
    """Zoom URLs in plain text become links; cancellation text sets the flag"""
    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    html_content = """
    <html><body>
    <h1 class="oc-page-title">Ethics Board Meeting - July 15, 2026</h1>
    <ul class="content-details-list minutes-details-list">
      <li><span class="minutes-date">July 15, 2026</span></li>
      <li><span class="field-value">Ethics Board</span></li>
    </ul>
    <div class="meeting-container"><p>Meeting has been canceled.</p></div>
    <div class="meeting-time">Time 9:00 AM - 10:00 AM</div>
    <div class="meeting-address">
      <p>7th Floor Meeting Room, Guardian Building, or join at
      https://zoom.us/j/2234975895.</p>
    </div>
    </body></html>
    """

    session = MagicMock()
    session.get.return_value = make_response(text=html_content)

    sdk = DetailSDK()
    await detail_scrape(
        sdk, "https://test.com", {"isCancelled": "False"}, session=session
    )

    assert sdk.data is not None
    zoom_links = [link for link in sdk.data["links"] if "zoom.us" in link["url"]]
    assert zoom_links == [
        {"title": "Zoom Meeting Link", "url": "https://zoom.us/j/2234975895"}
    ]
    # Cancelled in description text even though the API flag said otherwise
    assert sdk.data["is_cancelled"] is True


@pytest.mark.asyncio
async def test_detail_scraper_start_time_only():
    """Pages that publish only a start time should still produce a meeting"""
    from harambe_scrapers.extractor.wayne_commission.detail import (
        scrape as detail_scrape,
    )

    html_content = """
    <html><body>
    <h1 class="oc-page-title">Seniors and Veterans Affairs Committee</h1>
    <ul class="content-details-list minutes-details-list">
      <li><span class="minutes-date">January 14, 2026</span></li>
      <li><span class="field-value">Seniors and Veterans Affairs Committee</span></li>
    </ul>
    <div class="meeting-container"><p>Standard Meeting</p></div>
    <div class="meeting-time">Time09:30 AM</div>
    <div class="meeting-address">
      <p>Commission Chambers, Mezzanine, Guardian Building, 500 Griswold,
      Detroit, MI, 48226</p>
    </div>
    </body></html>
    """

    session = MagicMock()
    session.get.return_value = make_response(text=html_content)

    sdk = DetailSDK()
    await detail_scrape(
        sdk, "https://test.com", {"isCancelled": "False"}, session=session
    )

    assert sdk.data is not None
    assert "2026-01-14T09:30:00" in sdk.data["start_time"]
    assert sdk.data["end_time"] is None
    assert sdk.data["title"] == "Seniors and Veterans Affairs Committee"
