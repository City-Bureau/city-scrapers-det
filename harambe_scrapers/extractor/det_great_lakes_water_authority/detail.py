import asyncio
from typing import Any

from harambe import SDK
from harambe.contrib import soup_harness
from playwright.async_api import Page, TimeoutError

# https://github.com/City-Bureau/city-scrapers-det/blob/main/city_scrapers/spiders/det_great_lakes_water_authority.py


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

    async def parse_links(item):
        anchors = await item.query_selector_all(
            "table:nth-of-type(4) tr:nth-of-type(1) a:nth-of-type(1)"
        )
        links = []
        for anchor in anchors:
            href = await anchor.get_attribute("href") or ""
            title = await anchor.text_content() or ""
            if "agenda" in title.lower():
                title = "Agenda"
            elif "minute" in title.lower():
                title = "Minutes"
            elif "Not\xa0available" in title:
                continue
            links.append(
                {"url": "https://glwater.legistar.com/" + href, "title": title}
            )
        return links

    async def extract_and_format_date(date_string, year):
        # Parsing the date part
        date_part, time_part = date_string.split(" @ ")
        try:
            date = date = (
                datetime.strptime(f"{date_part} {year}", "%B %d %Y").date()
                if year not in date_string
                else datetime.strptime(date_part, "%B %d, %Y").date()
            )
        except Exception:
            date = datetime.strptime(date_part, "%B %d, %Y").date()

        # Splitting and parsing the time range
        start_time_str, end_time_str = time_part.split(" - ")
        start_time = datetime.strptime(start_time_str.strip(), "%I:%M %p").time()
        end_time = datetime.strptime(end_time_str.strip(), "%I:%M %p").time()

        # Combining date and time and formatting
        start_datetime = datetime.combine(date, start_time).isoformat()
        end_datetime = datetime.combine(date, end_time).isoformat()
        return (start_datetime, end_datetime)

    async def parse_classification(title, description_text, current_url):
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
            if (
                keyword in title
                or keyword in description_text
                or keyword in current_url
            ):
                return classification

        return None

    page: Page = sdk.page
    year = current_url.split("=")[-1]
    await page.wait_for_selector(".tribe-events-schedule")
    title_element = await page.query_selector("h1.tribe-events-single-event-title")
    title_text = await title_element.inner_text() if title_element else None
    date_element = await page.query_selector(".tribe-events-schedule")
    date_string = await date_element.inner_text()
    description_element = await page.query_selector(
        "div.tribe-events-single-event-description"
    )
    description_text = await description_element.inner_text()
    start_time, end_time = await extract_and_format_date(date_string, year)
    if "cancel" in title_text.lower():
        is_cancelled = True
    else:
        is_cancelled = False
    agenda_element = await page.query_selector(
        ".tribe-events-single-event-description p > a"
    )
    venue_name_address_element = await page.query_selector(".tribe-venue a")
    venue_name = (
        await venue_name_address_element.inner_text()
        if venue_name_address_element
        else None
    )
    vanue_address_element = await page.query_selector("span.tribe-address")
    vanue_address = (
        await vanue_address_element.inner_text() if vanue_address_element else None
    )

    links = []
    location = None
    if agenda_element:
        check_agenda_text = await agenda_element.inner_text()
        if "agenda" in check_agenda_text.lower():
            agenda_link = await agenda_element.get_attribute("href")
            await page.goto(agenda_link)
            try:
                await page.wait_for_selector(
                    "table:nth-of-type(4) tr:nth-of-type(1) a:nth-of-type(1)"
                )
                links = await parse_links(page)
                address_element = await page.query_selector(
                    "span#ctl00_ContentPlaceHolder1_lblLocation"
                )
                address_text = (
                    await address_element.inner_text() if address_element else ""
                )
                if "zoom" in address_text.lower() or "virtual" in address_text.lower():
                    location = {"name": "Virtual", "address": "Zoom"}
                elif "virtual" in address_text.lower():
                    location = {"name": "Virtual", "address": ""}
                elif address_text:
                    location = {"name": "", "address": address_text}

                if not links:
                    links = [{"url": agenda_link, "title": "Agenda"}]
                if "zoom" in description_text.lower():
                    location = {"name": "Virtual", "address": "Zoom"}
                else:
                    location = None
            except TimeoutError:
                links = [{"url": agenda_link, "title": "Agenda"}]
                if "zoom" in description_text.lower():
                    location = {"name": "Virtual", "address": "Zoom"}
                else:
                    location = None

        elif vanue_address and "zoom" in vanue_address.lower():
            location = {"name": "Virtual", "address": "Zoom"}
        elif vanue_address and venue_name:
            location = {"name": venue_name, "address": vanue_address}
        elif "zoom" in description_text.lower():
            location = {"name": "Virtual", "address": "Zoom"}
        else:
            location = None

    meeting = {
        "title": title_text,
        "description": description_text if description_text else None,
        "classification": await parse_classification(
            title_text, description_text, current_url
        ),
        "start_time": await change_timezone(start_time) if start_time else None,
        "end_time": await change_timezone(end_time) if end_time else None,
        "time_notes": None,
        "is_all_day_event": None,
        "location": location,
        "links": links,
        "is_cancelled": is_cancelled,
    }
    await sdk.save_data(meeting)


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            "https://www.glwater.org/event/operations-and-resources-25/?y=2025",
            headless=False,
            harness=soup_harness,
            schema={
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": (
                                    "The URL link to the document or "
                                    "resource related to the meeting."
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
                                "The full address of the meeting venue. Sometimes, it "
                                "will include an online meeting link if the physical "
                                "location is not provided. "
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
