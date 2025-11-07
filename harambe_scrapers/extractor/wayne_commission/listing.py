import asyncio
import datetime
from typing import Any

import pytz
import requests
from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page


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

    scraper_name = [
        "Ways & Means",
        "Audit",
        "Building Authority",
        "Committee of the Whole",
        "Full Commission",
        "Economic Development",
        "Government Operations",
        "Health and Human Services",
        "Public Safety",
        "Public Services",
        "Election Commission",
        "Local Emergency Planning",
        "Ethics Board",
    ]
    scraperId = []
    print("[LISTING] Starting page navigation...")
    await page.goto(
        "https://www.waynecountymi.gov/Government/County-Calendar",
        wait_until="networkidle",
    )
    print("[LISTING] Page loaded, waiting for calendar filter...")
    await page.wait_for_selector(".calendar-filter", timeout=30000)
    print("[LISTING] Calendar filter found, getting meeting types...")
    meeting_types = await page.query_selector_all(".calendar-filter-list-item")
    print(f"[LISTING] Found {len(meeting_types)} meeting types")
    for type in meeting_types:
        scr_name_element = await type.query_selector(
            "label .calendar-filter-list-item-text"
        )
        scr_name = await scr_name_element.inner_text()
        for scraper in scraper_name:
            if scraper in scr_name:
                ID = await type.get_attribute("data-filter-option-id")
                scraperId.append(ID)
                print(f"[LISTING]   Added filter ID for: {scr_name}")

    print(f"[LISTING] Collected {len(scraperId)} scraper IDs")
    if scraperId:
        # Get the current year
        current_year = datetime.datetime.now().year
        print(
            f"[LISTING] Starting API calls for years {current_year - 1} "
            f"to {current_year}"
        )

        # Loop from one year less than the current year to the current year
        for year in range(current_year - 1, current_year + 1):
            print(f"[LISTING] Processing year {year}...")
            url = "https://www.waynecountymi.gov/ocapi/calendars/getcalendaritems"

            payload = (
                f'{{"LanguageCode":"en-US","Ids":{scraperId},'
                f'"StartDate":"{year}-01-01","EndDate":"{year}-12-31"}}'
            )

            headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "accept-language": (
                    "es-419,es;q=0.9,es-ES;q=0.8,en;q=0.7,en-GB;q=0.6,"
                    "en-US;q=0.5,ar;q=0.4,ur;q=0.3,es-MX;q=0.2"
                ),
                "content-type": "application/json; charset=UTF-8",
                "origin": "https://www.waynecountymi.gov",
                "priority": "u=1, i",
                "referer": "https://www.waynecountymi.gov/Government/County-Calendar",
                "sec-ch-ua": (
                    '"Not)A;Brand";v="8", "Chromium";v="138", '
                    '"Microsoft Edge";v="138"'
                ),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
                ),
                "x-b3-sampled": "1",
                "x-b3-spanid": "8637d509111f36c5",
                "x-b3-traceid": "b1fb5355028f0b97b4d23cd37b51d7ee",
                "x-oracle-apm-ba-version": "1.1.131",
                "x-requested-with": "XMLHttpRequest",
                "Cookie": "ASP.NET_SessionId=h4ooyutzz33houczonxywo0h",
            }

            print(f"[LISTING] Making API POST to {url}")
            response = requests.request("POST", url, headers=headers, data=payload)
            print(f"[LISTING] API Response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                data_items = data.get("data", [])
                print(
                    f"[LISTING] Found {len(data_items)} calendar groups for year {year}"
                )
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

                        payload = {}
                        headers = {
                            "accept": "application/json, text/javascript, */*; q=0.01",
                            "accept-language": (
                                "es-419,es;q=0.9,es-ES;q=0.8,en;q=0.7,en-GB;q=0.6,"
                                "en-US;q=0.5,ar;q=0.4,ur;q=0.3,es-MX;q=0.2"
                            ),
                            "priority": "u=1, i",
                            "referer": (
                                "https://www.waynecountymi.gov/Government/"
                                "County-Calendar"
                            ),
                            "sec-ch-ua": (
                                '"Not)A;Brand";v="8", "Chromium";v="138", '
                                '"Microsoft Edge";v="138"'
                            ),
                            "sec-ch-ua-mobile": "?0",
                            "sec-ch-ua-platform": '"Windows"',
                            "sec-fetch-dest": "empty",
                            "sec-fetch-mode": "cors",
                            "sec-fetch-site": "same-origin",
                            "user-agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
                            ),
                            "x-b3-sampled": "1",
                            "x-b3-spanid": "b976fbfea423163d",
                            "x-b3-traceid": "be91badf5d062cf9732c40defae7b6b0",
                            "x-oracle-apm-ba-version": "1.1.131",
                            "x-requested-with": "XMLHttpRequest",
                            "Cookie": "ASP.NET_SessionId=h4ooyutzz33houczonxywo0h",
                        }

                        response = requests.request(
                            "GET", url, headers=headers, data=payload
                        )
                        if response.status_code == 200:
                            meeting_data = response.json()
                            meeting = meeting_data.get("data", {})
                            meeting_link = meeting.get("Link")
                            if meeting_link:
                                is_cancelled = (
                                    False
                                    if meeting.get("IsCancelled") is False
                                    else True
                                )

                                await sdk.enqueue(
                                    meeting_link,
                                    context={"isCancelled": f"{is_cancelled}"},
                                )
                                meetings_processed += 1
                                if meetings_processed % 20 == 0:
                                    print(
                                        f"[LISTING]   ✓ Enqueued {meetings_processed} "
                                        f"meeting URLs so far..."
                                    )
                        else:
                            print(
                                f"[LISTING]   Warning: Got status "
                                f"{response.status_code} for meeting API call"
                            )
                print(
                    f"[LISTING] Total meetings processed for year {year}: "
                    f"{total_meetings}, URLs enqueued: {meetings_processed}"
                )

    urls_count = len(sdk.detail_urls) if hasattr(sdk, "detail_urls") else "unknown"
    print(f"[LISTING] Scrape complete! Total URLs enqueued: {urls_count}")


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
