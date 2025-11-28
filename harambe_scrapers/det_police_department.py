"""
Detroit Police Department - Production Scraper with Observer Pattern
Orchestrates category->listing->detail scrapers with Azure upload support.
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz
from playwright.async_api import async_playwright

from harambe_scrapers.extractor.det_police_department.category import (
    scrape as category_scrape,
)
from harambe_scrapers.extractor.det_police_department.detail import (
    scrape as detail_scrape,
)
from harambe_scrapers.extractor.det_police_department.listing import (
    scrape as listing_scrape,
)
from harambe_scrapers.observers import DataCollector
from harambe_scrapers.utils import create_ocd_event

OUTPUT_DIR = Path("harambe_scrapers/output")
SCRAPER_NAME = "det_police_department"
AGENCY_NAME = "Detroit Police Department"
TIMEZONE = "America/Detroit"


class CategorySDK:
    """Mock SDK for category stage"""

    def __init__(self, page, urls_list):
        self.page = page
        self.urls = urls_list

    async def enqueue(self, url):
        # Add /events prefix if missing
        if url and not url.startswith("http"):
            url = f"https://detroitmi.gov{url}"
        if url and "?" in url and "/events" not in url:
            # URL has query parameters but no /events path
            parts = url.split("?")
            url = f"https://detroitmi.gov/events?{parts[1]}"
        self.urls.append(url)


class ListingSDK:
    """Mock SDK for listing stage"""

    def __init__(self, page, urls_list):
        self.page = page
        self.urls = urls_list

    async def enqueue(self, url):
        if url and not url.startswith("http"):
            url = f"https://detroitmi.gov{url}"
        self.urls.append(url)


class DetailSDK:
    """Mock SDK for detail stage"""

    def __init__(self, page):
        self.page = page
        self.data = None

    async def save_data(self, data):
        self.data = data


class DetroitPoliceOrchestrator:
    """Orchestrates the three-stage Detroit Police scraping process"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.observer = DataCollector(scraper_name=SCRAPER_NAME, timezone=TIMEZONE)
        self.listing_urls = []
        self.event_urls = []
        self.failed_urls = []

    async def run_category_stage(self, page):
        """Step 1: Run category scraper to find all listing pages"""
        print("=" * 60)
        print("[Stage 1/3] Category Stage - Finding listing pages")
        print("=" * 60)

        sdk = CategorySDK(page, self.listing_urls)

        # Navigate to the page first
        category_url = (
            "https://www.detroitmi.gov/Government/"
            "Detroit-Police-Commissioners-Meetings"
        )
        print(f"Navigating to: {category_url}")

        try:
            await page.goto(category_url, wait_until="domcontentloaded", timeout=60000)

            await category_scrape(
                sdk,
                category_url,
                {},
            )
            print(f"✓ Found {len(self.listing_urls)} listing pages")
            for idx, url in enumerate(self.listing_urls[:3], 1):
                print(f"  {idx}. {url}")
            if len(self.listing_urls) > 3:
                print(f"  ... and {len(self.listing_urls) - 3} more")
        except Exception as e:
            print(f"✗ Category stage failed: {e}")
            raise

    async def run_listing_stage(self, page):
        """Step 2: Run listing scraper on each listing page to find event URLs"""
        print("\n" + "=" * 60)
        print("[Stage 2/3] Listing Stage - Finding event URLs")
        print("=" * 60)

        for idx, listing_url in enumerate(self.listing_urls, 1):
            print(
                f"\nProcessing listing {idx}/{len(self.listing_urls)}: "
                f"{listing_url}"
            )
            sdk = ListingSDK(page, self.event_urls)
            try:
                await page.goto(
                    listing_url, wait_until="domcontentloaded", timeout=60000
                )
                await listing_scrape(sdk, listing_url, {})
            except Exception as e:
                print(f"  ✗ Failed: {e}")
                continue

        # Remove duplicates
        self.event_urls = list(set(self.event_urls))
        print(f"\n✓ Found {len(self.event_urls)} unique event URLs")

    async def run_detail_stage(self, page, event_url) -> Optional[Dict[str, Any]]:
        """Step 3: Run detail scraper on an event page"""
        sdk = DetailSDK(page)

        try:
            await page.goto(event_url, wait_until="domcontentloaded", timeout=60000)

            # Run detail scraper with better error handling
            await detail_scrape(sdk, event_url, {})

            if sdk.data:
                print("  ✓ Extracted via detail.py")
                return sdk.data
            else:
                print("  ⚠️ No data from detail.py, trying fallback...")

        except Exception as e:
            error_msg = str(e)
            print(f"  ✗ Detail extraction failed: {error_msg[:100]}")
            print("  ⚠️ Trying fallback extraction...")

        # Try fallback extraction if no data or error occurred
        try:
            result = await self.fallback_extraction(page, event_url)
            if result:
                print("  ✓ Extracted via fallback")
            return result
        except Exception as fallback_error:
            print(f"  ✗ Fallback extraction also failed: {fallback_error}")
            self.failed_urls.append((event_url, str(fallback_error)))
            return None

    async def fallback_extraction(self, page, event_url) -> Optional[Dict[str, Any]]:
        """Fallback extraction for pages with missing standard elements"""

        # Extract whatever we can find
        fallback_data = {}

        # Title - try multiple selectors
        title = None
        for selector in [".title span", "h1", ".page-title", "title"]:
            try:
                element = await page.query_selector(selector)
                if element:
                    title = await element.inner_text()
                    if title:
                        break
            except Exception:
                continue

        fallback_data["title"] = title or "Detroit Police Meeting"

        # Time extraction with pytz
        time_text = None
        try:
            time_element = await page.query_selector("article.time")
            if time_element:
                time_text = await time_element.inner_text()
        except Exception:
            pass

        # Date extraction
        date_text = None
        try:
            date_element = await page.query_selector(".date time")
            if date_element:
                date_text = await date_element.get_attribute("datetime")
        except Exception:
            pass

        # Parse datetime with timezone
        if date_text:
            try:
                # Parse the date
                if "T" in date_text:
                    naive_dt = datetime.strptime(date_text.split("T")[0], "%Y-%m-%d")
                else:
                    naive_dt = datetime.strptime(date_text, "%Y-%m-%d")

                # Parse time if available
                if time_text:
                    time_text = (
                        time_text.strip().replace(".", "").replace("Noon", "12:00 PM")
                    )
                    # Clean up time format
                    time_text = re.sub(
                        r"([0-9]+):([0-9]+)\s*([ap]m)",
                        r"\1:\2 \3",
                        time_text,
                        flags=re.IGNORECASE,
                    )
                    try:
                        time_parts = datetime.strptime(time_text, "%I:%M %p").time()
                        naive_dt = naive_dt.replace(
                            hour=time_parts.hour, minute=time_parts.minute
                        )
                    except Exception:
                        # Default to noon if time parsing fails
                        naive_dt = naive_dt.replace(hour=12, minute=0)
                else:
                    naive_dt = naive_dt.replace(hour=12, minute=0)

                # Add timezone
                tz = pytz.timezone("America/Detroit")
                localized_dt = tz.localize(naive_dt)
                fallback_data["start_time"] = localized_dt.isoformat()
            except Exception as e:
                print(f"    Date parsing failed: {e}")
                fallback_data["start_time"] = datetime.now(
                    pytz.timezone("America/Detroit")
                ).isoformat()

        # Extract links (PDFs and documents)
        links = []
        try:
            # Try multiple selectors for document links
            selectors = [
                ".file a",
                "a[href$='.pdf']",
                "a[href*='/sites/']",
                ".field--type-file a",
            ]
            for selector in selectors:
                link_elements = await page.query_selector_all(selector)
                for link_element in link_elements:
                    href = await link_element.get_attribute("href")
                    text = await link_element.inner_text()
                    if href:
                        if not href.startswith("http"):
                            href = f"https://detroitmi.gov{href}"

                        # Clean up title
                        if "agenda" in text.lower():
                            text = "Agenda"
                        elif "minute" in text.lower():
                            text = "Minutes"
                        else:
                            text = text.replace(".pdf", "").strip()

                        links.append({"url": href, "title": text})
        except Exception as e:
            print(f"    Link extraction failed: {e}")

        fallback_data["links"] = links

        # Description
        fallback_data["description"] = ""
        try:
            desc_element = await page.query_selector(".description")
            if desc_element:
                fallback_data["description"] = await desc_element.inner_text()
        except Exception:
            pass

        # Classification based on title/description
        combined_text = (
            fallback_data.get("title", "") + " " + fallback_data.get("description", "")
        ).lower()

        classifications = {
            "committee": "COMMITTEE",
            "board": "BOARD",
            "commission": "COMMISSION",
            "public": "PUBLIC",
            "community": "COMMUNITY",
            "policy": "POLICY",
            "advisory": "ADVISORY",
            "annual": "ANNUAL",
        }

        classification = None
        for keyword, class_value in classifications.items():
            if keyword in combined_text:
                classification = class_value
                break

        # Only set classification if we found one
        if classification:
            fallback_data["classification"] = classification

        # Check if cancelled
        fallback_data["is_cancelled"] = (
            "cancel" in combined_text or "recess" in combined_text
        )

        return fallback_data

    def transform_to_ocd_format(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform scraped data to OCD Event format using shared utility"""
        # Get is_all_day_event from raw_data, default to False if None
        all_day = raw_data.get("is_all_day_event")
        if all_day is None:
            all_day = False

        return create_ocd_event(
            title=raw_data.get("title", "Detroit Police Meeting"),
            start_time=raw_data.get("start_time"),
            scraper_name=SCRAPER_NAME,
            agency_name=AGENCY_NAME,
            timezone=TIMEZONE,
            description=raw_data.get("description", ""),
            classification=raw_data.get("classification", "COMMITTEE"),
            location=raw_data.get("location"),
            links=raw_data.get("links"),
            end_time=raw_data.get("end_time"),
            is_cancelled=raw_data.get("is_cancelled", False),
            source_url=(self.current_url if hasattr(self, "current_url") else ""),
            all_day=all_day,
        )

    async def run(self):
        """Run the complete orchestrated scraping process"""
        print("\nStarting Detroit Police Department Scraper")
        print(f"Timezone: {TIMEZONE}")
        print(f"Output: {OUTPUT_DIR}")
        print("=" * 60)

        async with async_playwright() as p:
            # Launch browser with anti-detection settings
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=site-per-process",
                    "--disable-web-security",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                    "--start-maximized",
                ],
            )

            # Create context with anti-detection
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
            )

            page = await context.new_page()

            # Add anti-detection script
            await page.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                window.chrome = {
                    runtime: {}
                };
                Object.defineProperty(navigator, 'permissions', {
                    get: () => ({
                        query: () => Promise.resolve({ state: 'granted' })
                    })
                });
            """
            )

            try:
                # Stage 1: Category
                await self.run_category_stage(page)

                # Stage 2: Listing
                await self.run_listing_stage(page)

                # Stage 3: Detail
                print("\n" + "=" * 60)
                print("[Stage 3/3] Detail Stage - Extracting meeting data")
                print("=" * 60)

                total_events = len(self.event_urls)
                print(f"\nProcessing {total_events} events...")

                for idx, event_url in enumerate(self.event_urls, 1):
                    print(f"\n[{idx}/{total_events}] {event_url}")
                    self.current_url = event_url

                    # Extract data
                    raw_data = await self.run_detail_stage(page, event_url)

                    if raw_data:
                        # Transform to OCD format
                        ocd_data = self.transform_to_ocd_format(raw_data)

                        # Save via observer
                        await self.observer.on_save_data(ocd_data)

                # Print summary
                print("\n" + "=" * 60)
                print("SCRAPING COMPLETE")
                print("=" * 60)
                print(f"✓ Processed: {len(self.observer.data)} meetings")
                print(f"✗ Failed: {len(self.failed_urls)} URLs")

                if self.failed_urls:
                    print("\nFailed URLs:")
                    for url, error in self.failed_urls[:5]:
                        print(f"  - {url}")
                        print(f"    Error: {error[:100]}")

                # Save to local file
                if self.observer.data:
                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_file = OUTPUT_DIR / f"{SCRAPER_NAME}_{timestamp}.json"

                    # Write JSONLINES format - one JSON object per line
                    with open(output_file, "w", encoding="utf-8") as f:
                        for meeting in self.observer.data:
                            # Remove __url field if it exists
                            if "__url" in meeting:
                                del meeting["__url"]
                            f.write(json.dumps(meeting, ensure_ascii=False) + "\n")

                    print(f"\n✓ Data saved to: {output_file}")

                    # Azure upload status
                    if self.observer.azure_client:
                        print("✓ Data uploaded to Azure Blob Storage")
                    else:
                        print(
                            "ℹ Azure upload not configured "
                            "(set AZURE_* environment variables)"
                        )

            finally:
                await browser.close()


async def main():
    """Main entry point"""
    orchestrator = DetroitPoliceOrchestrator(headless=True)
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
