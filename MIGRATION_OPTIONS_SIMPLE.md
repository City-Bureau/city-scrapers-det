# Reworkd Migration: Implementation Plan

## Executive Summary

**The Situation:**
- Reworkd (external scraping vendor) shutting down by end of 2025
- 12 government agencies must migrate back to in-house GitHub Actions
- 2 agencies already migrated (17% complete)
- 10 agencies remaining

**Timeline:**
- **Option 1 (Build from Scratch)**: 3-5 weeks
- **Option 2 (Reuse Reworkd Code)**: 2.5-3.5 weeks ⭐ RECOMMENDED

---

## Migration Status

### ✅ Completed (2/12 agencies)
1. Detroit Board of Police Commissioners (orchestration flow)
2. Detroit Police and Fire Retirement System (simple listing)

### 🔄 Remaining (10/12 agencies)

**Simple Listing Scrapers** (6 agencies)
- Greater Cleveland Regional Transit Authority
- Cleveland City Planning Commission
- Michigan Belle Isle Park Advisory Committee
- Detroit Wayne County Port Authority
- Cuyahoga County Arts & Culture
- Cleveland Board of Building Standards and Building Appeals

**Orchestration Flow** (4 agencies)
- Great Lakes Water Authority
- Wayne County Commission
- Cuyahoga County Emergency Services Advisory Board
- Cuyahoga County Council

---

## Option 1: Enhanced Conventional Scrapers

**Build new scrapers from scratch using Python/Scrapy**

### Timeline: 3-5 weeks

#### Week 1: Platform Preparation (5 days)
- Enhanced meeting data storage (0.5 days)
- Smart status management (1.5 days)
- Generic data properties (0.5 days)
- Meeting analysis service updates (1.5 days)
- Anomaly detection enhancement (1 day)
- Import filter system (1.5 days)

#### Week 2-4: Build Scrapers (2-3 weeks)
- Research each website structure
- Write CSS selectors and extraction logic
- Handle pagination and edge cases
- Write unit tests
- **Estimate**: 2-3 days per agency × 10 agencies

#### Week 5: QA & Cleanup (3-4 days)
- Validate data quality
- Remove Reworkd dependencies
- Production deployment

### Pros
✅ Lowest operational cost (basic HTTP requests)
✅ Proven technology (300+ existing scrapers)
✅ Full control and customization

### Cons
❌ Longer development time
❌ More development work (build from scratch)
❌ Poor JavaScript support
❌ Manual updates when websites change

---

## Option 2: Harambe (RECOMMENDED)

**Reuse Reworkd's scraper code with Harambe framework**

### Timeline: 2.5-3.5 weeks ⭐ FASTEST

#### Week 1: Platform Preparation (5 days)
Same as Option 1

#### Week 2-3: Migrate Simple Scrapers (6 days)
**Implementation for each simple scraper** (1 day each):
1. Copy Reworkd's `listing.py` scrape function
2. Create new file in `harambe_scrapers/` (e.g., `det_dwcpa.py`)
3. Add observer pattern wrapper:
   ```python
   observer = DataCollector(scraper_name="agency_name_v2")
   await SDK.run(scrape, START_URL, observer=observer, harness=playwright_harness)
   ```
4. Transform data to OCD format using `create_ocd_event()`
5. Test scraper and verify data output
6. Write unit tests (similar to `test_det_dwcpa_v2.py`)

**Example**: See `det_police_fire_retirement.py` and `det_dwcpa.py`

#### Week 3-4: Migrate Orchestration Scrapers (8 days)
**Implementation for each orchestration scraper** (2 days each):
1. Copy Reworkd's `category.py`, `listing.py`, `detail.py` files
2. Place in `harambe_scrapers/extractor/agency_name/` directory
3. Create orchestrator file (e.g., `det_agency.py`) with three stages:
   - Stage 1: Category scraper finds listing pages
   - Stage 2: Listing scraper finds event detail pages
   - Stage 3: Detail scraper extracts meeting data
4. Build orchestration logic to coordinate stages
5. Add observer pattern for data collection
6. Test full workflow and verify data
7. Write comprehensive unit tests

**Example**: See `det_police_department.py` (3-stage orchestration)

#### Week 4: QA & Cleanup (2-3 days)
- Validate all 10 scrapers
- Remove Reworkd dependencies
- Production deployment

### Pros
✅ **Fastest development** - Just copy existing code
✅ **Lowest development effort** - Reworkd did the hard work
✅ **Better technology** - Handles JavaScript properly
✅ **Proven code** - Already tested by Reworkd
✅ **17% complete** - 2 scrapers already done

### Cons
❌ Higher operational cost (browser automation)
❌ Still requires manual updates when sites change

---

## Implementation Details

### Simple Listing Scraper Pattern

**What to copy from Reworkd:**
- `listing.py` → entire `scrape()` function

**What to add:**
```python
# 1. Configuration
START_URL = "https://agency-website.com/meetings"
SCRAPER_NAME = "agency_name_v2"
AGENCY_NAME = "Full Agency Name"
TIMEZONE = "America/Detroit"

# 2. Main function with observer pattern
async def main():
    observer = DataCollector(scraper_name=SCRAPER_NAME, timezone=TIMEZONE)
    await SDK.run(scrape, START_URL, observer=observer, harness=playwright_harness)

    # Save to local JSONLINES file
    output_file = OUTPUT_DIR / f"{SCRAPER_NAME}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(output_file, "w") as f:
        for meeting in observer.data:
            if "__url" in meeting:
                del meeting["__url"]
            f.write(json.dumps(meeting, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    asyncio.run(main())
```

**Time estimate**: 1 day (4-6 hours coding + 2-4 hours testing)

---

### Orchestration Flow Pattern

**What to copy from Reworkd:**
- `category.py` → move to `harambe_scrapers/extractor/agency_name/category.py`
- `listing.py` → move to `harambe_scrapers/extractor/agency_name/listing.py`
- `detail.py` → move to `harambe_scrapers/extractor/agency_name/detail.py`

**What to build:**
```python
class AgencyOrchestrator:
    def __init__(self, headless: bool = True):
        self.observer = DataCollector(scraper_name=SCRAPER_NAME)
        self.listing_urls = []
        self.event_urls = []

    async def run_category_stage(self, page):
        # Navigate to category page
        # Run category scraper to find listing pages
        # Store listing URLs

    async def run_listing_stage(self, page):
        # For each listing URL
        # Run listing scraper to find event URLs
        # Store event URLs

    async def run_detail_stage(self, page, event_url):
        # Run detail scraper on event page
        # Extract meeting data
        # Transform to OCD format
        # Return meeting data

    async def run(self):
        # Create browser
        # Run stage 1 → stage 2 → stage 3
        # Collect all data via observer
        # Save to file
```

**Time estimate**: 2 days (1 day coding + 1 day testing/debugging)

---

## Week-by-Week Schedule (Option 2)

### Week 1: Platform Preparation
- Days 1-5: Platform upgrades (shared for all scrapers)

### Week 2: Simple Scrapers Batch 1
- Day 1: Greater Cleveland Regional Transit Authority
- Day 2: Cleveland City Planning Commission
- Day 3: Michigan Belle Isle Park Advisory Committee
- Day 4: Detroit Wayne County Port Authority
- Day 5: Cuyahoga County Arts & Culture

### Week 3: Simple + Orchestration Start
- Day 1: Cleveland Board of Building Standards (simple)
- Day 2-3: Great Lakes Water Authority (orchestration)
- Day 4-5: Wayne County Commission (orchestration)

### Week 4: Orchestration Finish + QA
- Day 1-2: Cuyahoga County Emergency Services (orchestration)
- Day 3-4: Cuyahoga County Council (orchestration)
- Day 5: Final QA across all 10 agencies

**Total**: 20 days = 4 weeks (with buffer)

---

## Recommendation

**Choose Option 2 (Harambe)** because:

1. **Faster**: 2.5-3.5 weeks vs 3-5 weeks
2. **Less work**: Copy existing code vs build from scratch
3. **Already started**: 2 of 12 done (17% complete)
4. **Better technology**: Handles JavaScript properly
5. **Proven code**: Reworkd already tested everything

**Trade-off**: Higher operational cost, but saves development time

---

## Key Questions

1. **Timeline**: When does Reworkd shut down?
2. **Priority**: Which agencies to migrate first?
3. **Resources**: Can we assign 2 developers to parallelize work?

---

## Next Steps

1. ✅ Approve Option 2 (Harambe)
2. ✅ Begin Platform Preparation (Week 1)
3. ✅ Start migrating simple scrapers (Week 2)
4. Monitor progress and adjust timeline as needed

---

*Last Updated: 2025-11-04*
*Progress: 2/12 agencies completed (17%)*
