import asyncio
from datetime import datetime
from typing import Any

from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    page: Page = sdk.page
    await page.wait_for_selector("a#more-events-btn")
    event_title_element = await page.query_selector("div.field--name-name")
    event_title = await event_title_element.inner_text()
    event_element = await page.query_selector("a#more-events-btn")  # noqa: F841
    # event_link = await event_element.get_attribute("href")
    # Manually inserting link as the element doesn't interact when run
    event_link = "https://detroitmi.gov/events?term_node_tid_depth_1=941"
    prev_year = datetime.now().year - 1
    await page.goto(event_link + f"&field_start_value={prev_year}-01-01")
    await page.wait_for_selector("select#edit-term-node-tid-depth-1")
    await page.select_option(
        "select#edit-term-node-tid-depth-1", "-" + event_title.strip()
    )
    await page.click("input#edit-submit-events")
    await page.wait_for_selector("h3 a")
    try:
        await page.wait_for_selector("a[title='Go to last page']")
        last_page_element = await page.query_selector("a[title='Go to last page']")
        last_page_link = await last_page_element.get_attribute("href")
        page_link_split = last_page_link.split("page=")
        number_of_pages = int(last_page_link.split("page=")[-1])
        for index in range(number_of_pages + 1):
            await sdk.enqueue(page_link_split[0] + "page=" + str(index))
    except Exception:
        await sdk.enqueue(page.url)


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            (
                "https://www.detroitmi.gov/Government/"
                "Detroit-Police-Commissioners-Meetings"
            ),
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
