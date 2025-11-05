import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytz
from dateutil.parser import parse as dateparse
from harambe import SDK
from harambe.contrib import playwright_harness
from playwright.async_api import Page

from harambe_scrapers.observers import DataCollector
from harambe_scrapers.utils import create_ocd_event

# Configuration
START_URL = "https://www.michigan.gov/dnr/about/boards/belle-isle"
OUTPUT_DIR = Path("harambe_scrapers/output")
SCRAPER_NAME = "mi_belle_isle_v2"
AGENCY_NAME = "Michigan Belle Isle Advisory Committee"
TIMEZONE = "America/Detroit"


async def scrape(
    sdk: SDK, current_url: str, context: dict[str, Any], *args: Any, **kwargs: Any
) -> None:
    page: Page = sdk.page
    meeting_dict = {}

    async def change_timezone(date):
        naive_datetime = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
        tz = pytz.timezone(TIMEZONE)
        localized_datetime = tz.localize(naive_datetime)
        iso_format = localized_datetime.strftime("%Y-%m-%dT%H:%M:%S%z")
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
        }
        for keyword, classification in classifications.items():
            if keyword in title or keyword in description_text:
                return classification
        return None

    async def current_year_meetings(page):
        async def parse_start_end(row):
            """Parse start and end datetimes."""
            date_cell = await row.query_selector("td:first-child")
            time_cell = await row.query_selector("td:nth-child(2)")

            if not date_cell or not time_cell:
                return (None, None)

            date_text = await date_cell.inner_text()
            time_text = await time_cell.inner_text()

            date_str = re.sub("[^a-zA-Z,\\d\\s]", "", date_text)
            time_str = re.sub("[^a-zA-Z,\\d\\s:-]", "", time_text)

            meridian_match = re.findall("(am|pm)", time_str.lower())
            if not meridian_match:
                return (None, None)
            meridian_str = meridian_match[0]

            try:
                date_value = dateparse(date_str)
            except Exception:
                return (None, None)

            if "-" in time_str:
                time_start_match = re.findall("(\\d+?:*?\\d*?)(?=\\s*-)", time_str)
                time_end_match = re.findall("((?<=-)\\s*)(\\d+?:*?\\d*)", time_str)
                if time_start_match and time_end_match:
                    time_start_str = time_start_match[0]
                    time_end_str = time_end_match[0][1]
                    end_value = dateparse(f"{date_str} {time_end_str} {meridian_str}")
                    end_dt = datetime.combine(date_value.date(), end_value.time())
                else:
                    time_start_str = re.search("(\\d+)(:\\d+)?", time_str).group()
                    end_dt = None
            else:
                time_start_match = re.search("(\\d+)(:\\d+)?", time_str)
                if not time_start_match:
                    return (None, None)
                time_start_str = time_start_match.group()
                end_dt = None

            start_value = dateparse(f"{date_str} {time_start_str} {meridian_str}")
            return (datetime.combine(date_value.date(), start_value.time()), end_dt)

        async def parse_location(row):
            """Parse or generate location."""
            location_cell = await row.query_selector("td:nth-child(3)")
            text = await location_cell.inner_text() if location_cell else None
            if not text:
                return None

            name_match = re.match("^(.*?), (\\d+ .*?),", text)
            name = name_match.group(1) if name_match else None

            address_match = re.search("(\\d+ .*?, .*?, [A-Z]{2} \\d{5})", text)
            address = address_match.group(1) if address_match else None

            if name and address:
                return {"name": name, "address": address}
            elif not name and address:
                return {"name": None, "address": address}
            elif text.strip():
                return {"name": text.strip(), "address": None}
            else:
                return None

        async def parse_links(page):
            """Parse agenda and minutes links."""
            agendas = {}
            minutes = {}

            agenda_elements = await page.query_selector_all("div[id*='comp_101140'] a")
            for agenda in agenda_elements:
                href = await agenda.get_attribute("href")
                text = await agenda.inner_text()
                if href and text:
                    text = text.replace(" (draft)", "").split(" - ")[0]
                    try:
                        agendas[dateparse(text).date()] = href
                    except Exception:
                        continue

            minutes_elements = await page.query_selector_all("div[id*='comp_101141'] a")
            for minute in minutes_elements:
                href = await minute.get_attribute("href")
                text = await minute.inner_text()
                if href and text:
                    text = text.replace(" (draft)", "")
                    try:
                        minutes[dateparse(text).date()] = href
                    except Exception:
                        continue

            return (agendas, minutes)

        async def match_links(row, start, page):
            """Match links to the meeting date."""
            meeting_date = start.date()
            agendas, minutes = await parse_links(page)
            matched_links = []

            if meeting_date in agendas:
                matched_links.append(
                    {"url": urljoin(page.url, agendas[meeting_date]), "title": "Agenda"}
                )
            if meeting_date in minutes:
                matched_links.append(
                    {
                        "url": urljoin(page.url, minutes[meeting_date]),
                        "title": "Minutes",
                    }
                )

            return matched_links

        rows = await page.query_selector_all("tbody tr")
        title_element = await page.query_selector(".last .navigation-title a")
        title = (
            await title_element.inner_text()
            if title_element
            else "Belle Isle Advisory Committee Meeting"
        )

        for row in rows:
            start, end = await parse_start_end(row)
            if not start:
                continue

            location = await parse_location(row)
            links = await match_links(row, start, page)
            status_cell = await row.query_selector("td:nth-child(3)")
            status_text = await status_cell.inner_text() if status_cell else "TBD"
            is_cancelled = "cancel" in status_text.lower()

            date_key = (await change_timezone(start.isoformat())).split("T")[0]
            meeting_dict[date_key] = {
                "title": title,
                "description": status_text,
                "classification": await parse_classification(title, ""),
                "start_time": await change_timezone(start.isoformat()),
                "end_time": await change_timezone(end.isoformat()) if end else None,
                "location": location,
                "links": links,
                "is_cancelled": is_cancelled,
            }

    async def archive_meetings(page):
        async def convert_date(date_str):
            clean_date = (
                date_str.replace("(draft)", "").replace("Feb.", "February").strip()
            )
            try:
                parsed_date = datetime.strptime(clean_date, "%B %d, %Y")
                return parsed_date.strftime("%Y-%m-%dT00:00:00")
            except ValueError:
                return None

        columns = await page.query_selector_all(
            ".link-list--4-columns a,.col-12 .field-link a"
        )

        for column in columns:
            column_text = await column.inner_text()
            start = await convert_date(column_text)
            if not start:
                continue
            href = await column.get_attribute("href")
            date_key = (await change_timezone(start)).split("T")[0]

            if meeting_dict.get(date_key):
                meeting_dict[date_key]["links"] = meeting_dict[date_key]["links"] + [
                    {"url": urljoin(page.url, href), "title": "Minutes"}
                ]

    await current_year_meetings(page)
    await archive_meetings(page)

    for key, value in meeting_dict.items():
        all_day = value["start_time"].endswith("T00:00:00-05:00") or value[
            "start_time"
        ].endswith("T00:00:00-04:00")

        meeting = create_ocd_event(
            title=value["title"],
            start_time=value["start_time"],
            scraper_name=SCRAPER_NAME,
            agency_name=AGENCY_NAME,
            timezone=TIMEZONE,
            description=value.get("description", ""),
            classification=value.get("classification"),
            location=value.get("location", {}),
            links=value.get("links", []),
            end_time=value.get("end_time"),
            is_cancelled=value.get("is_cancelled", False),
            source_url=START_URL,
            all_day=all_day,
        )

        await sdk.save_data(meeting)


async def main():
    print("=" * 70)
    print("Michigan Belle Isle Advisory Committee")
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
        output_file = OUTPUT_DIR / f"mi_belle_isle_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(output_file, "w") as f:
            for meeting in observer.data:
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
