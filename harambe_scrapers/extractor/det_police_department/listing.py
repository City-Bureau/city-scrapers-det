import asyncio
from typing import Any

from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    async def fetch_links(page):
        await page.wait_for_selector("h3 a")
        all_link_elements = await page.query_selector_all("h3 a")
        for link_element in all_link_elements:
            await sdk.enqueue(await link_element.get_attribute("href"))

    page: Page = sdk.page
    await fetch_links(page)


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            (
                "https://detroitmi.gov/Calendar-and-Events?"
                "field_start_value=2024-01-01&title=&term_node_tid_depth=All"
                "&term_node_tid_depth_1=1676&term_node_tid_depth_2=All&page=0"
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
