"""Listing stage for the Wayne County Commission scraper.

Collects meeting detail-page URLs from the county's OpenCities calendar
JSON API. The flow mirrors what the calendar widget on
/Government/County-Calendar does in the browser:

1. GET the calendar page and read the combined-calendar widget's entity id
2. GET /ocapi/calendars/getcalendars/{entityId}/{entityType} for the list
   of calendars (Full Commission, each committee, etc.)
3. POST /ocapi/calendars/getcalendaritems for each year's items
4. GET /ocapi/get/contentinfo per item for the detail-page link and
   cancellation status

Everything is plain HTTP — no browser. The site's Akamai bot protection
rejects spoofed browser headers from non-browser clients, so we identify
ourselves honestly instead (see common.py).
"""

import asyncio
import datetime
import re
from typing import Any

from harambe_scrapers.extractor.wayne_commission.common import (
    CALENDAR_PAGE_URL,
    DEFAULT_CALENDAR_ENTITY_ID,
    DEFAULT_CALENDAR_ENTITY_TYPE,
    GET_CALENDAR_ITEMS_URL,
    GET_CALENDARS_URL,
    GET_CONTENT_INFO_URL,
    REQUEST_TIMEOUT,
    create_session,
)

# Delay between per-item contentinfo requests to stay polite
ITEM_REQUEST_DELAY_SECONDS = 0.1


def get_calendar_entity(session) -> tuple[str, str]:
    """Read the combined-calendar widget's entity id/type from the page."""
    try:
        response = session.get(
            CALENDAR_PAGE_URL,
            headers={"Accept": "text/html"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        match = re.search(
            r"data-entity-id=[\"']?([0-9a-fA-F-]+)[\"']?\s+"
            r"data-entity-type=[\"']?(\w+)[\"']?",
            response.text,
        )
        if match:
            return match.group(1), match.group(2)
        print(
            "[LISTING] Could not find calendar widget in page HTML, "
            "falling back to known entity id"
        )
    except Exception as e:
        print(f"[LISTING] Error fetching calendar page ({e}), using fallback id")
    return DEFAULT_CALENDAR_ENTITY_ID, DEFAULT_CALENDAR_ENTITY_TYPE


def get_calendars(session, entity_id: str, entity_type: str) -> list[dict]:
    """Fetch the calendars (Full Commission + committees) for the widget."""
    url = f"{GET_CALENDARS_URL}/{entity_id}/{entity_type}"
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"getcalendars returned success=false: {body}")
    return body.get("data", [])


def get_calendar_items(
    session, calendar_ids: list[str], start_date: str, end_date: str
) -> list[dict]:
    """Fetch calendar items for the given calendars and date range."""
    payload = {
        "LanguageCode": "en-US",
        "Ids": calendar_ids,
        "StartDate": start_date,
        "EndDate": end_date,
    }
    response = session.post(
        GET_CALENDAR_ITEMS_URL, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"getcalendaritems returned success=false: {body}")
    items = []
    for group in body.get("data") or []:
        items.extend(group.get("Items") or [])
    return items


def get_content_info(session, item: dict) -> dict | None:
    """Fetch detail info (link, cancellation status) for a calendar item."""
    now = datetime.datetime.now()
    params = {
        "calendarId": item["CalendarId"],
        "contentId": item["Id"],
        "language": "en-US",
        "currentDateTime": now.strftime("%m/%d/%Y %I:%M:%S %p"),
        "mainContentId": item["MainContentId"],
    }
    response = session.get(GET_CONTENT_INFO_URL, params=params, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        print(
            f"[LISTING]   Warning: Got status {response.status_code} "
            f"for contentinfo call ({item.get('Name')})"
        )
        return None
    body = response.json()
    return body.get("data") or None


async def scrape(
    sdk: Any, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    print(f"[LISTING] Starting listing scrape for URL: {current_url}")
    session = kwargs.get("session") or create_session()

    entity_id, entity_type = get_calendar_entity(session)
    print(f"[LISTING] Calendar widget entity: {entity_id} ({entity_type})")

    calendars = get_calendars(session, entity_id, entity_type)
    calendar_ids = [c["Id"] for c in calendars if c.get("Id")]
    print(f"[LISTING] Found {len(calendar_ids)} calendars:")
    for calendar in calendars:
        print(f"[LISTING]   - {calendar.get('Label')}")

    if not calendar_ids:
        raise RuntimeError("No calendars found for the county calendar widget")

    # Previous year through next year, so late-year scrapes still pick up
    # meetings already booked for January onward.
    current_year = datetime.datetime.now().year
    seen_urls = set()
    enqueued = 0
    for year in range(current_year - 1, current_year + 2):
        items = get_calendar_items(
            session, calendar_ids, f"{year}-01-01", f"{year}-12-31"
        )
        print(f"[LISTING] Year {year}: {len(items)} calendar items")

        for item in items:
            info = get_content_info(session, item)
            await asyncio.sleep(ITEM_REQUEST_DELAY_SECONDS)
            if not info:
                continue
            meeting_link = info.get("Link")
            if not meeting_link or meeting_link in seen_urls:
                continue
            seen_urls.add(meeting_link)
            is_cancelled = info.get("IsCancelled") is not False
            await sdk.enqueue(
                meeting_link,
                context={"isCancelled": f"{is_cancelled}"},
            )
            enqueued += 1
            if enqueued % 20 == 0:
                print(f"[LISTING]   ✓ Enqueued {enqueued} meeting URLs so far...")

    print(f"[LISTING] Scrape complete! Total URLs enqueued: {enqueued}")


if __name__ == "__main__":
    # Minimal manual run: collect and print detail URLs
    class _PrintSDK:
        async def enqueue(self, url, context=None):
            print(url, context)

    asyncio.run(scrape(_PrintSDK(), CALENDAR_PAGE_URL, {}))
