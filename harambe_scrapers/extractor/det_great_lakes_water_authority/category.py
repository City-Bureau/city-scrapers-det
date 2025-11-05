import asyncio
from typing import Any

from harambe import SDK
from harambe.contrib import soup_harness


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    from datetime import datetime

    current_year = datetime.now().year
    next_year = current_year + 1
    for index in range(current_year - 1, next_year + 1):
        year = index
        for month in range(1, 13):
            if month < 10:
                month = "0" + str(month)
            else:
                month = str(month)
            await sdk.enqueue(f"https://www.glwater.org/events/month/{year}-{month}/")


if __name__ == "__main__":
    asyncio.run(
        SDK.run(
            scrape,
            "http://www.glwater.org/events/",
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
