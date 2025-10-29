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


# Helper functions for data transformation
def slugify(text):
    """Convert text to URL slug format"""
    text = str(text).lower().strip()
    # Remove special characters
    text = re.sub(r"[^\w\s-]", "", text)
    # Replace whitespace and underscores with hyphens
    text = re.sub(r"[\s_]+", "_", text)
    # Remove leading/trailing hyphens
    text = re.sub(r"^-+|-+$", "", text)
    return text


def generate_id(name, start_time):
    """Generate cityscrapers.org/id format.

    Format: scraper_name/YYYYMMDDhhmm/x/meeting_name_slug
    """
    # Parse datetime from ISO format
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

    # Parse start time and compare with current time
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

        # Check if there's a link to a detail page in the row
        detail_link_element = await row.query_selector("a")
        detail_url = None
        if detail_link_element:
            detail_url = await detail_link_element.get_attribute("href")
            # Make absolute URL if relative
            if detail_url and not detail_url.startswith("http"):
                base_url = "/".join(current_url.split("/")[:-1])
                detail_url = f"{base_url}/{detail_url}"

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

        classification = await parse_classification(title, "")
        if start_time:
            # Convert to ISO format with timezone
            start_time_iso = await change_timezone(start_time.isoformat())

            # Generate IDs
            scraper_id = generate_id(title, start_time_iso)
            ocd_id = generate_ocd_id(scraper_id)

            # Determine status
            status = determine_status(is_cancelled, start_time_iso)

            # Check if all-day event (time is midnight)
            all_day = start_time.time().hour == 0 and start_time.time().minute == 0

            # Clean up title - remove extra whitespace and newlines
            clean_title = " ".join(title.split())

            # Map classification to proper case
            classification_map = {
                "BOARD": "Board",
                "COMMITTEE": "Committee",
                "COMMISSION": "Commission",
                "ADVISORY": "Advisory Committee",
            }
            proper_classification = classification_map.get(classification, "Board")

            # Build meeting in Azure blob format
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

            # If detail page URL exists, enqueue it with meeting context
            if detail_url:
                await sdk.enqueue(detail_url, context=meeting)
            else:
                # No detail page, save meeting as-is
                meetings.append(meeting)

    # Save all meetings without detail pages
    for meeting in meetings:
        await sdk.save_data(meeting)


# Detail scraper - processes detail pages to extract links/documents
async def scrape_detail(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    """Scrape detail page to extract links and merge with meeting data from context"""
    page: Page = sdk.page

    # Get the meeting data passed from listing scraper
    meeting = context.copy()

    # Try to extract links from detail page
    links = []

    # Look for links in common patterns
    link_elements = await page.query_selector_all(
        "a[href$='.pdf'], a[href*='agenda'], a[href*='minutes'], a[href*='document']"
    )

    for link_element in link_elements:
        url = await link_element.get_attribute("href")
        title = await link_element.inner_text()

        if url and title:
            # Make absolute URL if relative
            if not url.startswith("http"):
                base_url = "/".join(current_url.split("/")[:3])
                url = f"{base_url}/{url.lstrip('/')}"

            links.append({"note": title.strip(), "url": url})

    # Update meeting with extracted links
    if links:
        meeting["links"] = links
        # Also add to documents if PDFs
        meeting["documents"] = []  # Keep empty for now, backend will process

    # Save the complete meeting with links
    await sdk.save_data(meeting)


# Main execution
async def main():
    print("=" * 70)
    print("Detroit Police & Fire Retirement System - Board of Trustees")
    print("=" * 70)
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Scraping: {START_URL}")
    print()

    observer = DataCollector(scraper_name=SCRAPER_NAME, timezone=TIMEZONE)

    # Router function to handle both listing and detail pages
    async def scrape_router(
        sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
    ) -> None:
        # If context has meeting data, it's a detail page
        if context and "_type" in context:
            await scrape_detail(sdk, current_url, context, *args, **kwargs)
        else:
            # Otherwise it's the listing page
            await scrape(sdk, current_url, context, *args, **kwargs)

    try:
        await SDK.run(
            scrape_router,
            START_URL,
            observer=observer,
            harness=playwright_harness,
            headless=True,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()

    # Save results summary
    print()
    print("=" * 70)
    print(f"COMPLETE: {len(observer.data)} meetings collected")
    print("=" * 70)

    if observer.data:
        # Save local backup file
        output_file = (
            OUTPUT_DIR
            / f"det_police_fire_retirement_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        with open(output_file, "w") as f:
            json.dump(observer.data, f, indent=2, ensure_ascii=False)

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
