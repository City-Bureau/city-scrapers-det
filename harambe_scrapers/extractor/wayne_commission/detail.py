import asyncio
import re
from datetime import datetime
from typing import Any

from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page, TimeoutError


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    page: Page = sdk.page

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

    # Wait for the main content to load
    await page.wait_for_selector("div.main-inner-container")

    # Extract title
    main_title_element = await page.query_selector("h1.oc-page-title")
    main_title = await main_title_element.inner_text()

    try:
        await page.wait_for_selector(
            "ul.content-details-list.minutes-details-list span.minutes-date"
        )
        # Extract meeting date
        date_element = await page.query_selector(
            "ul.content-details-list.minutes-details-list span.minutes-date"
        )
        meeting_date = await date_element.inner_text()

        # Extract meeting type
        type_selector = (
            "ul.content-details-list.minutes-details-list "
            "li:nth-child(2) span.field-value"
        )
        type_element = await page.query_selector(type_selector)
        meeting_type = await type_element.inner_text()

        # Extract description
        description_element = await page.query_selector("div.meeting-container > p")
        description = await description_element.inner_text()

        # Extract start and end time
        time_element = await page.query_selector("div.meeting-time")
        time_text = (
            (await time_element.inner_text())
            .replace("Time", "")
            .replace("Add to Calendar", "")
            .replace("\n", "")
            .strip()
        )
        start_time, end_time = time_text.split(" - ")

        # Combine meeting date with times and convert to datetime objects
        start_datetime = datetime.strptime(
            f"{meeting_date} {start_time}", "%B %d, %Y %I:%M %p"
        )
        end_datetime = datetime.strptime(
            f"{meeting_date} {end_time}", "%B %d, %Y %I:%M %p"
        )

        # Extract location details
        location_element = await page.query_selector(
            "div.meeting-address > p:last-of-type"
        )
        location_text = await location_element.inner_text()
        location_parts = location_text.split(",", 1)
        location_name = location_parts[0].strip()
        location_address = location_parts[1].strip() if len(location_parts) > 1 else ""

        # Extract links
        links = []
        meeting_documents = await page.query_selector_all(".meeting-document")
        for document in meeting_documents:
            title_el = await document.query_selector(".meeting-document-title")
            title = await title_el.inner_text() if title_el else None
            link = await document.query_selector("a")
            if not link:
                continue
            url = await link.get_attribute("href")
            if "http" not in url:
                url = "https://www.waynecountymi.gov" + url
            if "youtu" not in url:
                links.append({"title": title, "url": url})

        related_links = await page.query_selector_all(
            ".related-information-section a, .related-information-list a"
        )
        for link in related_links:
            title = await link.inner_text()
            url = await link.get_attribute("href")
            if "http" not in url:
                url = "https://www.waynecountymi.gov" + url
            if "youtu" not in url:
                links.append({"title": title, "url": url})

        classification = parse_classification(meeting_type)

    except TimeoutError:
        try:
            await page.wait_for_selector(".small-text")
            small_text_element = await page.query_selector(".small-text")
            small_text = await small_text_element.inner_text()

            # Extract date using regex
            date_match = re.search(
                "\\b\\w+ \\d{1,2}, \\d{4}, \\d{1,2}:\\d{2} [AP]M\\b", small_text
            )
            if date_match:
                meeting_date = date_match.group(0)
                start_datetime = datetime.strptime(meeting_date, "%B %d, %Y, %I:%M %p")
                end_datetime = None
            else:
                start_datetime = None
                end_datetime = None

            # Extract location
            location_element = await page.query_selector(
                ".side-box-section p:nth-child(5)"
            )
            if location_element:
                location_text = await location_element.inner_text()
                location_parts = location_text.split("\n")
                location_name = location_parts[0].strip()
                location_address = ", ".join(location_parts[1:]).strip()
            else:
                location_name, location_address = (None, None)

            # Extract description
            description_element = await page.query_selector(".col-m-8 .body-content")
            description = await description_element.inner_text()

            # Extract links
            links = []
            related_links = await page.query_selector_all(
                ".related-information-section a, .related-information-list a"
            )
            for link in related_links:
                title = await link.inner_text()
                url = await link.get_attribute("href")
                if "http" not in url:
                    url = "https://www.waynecountymi.gov" + url
                if "youtu" not in url:
                    links.append({"title": title, "url": url})

            meeting_documents = await page.query_selector_all(".meeting-document")
            for document in meeting_documents:
                title_el = await document.query_selector(".meeting-document-title")
                title = await title_el.inner_text() if title_el else None
                link = await document.query_selector("a")
                if not link:
                    continue
                url = await link.get_attribute("href")
                if "http" not in url:
                    url = "https://www.waynecountymi.gov" + url
                if "youtu" not in url:
                    links.append({"title": title, "url": url})

            classification = parse_classification(main_title)
        except TimeoutError:
            return
        except AttributeError:
            raise AttributeError(
                "AttributeError: Some of the required fields couldn't be "
                "extracted, you might wanna incorporate this page's structure"
            )
    is_all_day_event = (
        True
        if start_datetime
        and end_datetime
        and ((end_datetime - start_datetime).total_seconds() >= 86400)
        else None
    )

    is_cancelled = True if context["isCancelled"] == "True" else None

    if start_datetime:
        # Save data
        await sdk.save_data(
            {
                "title": main_title,
                "description": description,
                "classification": classification,
                "start_time": await change_timezone(start_datetime.isoformat()),
                "end_time": (
                    await change_timezone(end_datetime.isoformat())
                    if end_datetime
                    else None
                ),
                "location": (
                    {"name": location_name, "address": location_address}
                    if location_name or location_address
                    else None
                ),
                "links": links,
                "time_notes": "",
                "is_cancelled": is_cancelled,
                "is_all_day_event": is_all_day_event,
            }
        )


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            "https://www.waynecountymi.gov/Government/Elected-Officials/"
            "Commission/Committees/Full-Commission/Full-Commission-Meetings/"
            "Full-Commission-February-1-2024",
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
