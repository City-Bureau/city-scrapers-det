# Add Wayback Machine Archive Support for Harambe Scrapers

## Background

### Current State
- **Scrapy scrapers**: Have Wayback archive support via `CityScrapersWaybackMiddleware`
- **Harambe scrapers**: No archive support - URLs not sent to Wayback Machine

### How Scrapy Archive Works
1. `archive.yml` workflow runs daily at 11:07 UTC
2. Uses `city_scrapers.settings.archive` which enables `CityScrapersWaybackMiddleware`
3. Middleware intercepts each scraped meeting during the crawl
4. Sends source URL + up to 3 document links to `https://web.archive.org/save/{url}`
5. Handles rate limiting (429) by waiting 60 seconds

### Meeting Data Structure (both Scrapy and Harambe after DiffPipeline)
```json
{
  "sources": [{"url": "https://...", "note": ""}],
  "links": [{"url": "https://...", "note": "Agenda"}]
}
```

## Implementation Plan

### 1. Create `scripts/archive_harambe_to_wayback.py`

```python
"""
Archive Harambe scraper URLs to the Wayback Machine.

Reads latest Harambe output files and sends meeting URLs to the
Internet Archive's Wayback Machine for preservation.
"""

import json
import random
import time
import requests
from pathlib import Path
from typing import List, Dict

WAYBACK_SAVE_URL = "https://web.archive.org/save/"
LOCAL_OUTPUT_DIR = "harambe_scrapers/output"
MAX_LINKS_PER_MEETING = 3
DELAY_BETWEEN_REQUESTS = 1  # seconds
RATE_LIMIT_WAIT = 60  # seconds


def get_urls_from_meeting(meeting: Dict) -> List[str]:
    """Extract URLs from sources and links fields."""
    urls = []

    for source in meeting.get("sources", []):
        url = source.get("url")
        if url and url.startswith("http"):
            urls.append(url)

    for link in meeting.get("links", []):
        url = link.get("url")
        if url and url.startswith("http"):
            urls.append(url)

    # Remove duplicates
    unique_urls = list(dict.fromkeys(urls))

    # Limit to MAX_LINKS_PER_MEETING
    if len(unique_urls) > MAX_LINKS_PER_MEETING:
        return random.sample(unique_urls, MAX_LINKS_PER_MEETING)

    return unique_urls


def save_to_wayback(url: str) -> bool:
    """Send URL to Wayback Machine. Returns True on success."""
    if "web.archive.org" in url:
        return False

    try:
        response = requests.get(
            f"{WAYBACK_SAVE_URL}{url}",
            timeout=30,
            allow_redirects=False,
            headers={"User-Agent": "City Scrapers Archiver (https://cityscrapers.org)"}
        )

        if response.status_code in [200, 302]:
            print(f"  [OK] {url[:70]}...")
            return True
        elif response.status_code == 429:
            print(f"  [RATE LIMITED] Waiting {RATE_LIMIT_WAIT}s...")
            time.sleep(RATE_LIMIT_WAIT)
            return save_to_wayback(url)  # Retry once
        else:
            print(f"  [FAILED {response.status_code}] {url[:70]}...")
            return False

    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT] {url[:70]}...")
        return False
    except Exception as e:
        print(f"  [ERROR] {url[:70]}... - {e}")
        return False


def read_latest_harambe_files(output_dir: str = LOCAL_OUTPUT_DIR) -> Dict[str, Path]:
    """Find latest output file per scraper."""
    output_path = Path(output_dir)
    if not output_path.exists():
        return {}

    by_scraper = {}
    for json_file in output_path.glob("*.json"):
        parts = json_file.stem.rsplit("_", 2)
        if len(parts) >= 3:
            scraper_name = parts[0]
            timestamp = f"{parts[1]}_{parts[2]}"
            if scraper_name not in by_scraper:
                by_scraper[scraper_name] = []
            by_scraper[scraper_name].append({"file": json_file, "timestamp": timestamp})

    return {
        name: max(files, key=lambda x: x["timestamp"])["file"]
        for name, files in by_scraper.items()
    }


def main():
    print("=" * 70)
    print("Archiving Harambe URLs to Wayback Machine")
    print("=" * 70)

    latest_files = read_latest_harambe_files()
    if not latest_files:
        print("No Harambe output files found")
        return

    print(f"Found {len(latest_files)} scrapers")

    total_archived = 0
    total_failed = 0

    for scraper_name, file_path in sorted(latest_files.items()):
        print(f"\n[{scraper_name}] {file_path.name}")

        with open(file_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                meeting = json.loads(line)
                for url in get_urls_from_meeting(meeting):
                    if save_to_wayback(url):
                        total_archived += 1
                    else:
                        total_failed += 1
                    time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"\nCOMPLETE: {total_archived} archived, {total_failed} failed")


if __name__ == "__main__":
    main()
```

### 2. Add to Workflow (Optional)

Add to `.github/workflows/cron.yml` after merge step:

```yaml
- name: Archive Harambe URLs to Wayback Machine
  run: |
    export PYTHONPATH=$(pwd):$PYTHONPATH
    python scripts/archive_harambe_to_wayback.py
```

Or create separate `.github/workflows/archive_harambe.yml`:

```yaml
name: Archive Harambe

on:
  schedule:
    - cron: "30 12 * * *"  # Run 1.5 hours after main cron
  workflow_dispatch:

jobs:
  archive:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install requests
      - run: python scripts/archive_harambe_to_wayback.py
```

### 3. Testing

```bash
cd /path/to/city-scrapers-det
python scripts/archive_harambe_to_wayback.py
```

Expected output:
```
======================================================================
Archiving Harambe URLs to Wayback Machine
======================================================================
Found 6 scrapers

[det_dwcpa] det_dwcpa_20251201_100508.json
  [OK] https://detroitmi.gov/...
  [OK] https://detroitmi.gov/agenda.pdf...

[det_police_department] det_police_department_20251201_102334.json
  [OK] https://...

COMPLETE: 45 archived, 2 failed
```

Verify by visiting `https://web.archive.org/web/*/URL` for any archived URL.

## Key Differences from Scrapy Middleware

| Aspect | Scrapy Middleware | Harambe Script |
|--------|-------------------|----------------|
| When | During scrape | After scrape (post-process) |
| Input | Live Meeting items | JSON files |
| Integration | Scrapy pipeline | Standalone script |
| Rate limiting | Built-in slot delay | Manual sleep + retry |

## Dependencies

- `requests` - already available (transitive dependency)
- No API keys or credentials needed

## Files to Create/Modify

| File | Action |
|------|--------|
| `scripts/archive_harambe_to_wayback.py` | Create |
| `.github/workflows/cron.yml` or new workflow | Add archive step (optional) |

## Considerations

1. **Rate limiting**: Wayback Machine limits requests. Script handles 429 by waiting 60s.
2. **Runtime**: With 1s delay per URL, 1000 URLs = ~17 minutes
3. **Duplicates**: Same URL won't be re-archived if recently saved (Wayback handles this)
4. **Failures**: Non-critical - meetings still work, just not preserved
