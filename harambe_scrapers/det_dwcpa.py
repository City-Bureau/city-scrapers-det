import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page

from harambe_scrapers.observers import DataCollector
from harambe_scrapers.utils import create_ocd_event

# Configuration
START_URL = "https://portdetroit.com/board-meeting-schedule/"
OUTPUT_DIR = Path("harambe_scrapers/output")
SCRAPER_NAME = "det_dwcpa_v2"
AGENCY_NAME = "Detroit Wayne County Port Authority"
TIMEZONE = "America/Detroit"


# This is the scrape function from portdetroit.com-24b335a8/listing.py - REUSED AS-IS
async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    page: Page = sdk.page

    async def change_timezone(date):
        timezone = "America/Detroit"
        # Convert string to naive datetime object
        naive_datetime = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
        # Get the timezone object
        tz = pytz.timezone(timezone)
        # Add timezone to the naive datetime
        localized_datetime = tz.localize(naive_datetime)
        # Format the localized datetime as ISO 8601 string
        iso_format = localized_datetime.strftime("%Y-%m-%dT%H:%M:%S%z")
        # Adjusting the offset format to include a colon
        iso_format_with_colon = iso_format[:-2] + ":" + iso_format[-2:]
        return iso_format_with_colon

    async def parse_classification(title):
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

    # Navigate to the intended page
    await page.goto("https://portdetroit.com/board-meeting-schedule/")
    await page.wait_for_selector("div:has-text('Meeting Schedule')")

    # Extract title dynamically
    # header_element = await page.query_selector("h2:has-text('Board Meeting')")
    header_element = await page.query_selector(".heading-text.el-text h2.h1 span")
    title = await header_element.inner_text() if header_element else "Board Meeting"

    classification = await parse_classification(title)

    # Extract meeting details dynamically
    meeting_elements = await page.query_selector_all(
        "div:has-text('Meeting Schedule') h2.h4 span"
    )

    # Extract year dynamically
    year_element = await page.query_selector("div h2:has-text('Meeting Schedule')")
    year_text = await year_element.inner_text() if year_element else ""
    year_match = re.search("\\d{4}", year_text)
    year = year_match.group() if year_match else ""

    # Extract location dynamically
    location_element = await page.query_selector("div:has-text('Meeting Schedule') em")
    location_text = await location_element.inner_text() if location_element else ""

    # Parse location into name and address
    location_parts = location_text.split(" at ")
    location_name = (
        location_parts[1].replace("located", "").strip()
        if len(location_parts) > 1
        else None
    )
    location_address = (
        location_parts[2].replace(", beginning", "").strip()
        if len(location_parts) > 2
        else None
    )

    for element in meeting_elements:
        meeting_text = await element.inner_text()

        # Extract date and time using regex
        date_match = re.search("(\\w+),\\s+(\\w+\\s+\\d+)", meeting_text)
        time_match = re.search(
            "(\\d{1,2}):(\\d{2})\\s*(am|pm)", location_text, re.IGNORECASE
        )

        if date_match:
            # Parse the date
            raw_date = date_match.group(2) + f", {year}"
            clean_date = re.sub("(\\d+)(st|nd|rd|th)", "\\1", raw_date)
            parsed_date = datetime.strptime(clean_date, "%B %d, %Y")
        else:
            parsed_date = None

        if time_match:
            # Parse the time
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            am_pm = time_match.group(3).lower()
            if am_pm == "pm" and hour != 12:
                hour += 12
            if am_pm == "am" and hour == 12:
                hour = 0
            parsed_time = f"{hour:02d}:{minute:02d}:00"
        else:
            parsed_time = "09:00:00"  # Default time if not found

        if parsed_date:
            start_time = f"{parsed_date.strftime('%Y-%m-%d')}T{parsed_time}"
            start_time = await change_timezone(start_time)

            # All-day if time is midnight
            all_day = parsed_time == "00:00:00"

            # Map classification to proper case
            classification_map = {
                "BOARD": "Board",
                "COMMITTEE": "Committee",
                "COMMISSION": "Commission",
                "ADVISORY": "Advisory Committee",
            }
            proper_classification = classification_map.get(classification, "Board")

            # Use shared utility to create OCD event
            meeting = create_ocd_event(
                title=title,
                start_time=start_time,
                scraper_name=SCRAPER_NAME,
                agency_name=AGENCY_NAME,
                timezone=TIMEZONE,
                description="",
                classification=proper_classification,
                location={"name": location_name, "address": location_address},
                links=[],
                end_time=None,
                is_cancelled=None,
                source_url=START_URL,
                all_day=all_day,
            )

            await sdk.save_data(meeting)


async def main():
    print("=" * 70)
    print("Detroit Wayne County Port Authority - Board Meeting Schedule")
    print("=" * 70)
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Scraping: {START_URL}")
    print()

    observer = DataCollector(scraper_name=SCRAPER_NAME, timezone=TIMEZONE)

    try:
        await SDK.run(
            scrape,
            START_URL,
            observer=observer,
            harness=playwright_harness,
            headless=True,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()

    print()
    print("=" * 70)
    print(f"COMPLETE: {len(observer.data)} meetings collected")
    print("=" * 70)

    if observer.data:
        output_file = OUTPUT_DIR / f"det_dwcpa_{datetime.now():%Y%m%d_%H%M%S}.json"
        # Write JSONLINES format - one JSON object per line
        with open(output_file, "w") as f:
            for meeting in observer.data:
                # Remove __url field if it exists (added by Harambe SDK)
                if "__url" in meeting:
                    del meeting["__url"]
                f.write(json.dumps(meeting, ensure_ascii=False) + "\n")

        print(f"✓ Saved local backup to: {output_file}")

        if observer.azure_client:
            print(f"✓ Uploaded {len(observer.data)} meetings to Azure Blob Storage")

        print()
        print("Sample meeting:")
        print("-" * 70)
        print(json.dumps(observer.data[0], indent=2))
    else:
        print("⚠ No meetings collected")


if __name__ == "__main__":
    asyncio.run(main())
