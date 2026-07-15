"""Detail stage for the Wayne County Commission scraper.

Meeting detail pages on waynecountymi.gov are server-rendered, so this
stage fetches them with plain HTTP and parses the HTML with parsel —
no browser needed. Two page layouts are handled:

1. The standard meeting layout (`.minutes-details-list`, `.meeting-time`,
   `.meeting-address`, `.meeting-document`)
2. A general content layout (`.small-text` date line with a side box)
"""

import asyncio
import re
from datetime import datetime
from typing import Any, Optional

import pytz
from parsel import Selector

from harambe_scrapers.extractor.wayne_commission.common import (
    BASE_URL,
    REQUEST_TIMEOUT,
    create_session,
)

TIMEZONE = "America/Detroit"


def change_timezone(date: str) -> str:
    """Localize a naive ISO datetime string to America/Detroit."""
    naive_datetime = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
    tz = pytz.timezone(TIMEZONE)
    localized_datetime = tz.localize(naive_datetime)
    iso_format = localized_datetime.strftime("%Y-%m-%dT%H:%M:%S%z")
    # Adjust the offset format to include a colon
    return iso_format[:-2] + ":" + iso_format[-2:]


def parse_classification(title: Optional[str]) -> Optional[str]:
    title = (title or "").lower()

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

    for keyword, classification in classifications.items():
        if keyword in title:
            return classification

    return None


def _text(selector: Selector, css: str) -> Optional[str]:
    """Joined, whitespace-normalized text of the first element matching css."""
    matches = selector.css(css)
    if not matches:
        return None
    joined = "".join(matches[0].css("::text").getall())
    return " ".join(joined.replace("\xa0", " ").split())


def _absolute_url(url: str) -> str:
    if "http" not in url:
        return BASE_URL + url
    return url


def _parse_links(selector: Selector) -> list[dict]:
    """Collect document and related-information links (excluding video)."""
    links = []
    for document in selector.css(".meeting-document"):
        title = " ".join(
            "".join(document.css(".meeting-document-title ::text").getall()).split()
        )
        url = document.css("a::attr(href)").get()
        if not url:
            continue
        url = _absolute_url(url)
        if "youtu" not in url:
            links.append({"title": title or None, "url": url})

    related = selector.css(
        ".related-information-section a, .related-information-list a"
    )
    for link in related:
        title = " ".join("".join(link.css("::text").getall()).split())
        url = link.attrib.get("href")
        if not url:
            continue
        url = _absolute_url(url)
        if "youtu" not in url:
            links.append({"title": title, "url": url})

    return links


def _parse_meeting_layout(selector: Selector) -> dict:
    """Parse the standard meeting page layout."""
    meeting_date = _text(
        selector, "ul.content-details-list.minutes-details-list span.minutes-date"
    )
    meeting_type = _text(
        selector,
        "ul.content-details-list.minutes-details-list "
        "li:nth-child(2) span.field-value",
    )
    description = _text(selector, "div.meeting-container > p") or ""

    time_text = (
        (_text(selector, "div.meeting-time") or "")
        .replace("Time", "")
        .replace("Add to Calendar", "")
        .strip()
    )
    start_time, end_time = time_text.split(" - ")

    start_datetime = datetime.strptime(
        f"{meeting_date} {start_time.strip()}", "%B %d, %Y %I:%M %p"
    )
    end_datetime = datetime.strptime(
        f"{meeting_date} {end_time.strip()}", "%B %d, %Y %I:%M %p"
    )

    location_text = _text(selector, "div.meeting-address > p:last-of-type") or ""
    location_text = location_text.replace("View Map", "").strip()
    location_parts = location_text.split(",", 1)
    location_name = location_parts[0].strip()
    location_address = location_parts[1].strip() if len(location_parts) > 1 else ""

    return {
        "description": description,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "location_name": location_name,
        "location_address": location_address,
        "links": _parse_links(selector),
        "classification": parse_classification(meeting_type),
    }


def _parse_general_layout(selector: Selector, main_title: str) -> dict:
    """Parse the fallback general content layout (.small-text date line)."""
    small_text = "".join(selector.css(".small-text ::text").getall())

    date_match = re.search(r"\b\w+ \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M\b", small_text)
    if date_match:
        start_datetime = datetime.strptime(date_match.group(0), "%B %d, %Y, %I:%M %p")
    else:
        start_datetime = None

    location_name, location_address = None, None
    location_el = selector.css(".side-box-section p:nth-child(5)")
    if location_el:
        location_lines = [
            line.strip()
            for line in "".join(location_el[0].css("::text").getall())
            .replace("\xa0", " ")
            .split("\n")
            if line.strip()
        ]
        if location_lines:
            location_name = location_lines[0]
            location_address = ", ".join(location_lines[1:]).strip()

    description = _text(selector, ".col-m-8 .body-content") or ""

    return {
        "description": description,
        "start_datetime": start_datetime,
        "end_datetime": None,
        "location_name": location_name,
        "location_address": location_address,
        "links": _parse_links(selector),
        "classification": parse_classification(main_title),
    }


async def scrape(
    sdk: Any, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    session = kwargs.get("session") or create_session()

    response = session.get(
        current_url, headers={"Accept": "text/html"}, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    selector = Selector(text=response.text)

    main_title = _text(selector, "h1.oc-page-title")

    if selector.css("ul.content-details-list.minutes-details-list span.minutes-date"):
        parsed = _parse_meeting_layout(selector)
    elif selector.css(".small-text"):
        parsed = _parse_general_layout(selector, main_title)
    else:
        print(f"    ✗ Unrecognized page layout: {current_url}")
        return

    start_datetime = parsed["start_datetime"]
    end_datetime = parsed["end_datetime"]

    is_all_day_event = (
        True
        if start_datetime
        and end_datetime
        and ((end_datetime - start_datetime).total_seconds() >= 86400)
        else None
    )

    is_cancelled = True if context.get("isCancelled") == "True" else None

    if start_datetime:
        await sdk.save_data(
            {
                "title": main_title,
                "description": parsed["description"],
                "classification": parsed["classification"],
                "start_time": change_timezone(start_datetime.isoformat()),
                "end_time": (
                    change_timezone(end_datetime.isoformat()) if end_datetime else None
                ),
                "location": (
                    {
                        "name": parsed["location_name"],
                        "address": parsed["location_address"],
                    }
                    if parsed["location_name"] or parsed["location_address"]
                    else None
                ),
                "links": parsed["links"],
                "time_notes": "",
                "is_cancelled": is_cancelled,
                "is_all_day_event": is_all_day_event,
            }
        )


if __name__ == "__main__":
    # Minimal manual run against a single detail page
    class _PrintSDK:
        async def save_data(self, data):
            import json

            print(json.dumps(data, indent=2))

    asyncio.run(
        scrape(
            _PrintSDK(),
            "https://www.waynecountymi.gov/Government/Elected-Officials/"
            "Commission/Committees/Full-Commission/Full-Commission-Meetings/"
            "2025/Full-Commission-January-8-2026",
            {"isCancelled": "False"},
        )
    )
