import asyncio
import hashlib
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

# Configuration
START_URL = (
    "https://www.rscd.org/member_resources/board_of_trustees/upcoming_meetings.php"
)
OUTPUT_DIR = Path("harambe_scrapers/output")
SCRAPER_NAME = "det_police_fire_retirement_v2"
AGENCY_NAME = "Detroit Police & Fire Retirement System"
TIMEZONE = "America/Detroit"


def slugify(text):
    """Convert text to URL slug format"""
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def generate_id(name, start_time):
    """Generate cityscrapers.org/id format.

    Format: scraper_name/YYYYMMDDhhmm/x/meeting_name_slug
    """
    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    date_str = dt.strftime("%Y%m%d%H%M")
    name_slug = slugify(name)
    return f"{SCRAPER_NAME}/{date_str}/x/{name_slug}"


def generate_ocd_id(scraper_id):
    """Generate OCD event ID using MD5 hash"""
    hash_obj = hashlib.md5(scraper_id.encode())
    hash_hex = hash_obj.hexdigest()
    # Format as UUID-like string: 8-4-4-4-12
    return (
        f"ocd-event/{hash_hex[:8]}-{hash_hex[8:12]}-{hash_hex[12:16]}-"
        f"{hash_hex[16:20]}-{hash_hex[20:32]}"
    )


def determine_status(is_cancelled, start_time):
    """Determine meeting status based on cancelled flag and start time"""
    if is_cancelled:
        return "canceled"

    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    now = datetime.now(dt.tzinfo)

    if dt > now:
        return "tentative"
    else:
        return "passed"


# This is the scrape function from rscd.org-78051171/listing.py - REUSED AS-IS
async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    page: Page = sdk.page

    async def change_timezone(date):
        timezone = "America/Detroit"
        naive_datetime = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
        tz = pytz.timezone(timezone)
        localized_datetime = tz.localize(naive_datetime)
        iso_format = localized_datetime.strftime("%Y-%m-%dT%H:%M:%S%z")
        # Adjust offset format to include colon
        iso_format_with_colon = iso_format[:-2] + ":" + iso_format[-2:]
        return iso_format_with_colon

    async def parse_classification(title, description_text):
        title = (title or "").lower()
        description_text = (description_text or "").lower()
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
        for keyword, classification in classifications.items():
            if keyword in title or keyword in description_text:
                return classification
        return None

    title_element = await page.query_selector("#post p strong")
    title = ""
    if title_element:
        title_text = await title_element.inner_text()
        title = title_text.split("<br>")[0].strip()  # Extract text before <br>

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

    await page.wait_for_selector("table tbody")
    rows = await page.query_selector_all("table tbody tr")

    meetings = []

    # Skip header row
    for row in rows[1:]:
        columns = await row.query_selector_all("td")

        if len(columns) < 3:
            continue

        date_text = (await columns[0].inner_text()).replace("\n", " ").strip()
        time_text = (await columns[1].inner_text()).replace("\n", " ").strip()
        location_text = await columns[2].inner_text()

        time_text = time_text.replace("A.M.", "AM").replace("P.M.", "PM")

        is_cancelled = (
            "CANCELLED" in date_text.upper() or "CANCELLED" in time_text.upper()
        )

        try:
            start_time = None
            if is_cancelled:
                # Remove CANCELLED and default to 12:00 AM
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

        combined_location_name = (
            f"{location_name}, {location_text.strip()}"
            if location_name
            else location_text.strip()
        )

        classification = await parse_classification(title, "")
        if start_time:
            start_time_iso = await change_timezone(start_time.isoformat())
            scraper_id = generate_id(title, start_time_iso)
            ocd_id = generate_ocd_id(scraper_id)
            status = determine_status(is_cancelled, start_time_iso)

            # All-day if time is midnight
            all_day = start_time.time().hour == 0 and start_time.time().minute == 0

            clean_title = " ".join(title.split())

            classification_map = {
                "BOARD": "Board",
                "COMMITTEE": "Committee",
                "COMMISSION": "Commission",
                "ADVISORY": "Advisory Committee",
            }
            proper_classification = classification_map.get(classification, "Board")

            meeting = {
                "_type": "event",
                "_id": ocd_id,
                "updated_at": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "name": clean_title,
                "description": "",
                "classification": proper_classification,
                "status": status,
                "all_day": all_day,
                "start_time": start_time_iso,
                "end_time": None,
                "timezone": TIMEZONE,
                "location": {
                    "url": "",
                    "name": combined_location_name,
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
                    "cityscrapers.org/address": location_address,
                },
            }

            meetings.append(meeting)

    for meeting in meetings:
        await sdk.save_data(meeting)


async def main():
    print("=" * 70)
    print("Detroit Police & Fire Retirement System - Board of Trustees")
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
        output_file = (
            OUTPUT_DIR
            / f"det_police_fire_retirement_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
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
