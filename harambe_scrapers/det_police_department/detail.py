import asyncio
import re
from typing import Any

from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page

# https://github.com/City-Bureau/city-scrapers-det/blob/main/city_scrapers/spiders/det_police_department.py


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    from datetime import datetime

    import pytz

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

    async def extract_and_format_date(original_datetime_str, time):
        # Normalize the new_time_str by adding a space if it's missing before AM/PM
        new_time_str = (
            re.sub("([APap][Mm])$", " \\1", time)
            .replace("Noon", "PM")
            .replace("p.m.", "PM")
            .replace("pm", "PM")
        )
        if "-" in time:
            date_part = original_datetime_str.split("T")[0]  # '2022-11-14'

            # Parse the time range
            time = time.replace("am", " am").replace("pm", " pm").replace("  ", " ")
            start_time_str, end_time_str = time.split("-")
            start_time = datetime.strptime(start_time_str.strip(), "%I:%M %p")
            end_time = datetime.strptime(end_time_str.strip(), "%I:%M %p")

            # Combine date with times
            start_datetime = f"{date_part}T{start_time.strftime('%H:%M:%S')}"
            end_datetime = f"{date_part}T{end_time.strftime('%H:%M:%S')}"
            print(start_datetime, end_datetime)
            return (start_datetime, end_datetime)
        # Parse the original datetime string into a datetime object
        datetime_obj = datetime.strptime(original_datetime_str, "%Y-%m-%dT%H:%M:%SZ")

        # Parse the new time string into a time object

        # Remove spaces around the colon using regex
        cleaned_time_str = re.sub("\\s*:\\s*", ":", new_time_str)
        # Parse the cleaned string
        try:
            new_time_obj = datetime.strptime(cleaned_time_str, "%I:%M %p").time()
            print(new_time_obj)
        except ValueError as e:
            new_time_obj = datetime.strptime("12:00 PM", "%I:%M %p").time()
            print(f"Error parsing time '{new_time_str}': {e}")

        # Combine the original date with the new time
        updated_datetime_obj = datetime_obj.replace(
            hour=new_time_obj.hour,
            minute=new_time_obj.minute,
            second=new_time_obj.second,
        )

        # Convert back to the desired string format
        updated_datetime_str = updated_datetime_obj.strftime("%Y-%m-%dT%H:%M:%S")
        return (updated_datetime_str, None)

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
        }

        # First check the title for each keyword
        for keyword, classification in classifications.items():
            if keyword in title or keyword in description_text:
                return classification

        return None

    async def parse_links(item):
        anchors = await item.query_selector_all(".file a")
        links = []
        for anchor in anchors:
            href = await anchor.get_attribute("href") or ""
            title = await anchor.text_content() or ""
            title = re.sub("\\s+", " ", title).strip()
            if "agenda" in title.lower():
                title = "Agenda"
            elif "minute" in title.lower():
                title = "Minutes"
            else:
                title = title.replace(".pdf", "")
            links.append({"url": "https://detroitmi.gov" + href, "title": title})
        return links

    page: Page = sdk.page
    await page.wait_for_selector(".title span")
    title_element = await page.query_selector(".title span")
    title = await title_element.inner_text()
    date_element = await page.query_selector(".date time")
    date_text = await date_element.get_attribute("datetime")
    time_element = await page.query_selector("article.time")
    time_text = await time_element.inner_text()

    start_time, end_time = await extract_and_format_date(date_text, time_text.strip())
    description_element = await page.query_selector(".description")
    description_text = (
        await description_element.inner_text() if description_element else ""
    )
    location_name_element = await page.query_selector("strong span")
    location_address_element = await page.query_selector(".location.teaser.clearfix")
    location = None
    if location_address_element:
        location_name = await page.locator("article.contact-info span").inner_text()

        # Select the address (text after <br>)
        address_locator = page.locator("article.contact-info")
        address_text = (
            (await address_locator.inner_text()).split("\n")[-1].split(" (")[0].strip()
        )
        location = {"name": location_name, "address": address_text}
    elif await page.query_selector('p strong:has-text("Location")'):
        location_name_element = await page.query_selector(
            'p strong:has-text("Location")'
        )
        if location_name_element:
            location_text = await location_name_element.inner_text()
            if location_text:
                location_name, address_text = (None, None)
                location_text = location_text.replace("Location:", "").strip()
                if "," in location_text:
                    location_name, address_text = location_text.split(",", 1)
                else:
                    location_name = location_text
                location = {"name": location_name, "address": address_text}
    else:
        desc_loc_element = await page.query_selector(
            'article.description > p:first-child:has-text("at")'
        )
        if desc_loc_element:
            location_text = await desc_loc_element.inner_text()
            if location_text:
                if "at" in location_text:
                    location_text = location_text.rsplit(" at", 1)[-1]
                    location_name, address_text = (None, None)
                    location_text = location_text.replace("Location:", "").strip()
                    if "," in location_text:
                        location_name, address_text = location_text.split(",", 1)
                    else:
                        location_name = location_text
                    location = {"name": location_name, "address": address_text}
    if (
        "cancel" in description_text.lower()
        or "no meeting" in description_text.lower()
        or "cancel" in title.lower()
    ):
        is_cancelled = True
    else:
        is_cancelled = False

    meeting = {
        "title": title,
        "description": description_text,
        "classification": await parse_classification(title, description_text),
        "start_time": await change_timezone(start_time),
        "end_time": await change_timezone(end_time) if end_time else None,
        "time_notes": None,
        "is_all_day_event": None,
        "location": location,
        "links": await parse_links(page),
    }
    meeting["is_cancelled"] = is_cancelled
    await sdk.save_data(meeting)


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            "https://detroitmi.gov/events/bopc-budget-committee-meeting-april-1-2025",
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
                            "List of dictionaries with title and href for relevant "
                            "links (eg. agenda, minutes). Empty list if no relevant "
                            "links are available."
                        ),
                    },
                    "description": (
                        "A list of links related to the meeting, such as references "
                        "to meeting agendas, minutes, or other documents."
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
                                "physical location is not provided. "
                            ),
                        },
                    },
                    "description": (
                        "Details about the meeting's location, including the name "
                        "and address of the venue."
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
                        "If there are any fields in the site that shows that the "
                        "meeting has been cancelled True."
                    ),
                },
                "classification": {
                    "type": "string",
                    "expression": "UPPER(classification)",
                    "description": (
                        "The classification of the meeting, such as 'Regular "
                        "Business Meeting', 'Norcross Development Authority', "
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
