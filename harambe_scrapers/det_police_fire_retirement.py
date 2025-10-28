import asyncio
import json
import hashlib
import re
from typing import Any
from datetime import datetime
from pathlib import Path

from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page
import pytz


# Configuration
START_URL = "https://www.rscd.org/member_resources/board_of_trustees/upcoming_meetings.php"
OUTPUT_DIR = Path("harambe_scrapers/output")
SCRAPER_NAME = "det_police_fire_retirement"
AGENCY_NAME = "Detroit Police & Fire Retirement System"
TIMEZONE = "America/Detroit"


# This is the scrape function from rscd.org-78051171/listing.py - REUSED AS-IS
async def scrape(sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any) -> None:
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

    async def parse_classification(title, description_text):
        title = (title or "").lower()
        description_text = (description_text or "").lower()
        # Define mappings of keywords to classification categories
        classifications = {
            "advisory": "ADVISORY",
            "committee": "COMMITTEE",
            "board": "BOARD",
            "commission": "COMMISION",
            "public meeting": "PUBLIC",
            "policy meeting": "POLICY",
            "community": "COMMUNITY",
            "annual": "ANNUAL",
            "cbo": "CBO",
            "authority": "Authority",
        }
        # First check the title for each keyword
        for keyword, classification in classifications.items():
            if keyword in title or keyword in description_text:
                return classification
        return None

    # Extract the title of the page dynamically
    title_element = await page.query_selector("#post p strong")
    title = ""
    if title_element:
        title_text = await title_element.inner_text()
        title = title_text.split("<br>")[0].strip()  # Extract text before <br>

    # Extract the location dynamically
    location_element = await page.query_selector('#post:has-text("Meeting Location")')
    location_name = ""
    location_address = ""
    if location_element:
        location_text = await location_element.inner_text()
        if "Meeting Location" in location_text:
            location_details = (
                location_text.split("Meeting Location:")[1].strip().split("\n")
            )
            location_name = (
                location_details[0].strip() if len(location_details) > 0 else ""
            )
            location_address = (
                location_details[1].strip() if len(location_details) > 1 else ""
            )

    # Wait for the table containing meeting details
    await page.wait_for_selector("table tbody")

    # Extract rows from the table
    rows = await page.query_selector_all("table tbody tr")

    meetings = []

    # Skip the first row (header row)
    for row in rows[1:]:
        # Extract columns from the row
        columns = await row.query_selector_all("td")

        if len(columns) < 3:
            continue  # Skip rows that don't have enough columns

        # Extract date and status
        date_text = (await columns[0].inner_text()).replace("\n", " ").strip()
        time_text = (await columns[1].inner_text()).replace("\n", " ").strip()
        location_text = await columns[2].inner_text()

        # Normalize AM/PM format
        time_text = time_text.replace("A.M.", "AM").replace("P.M.", "PM")

        # Determine if the meeting is cancelled
        is_cancelled = (
            "CANCELLED" in date_text.upper() or "CANCELLED" in time_text.upper()
        )

        # Parse date and time
        try:
            start_time = None
            if is_cancelled:
                # Remove "CANCELLED" and set default time to 12:00 AM
                date_text = (
                    date_text.replace("CANCELLED", "").replace("CANELLED", "").strip()
                )
                start_time = datetime.strptime(
                    f"{date_text} 12:00 AM", "%B %d, %Y %I:%M %p"
                )
            else:
                start_time = datetime.strptime(
                    f"{date_text.strip()} {time_text.strip()}", "%B %d, %Y %I:%M %p"
                )
        except ValueError as e:
            raise ValueError(f"Error parsing date/time: {e}")

        # Combine row location with current location name
        combined_location_name = (
            f"{location_name}, {location_text.strip()}"
            if location_name
            else location_text.strip()
        )

        # Extract location details
        location = {"name": combined_location_name, "address": location_address}

        classification = await parse_classification(title, "")
        if start_time:
            # Add meeting details to the list
            meetings.append(
                {
                    "title": title,
                    "description": "",
                    "start_time": await change_timezone(start_time.isoformat()),
                    "end_time": None,
                    "time_notes": "",
                    "location": location,
                    "links": [],
                    "is_cancelled": is_cancelled,
                    "is_all_day_event": None,
                    "classification": classification,
                }
            )

    # Save all meetings
    for meeting in meetings:
        await sdk.save_data(meeting)


# Custom observer to collect data
class DataCollector:
    def __init__(self):
        self.data = []

    async def on_save_data(self, data):
        self.data.append(data)
        print(f"  ✓ {data.get('start_time', '')[:10]} - {data.get('title', 'Unknown')}")

    async def on_queue_url(self, url, context, options):
        pass

    async def on_download(self, *args):
        return {}

    async def on_paginate(self, url):
        pass

    async def on_save_cookies(self, cookies):
        pass

    async def on_save_local_storage(self, storage):
        pass


# Main execution
async def main():
    print("=" * 70)
    print("Detroit Police & Fire Retirement System - Board of Trustees")
    print("=" * 70)
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Scraping: {START_URL}")
    print()

    collector = DataCollector()

    try:
        await SDK.run(scrape, START_URL, observer=collector, harness=playwright_harness, headless=True)
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

    # Save results
    print()
    print("=" * 70)
    print(f"COMPLETE: {len(collector.data)} meetings collected")
    print("=" * 70)

    if collector.data:
        output_file = OUTPUT_DIR / f"det_police_fire_retirement_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(output_file, "w") as f:
            json.dump(collector.data, f, indent=2, ensure_ascii=False)

        print(f"✓ Saved to: {output_file}")
        print()
        print("Sample meeting:")
        print("-" * 70)
        print(json.dumps(collector.data[0], indent=2))
    else:
        print("⚠ No meetings collected")


if __name__ == "__main__":
    asyncio.run(main())
