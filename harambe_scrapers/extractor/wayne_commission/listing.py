import asyncio
import datetime
from typing import Any

import pytz
import requests
from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page

CALENDAR_URL = "https://www.waynecountymi.gov/Government/County-Calendar"

# Fallback user-agent, only used if the live page cannot report its own.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


async def _session_from_page(page: Page) -> tuple[str, str]:
    """Extract a live ``Cookie`` header and user-agent from the Playwright page.

    The calendar page must already be loaded so the Oracle backend has issued a
    fresh ``ASP.NET_SessionId``. We reuse that live session (and the browser's
    real user-agent) for the ``requests`` calls to the ocapi endpoints instead
    of shipping a hardcoded cookie that goes stale the moment the session dies.
    """
    cookie_pairs = []
    try:
        cookies = await page.context.cookies()
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value is not None:
                cookie_pairs.append(f"{name}={value}")
    except Exception as e:  # pragma: no cover - defensive
        print(f"[LISTING] Warning: could not read cookies from page: {e}")

    cookie_header = "; ".join(cookie_pairs)

    if "ASP.NET_SessionId" not in cookie_header:
        print(
            "[LISTING] Warning: no ASP.NET_SessionId cookie found on the live "
            "page session. The calendar API may reject the request."
        )

    try:
        user_agent = await page.evaluate("() => navigator.userAgent")
    except Exception:  # pragma: no cover - defensive
        user_agent = None

    return cookie_header, user_agent or DEFAULT_USER_AGENT


def _build_headers(
    cookie_header: str, user_agent: str, json_body: bool
) -> dict[str, str]:
    """Build request headers for the ocapi calls using a live session.

    Frozen Oracle APM trace headers (``x-b3-*``, ``x-oracle-apm-ba-version``)
    are intentionally omitted -- they were request-specific trace ids captured
    once and are not required by the endpoint.
    """
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "origin": "https://www.waynecountymi.gov",
        "referer": CALENDAR_URL,
        "user-agent": user_agent,
        "x-requested-with": "XMLHttpRequest",
    }
    if json_body:
        headers["content-type"] = "application/json; charset=UTF-8"
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    print(f"[LISTING] Starting listing scrape for URL: {current_url}")
    page: Page = sdk.page

    async def change_timezone(date):
        timezone = "America/Detroit"

        # Convert string to naive datetime object
        naive_datetime = datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")

        # Get the timezone object
        tz = pytz.timezone(timezone)

        # Add timezone to the naive datetime
        localized_datetime = tz.localize(naive_datetime)

        # Format the localized datetime as ISO 8601 string
        iso_format = localized_datetime.strftime("%Y-%m-%dT%H:%M:%S%z")
        # Adjusting the offset format to include a colon
        iso_format_with_colon = iso_format[:-2] + ":" + iso_format[-2:]
        return iso_format_with_colon

    def parse_classification(title):
        title = (title or "").lower()

        # Define mappings of keywords to classification categories
        classifications = {
            "committee": "COMMITTEE",
            "board": "BOARD",
            "commission": "COMMISION",
            "public meeting": "PUBLIC",
            "policy meeting": "POLICY",
            "community": "COMMUNITY",
            "annual": "ANNUAL",
            "cbo": "CBO",
            "advisory": "ADVISORY",
            "council": "COUNCIL",
        }

        # First check the title for each keyword
        for keyword, classification in classifications.items():
            if keyword in title:
                return classification

        return None

    scraperId = []
    print("[LISTING] Starting page navigation...")
    await page.goto(CALENDAR_URL)
    print("[LISTING] Page loaded, waiting for calendar filter...")
    await page.wait_for_selector(".calendar-filter")
    print("[LISTING] Calendar filter found, getting meeting types...")
    meeting_types = await page.query_selector_all(".calendar-filter-list-item")
    print(f"[LISTING] Found {len(meeting_types)} meeting types")
    for type in meeting_types:
        ID = await type.get_attribute("data-filter-option-id")
        if ID:
            scraperId.append(ID)

    print(f"[LISTING] Collected {len(scraperId)} scraper IDs")

    # Fail loudly if the calendar page structure changed and no meeting-type
    # filters were found. Continuing would silently produce zero meetings.
    if not scraperId:
        raise RuntimeError(
            "[LISTING] No meeting-type filters found on the calendar page. "
            "The '.calendar-filter-list-item' markup may have changed, or the "
            "page failed to load. Aborting so the failure is visible instead "
            "of silently scraping nothing."
        )

    # Pull a *live* session from the Playwright page instead of shipping a
    # hardcoded ASP.NET_SessionId that goes stale. The page has already loaded
    # the calendar above, so the Oracle backend has issued us a valid session.
    cookie_header, user_agent = await _session_from_page(page)
    print(
        f"[LISTING] Using live session cookie "
        f"({'present' if 'ASP.NET_SessionId' in cookie_header else 'MISSING'})"
    )

    # Get the current year
    current_year = datetime.datetime.now().year
    print(
        f"[LISTING] Starting API calls for years {current_year - 1} "
        f"to {current_year}"
    )

    total_enqueued = 0

    # Loop from one year less than the current year to the current year
    for year in range(current_year - 1, current_year + 1):
        print(f"[LISTING] Processing year {year}...")
        url = "https://www.waynecountymi.gov/ocapi/calendars/getcalendaritems"

        payload = (
            f'{{"LanguageCode":"en-US","Ids":{scraperId},'
            f'"StartDate":"{year}-01-01","EndDate":"{year}-12-31"}}'
        )

        headers = _build_headers(cookie_header, user_agent, json_body=True)

        print(f"[LISTING] Making API POST to {url}")
        response = requests.request("POST", url, headers=headers, data=payload)
        print(f"[LISTING] API Response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            data_items = data.get("data", [])
            print(f"[LISTING] Found {len(data_items)} calendar groups for year {year}")
            total_meetings = 0
            meetings_processed = 0
            for idx, meeting in enumerate(data_items):
                meeting_items = meeting.get("Items", [])
                total_meetings += len(meeting_items)
                if len(meeting_items) > 0:  # Only print if there are items
                    print(
                        f"[LISTING] Processing calendar group {idx + 1}/"
                        f"{len(data_items)}, with {len(meeting_items)} items"
                    )
                for item_idx, item in enumerate(meeting_items):
                    calendarId = item["CalendarId"]
                    contentId = item["Id"]
                    mainContentId = item["MainContentId"]
                    itemDate = item["DateTime"]
                    # Note: itemDate is used for display/logging purposes

                    # Get the current date and time
                    now = datetime.datetime.now()

                    # Format the date and time in the desired format
                    formatted_date_time = now.strftime("%m/%d/%Y%%20%I:%M:%S%%20%p")

                    url = (
                        f"https://www.waynecountymi.gov/ocapi/get/contentinfo?"
                        f"calendarId={calendarId}&contentId={contentId}&"
                        f"language=en-US&currentDateTime={formatted_date_time}&"
                        f"mainContentId={mainContentId}"
                    )

                    # Print progress every 5 items or on first/last item
                    if (
                        item_idx == 0
                        or item_idx % 5 == 0
                        or item_idx == len(meeting_items) - 1
                    ):
                        print(
                            f"[LISTING]   Processing item {item_idx + 1}/"
                            f"{len(meeting_items)} - Date: {itemDate}"
                        )

                    headers = _build_headers(cookie_header, user_agent, json_body=False)

                    response = requests.request("GET", url, headers=headers)
                    if response.status_code == 200:
                        meeting_data = response.json()
                        meeting = meeting_data.get("data", {})
                        meeting_link = meeting.get("Link")
                        if meeting_link:
                            is_cancelled = (
                                False if meeting.get("IsCancelled") is False else True
                            )

                            await sdk.enqueue(
                                meeting_link,
                                context={"isCancelled": f"{is_cancelled}"},
                            )
                            meetings_processed += 1
                            total_enqueued += 1
                            if meetings_processed % 20 == 0:
                                print(
                                    f"[LISTING]   ✓ Enqueued {meetings_processed} "
                                    f"meeting URLs so far..."
                                )
                    else:
                        print(
                            f"[LISTING]   Warning: Got status "
                            f"{response.status_code} for meeting content API call"
                        )
            print(
                f"[LISTING] Total meetings processed for year {year}: "
                f"{total_meetings}, URLs enqueued: {meetings_processed}"
            )
        else:
            # A non-200 from the calendar API means the session/headers were
            # rejected or the endpoint moved. Surface it loudly rather than
            # skipping the whole year silently.
            print(
                f"[LISTING] ERROR: calendar API returned status "
                f"{response.status_code} for year {year}. "
                f"Response body (truncated): {response.text[:500]}"
            )

    urls_count = len(sdk.detail_urls) if hasattr(sdk, "detail_urls") else total_enqueued
    print(f"[LISTING] Scrape complete! Total URLs enqueued: {urls_count}")

    # Fail loudly if the whole run produced nothing. This is almost always a
    # broken session, changed API contract, or blocked request -- not a genuine
    # "no meetings scheduled" result -- and a silent empty output quietly
    # degrades county-wide coverage until someone notices.
    if total_enqueued == 0:
        raise RuntimeError(
            "[LISTING] Enqueued 0 meetings across all years. The calendar API "
            "returned no usable meeting links -- likely a rejected session, a "
            "changed API contract, or a blocked request. Aborting so the "
            "failure is visible instead of silently producing an empty feed."
        )


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            "https://www.waynecountymi.gov/Government/County-Calendar",
            headless=False,
            harness=playwright_harness,
            schema={
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": (
                                    "The URL link to the document or resource "
                                    "related to the meeting."
                                ),
                            },
                            "title": {
                                "type": "string",
                                "description": (
                                    "The title or label for the link, providing "
                                    "context for what the document or resource is."
                                ),
                            },
                        },
                        "description": (
                            "List of dictionaries with title and href for "
                            "relevant links (eg. agenda, minutes). Empty list "
                            "if no relevant links are available."
                        ),
                    },
                    "description": (
                        "A list of links related to the meeting, such as "
                        "references to meeting agendas, minutes, or other documents."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Title of the meeting (e.g., 'Regular council meeting')."
                    ),
                },
                "end_time": {
                    "type": "datetime",
                    "description": (
                        "The scheduled end time of the meeting. Often unavailable."
                    ),
                },
                "location": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "The name of the venue where the meeting will "
                                "take place."
                            ),
                        },
                        "address": {
                            "type": "string",
                            "description": (
                                "The full address of the meeting venue. Sometimes, "
                                "it will include an online meeting link if the "
                                "physical location is not provided."
                            ),
                        },
                    },
                    "description": (
                        "Details about the meeting's location, including the "
                        "name and address of the venue."
                    ),
                },
                "start_time": {
                    "type": "datetime",
                    "description": "The scheduled start time of the meeting.",
                },
                "time_notes": {
                    "type": "string",
                    "description": (
                        "If needed, a note about the meeting time. Empty string "
                        "otherwise. Typically empty string."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Specific meeting description; empty string if unavailable."
                    ),
                },
                "is_cancelled": {
                    "type": "boolean",
                    "description": (
                        "If there are any fields in the site that shows that "
                        "the meeting has been cancelled True."
                    ),
                },
                "classification": {
                    "type": "string",
                    "expression": "UPPER(classification)",
                    "description": (
                        "The classification of the meeting, such as "
                        "'Regular Business Meeting', 'Norcross Development Authority', "
                        "'City Council Work Session' etc."
                    ),
                },
                "is_all_day_event": {
                    "type": "boolean",
                    "description": "Boolean for all-day events. Typically False.",
                },
            },
        )
    )
