"""
Wayne County Commission scraper using Harambe orchestrator.

This scraper consolidates all Wayne County Commission meetings including:
- Ways & Means
- Audit
- Building Authority
- Committee of the Whole
- Full Commission
- Economic Development
- Government Operations
- Health and Human Services
- Public Safety
- Public Services
- Election Commission
- Local Emergency Planning
- Ethics Board

The county site's Akamai bot protection blocks clients that spoof browser
headers, so both stages run over plain HTTP with an honest User-Agent
(see extractor/wayne_commission/common.py) — no browser required.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from harambe_scrapers.extractor.wayne_commission.common import create_session
from harambe_scrapers.extractor.wayne_commission.detail import scrape as detail_scrape
from harambe_scrapers.extractor.wayne_commission.listing import scrape as listing_scrape
from harambe_scrapers.observers import DataCollector
from harambe_scrapers.utils import create_ocd_event

# Constants
AGENCY_NAME = "Wayne County Commission"
SCRAPER_NAME = (
    "wayne_health_human_services,wayne_economic_development,wayne_ethics_board,"
    "wayne_government_operations,wayne_ways_means,wayne_audit,wayne_public_services,"
    "wayne_building_authority,wayne_election_commission,wayne_public_safety,wayne_cow,"
    "wayne_local_emergency_planning,wayne_full_commission"
)
# Use shorter name for file output
OUTPUT_NAME = "wayne_commission"
TIMEZONE = "America/Detroit"
START_URL = "https://www.waynecountymi.gov/Government/County-Calendar"
OUTPUT_DIR = Path("harambe_scrapers/output")

# Delay between detail-page requests to stay polite
DETAIL_REQUEST_DELAY_SECONDS = 0.25


class ListingSDK:
    """Mock SDK for listing stage that collects URLs."""

    def __init__(self, detail_urls):
        self.detail_urls = detail_urls

    async def enqueue(self, url: str, context: dict = None):
        """Collect detail page URLs with context."""
        self.detail_urls.append({"url": url, "context": context or {}})


class DetailSDK:
    """Mock SDK for detail stage that stores extracted data."""

    def __init__(self):
        self.data = None

    async def save_data(self, data: dict):
        """Store the extracted meeting data."""
        self.data = data


class WayneCommissionOrchestrator:
    """Orchestrator for Wayne County Commission scraper."""

    def __init__(self, limit_meetings: int = None):
        self.limit_meetings = limit_meetings  # Optional limit for testing
        self.observer = DataCollector(
            scraper_name=SCRAPER_NAME,
            timezone=TIMEZONE,
        )
        self.session = create_session()
        self.detail_urls = []
        self.current_url = None

    async def run_listing_stage(self):
        """Run listing stage to collect all detail page URLs."""
        print("\n📋 STAGE 1: Collecting meeting URLs from calendar API...")

        try:
            listing_sdk = ListingSDK(self.detail_urls)
            await listing_scrape(listing_sdk, START_URL, {}, session=self.session)
            print(f"  ✓ Found {len(self.detail_urls)} meetings")
        except Exception as e:
            print(f"  ✗ Error during listing stage: {e}")
            raise

    async def run_detail_stage(self, detail_info: dict) -> Optional[dict]:
        """Run detail stage for a single meeting."""
        url = detail_info["url"]
        context = detail_info.get("context", {})

        try:
            self.current_url = url
            detail_sdk = DetailSDK()
            await detail_scrape(detail_sdk, url, context, session=self.session)
            return detail_sdk.data
        except Exception as e:
            print(f"    ✗ Error extracting {url}: {e}")
            return None

    def transform_to_ocd_format(self, raw_data: dict) -> dict:
        """Transform raw data to OCD format."""
        # Handle all_day_event field
        all_day = raw_data.get("is_all_day_event")
        if all_day is None:
            all_day = False

        location = raw_data.get("location") or {}

        return create_ocd_event(
            title=raw_data.get("title") or "Wayne County Commission Meeting",
            start_time=raw_data["start_time"],
            scraper_name=SCRAPER_NAME,
            agency_name=AGENCY_NAME,
            timezone=TIMEZONE,
            description=raw_data.get("description") or "",
            classification=raw_data.get("classification"),
            location=location,
            links=raw_data.get("links") or [],
            end_time=raw_data.get("end_time"),
            is_cancelled=raw_data.get("is_cancelled", False),
            source_url=self.current_url,
            all_day=all_day,
        )

    async def run(self):
        print("=" * 70)
        print(AGENCY_NAME)
        print("=" * 70)

        # Stage 1: Collect all meeting URLs
        await self.run_listing_stage()

        # Stage 2: Extract details from each meeting page
        print("\n📄 STAGE 2: Extracting meeting details...")

        # Apply limit if set (for testing)
        urls_to_process = self.detail_urls
        if self.limit_meetings:
            urls_to_process = self.detail_urls[: self.limit_meetings]
            print(
                f"  ⚠️ Limited to processing {self.limit_meetings} meetings "
                f"(out of {len(self.detail_urls)} total)"
            )

        for i, detail_info in enumerate(urls_to_process, 1):
            # Show progress percentage
            progress = (i / len(urls_to_process)) * 100
            print(f"\n  [{progress:.1f}%] Processing {i}/{len(urls_to_process)}:")
            print(f"    URL: {detail_info['url']}")

            raw_data = await self.run_detail_stage(detail_info)
            await asyncio.sleep(DETAIL_REQUEST_DELAY_SECONDS)

            if raw_data and raw_data.get("start_time"):
                ocd_event = self.transform_to_ocd_format(raw_data)
                await self.observer.on_save_data(ocd_event)
                # Extract date from start_time for display
                start_date = raw_data["start_time"][:10]  # Get YYYY-MM-DD
                title = raw_data.get("title", "Unknown")
                print(f"    ✓ {start_date} - {title}")
            else:
                print("    ✗ Skipped (missing start_time or data)")

        # URLs were found but nothing parsed — the detail-page markup has
        # likely changed. Fail loudly so the cron doesn't report a
        # "successful" run that quietly produced no meetings.
        if urls_to_process and not self.observer.data:
            raise RuntimeError(
                f"Detail stage produced 0 meetings from "
                f"{len(urls_to_process)} URLs — treating as a scraper failure"
            )

        print("\n" + "=" * 70)
        print(f"Scraping Complete: {len(self.observer.data)} meetings")
        print("=" * 70)

        if self.observer.data:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = OUTPUT_DIR / f"{OUTPUT_NAME}_{timestamp}.json"

            with open(output_file, "w", encoding="utf-8") as f:
                for meeting in self.observer.data:
                    if "__url" in meeting:
                        del meeting["__url"]
                    f.write(json.dumps(meeting, ensure_ascii=False) + "\n")

            print(f"\n✓ Data saved to: {output_file}")

            if self.observer.azure_client:
                print("✓ Data uploaded to Azure Blob Storage")
            else:
                print(
                    "ℹ Azure upload not configured "
                    "(set AZURE_* environment variables)"
                )


async def main():
    # Process all meetings (no limit)
    orchestrator = WayneCommissionOrchestrator()
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
