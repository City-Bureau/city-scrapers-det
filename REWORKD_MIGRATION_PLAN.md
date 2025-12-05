# TWO CRITICAL INITIATIVES FOR MEETING SCRAPER PLATFORM

## EXECUTIVE SUMMARY

### The Situation
We have two important but separate initiatives that both improve our meeting scraping infrastructure:

---

## INITIATIVE 1: MIGRATE 12 REWORKD AGENCIES BACK TO CONVENTIONAL SCRAPERS

### Background
- **What's happening**: Reworkd (our external scraping vendor) is shutting down by end of 2025
- **Impact**: 12 government agencies currently using Reworkd must return to our in-house system
- **Timeline**: 2.5-3.5 weeks of development work needed
- **Progress**: 2 of 12 agencies already migrated (17% complete)
- **Budget Impact**: Eliminates ongoing Reworkd subscription costs after migration

### The Solution
- Use Harambe framework to reuse existing Reworkd scraper code
- Migrate 10 remaining agencies (2 already completed)
- Maintain Reworkd's advanced features in the new scrapers
- Timeline: 14 days for remaining agencies

---

## INITIATIVE 2: UPGRADE 300+ CONVENTIONAL SCRAPERS WITH ADVANCED FEATURES

### Background
- **What's happening**: Existing conventional scrapers lack advanced data quality features
- **Impact**: 300+ agencies experience false cancellations and data quality issues
- **Opportunity**: Platform upgrades from Initiative 1 can benefit ALL scrapers
- **Timeline**: Ongoing effort (5-10 minutes per scraper)

### The Solution
- Add timestamp tracking to conventional scrapers
- Enable Reworkd-level features: deletion detection, rescheduling, duplicate prevention
- Improve data quality across entire platform
- Can be done incrementally (high-priority agencies first)

---

### How These Initiatives Relate

**Shared Foundation (Phase 1)**: Both initiatives require the same platform preparation work
**Different Execution**:
- Initiative 1 = Migrating 12 specific agencies using Harambe (Phases 2-4)
- Initiative 2 = Upgrading 300+ existing scrapers with timestamp tracking (ongoing)

**Both are important but can proceed independently after Phase 1 is complete.**

---

# DETAILED BREAKDOWN BY INITIATIVE

---

# INITIATIVE 1: MIGRATE 12 REWORKD AGENCIES

---

## Business Impact - Initiative 1

**What This Means for Users:**
- **No disruption** - Meetings will continue appearing without interruption
- **Better reliability** - In-house control means faster fixes when issues arise
- **Maintained quality** - Keep Reworkd's advanced features (deletion detection, rescheduling, etc.)

**What This Means for Operations:**
- **Cost savings** - Eliminate monthly Reworkd subscription fees
- **Vendor independence** - No more reliance on external service availability
- **Faster development** - Reuse existing Reworkd code with Harambe (1-2 days vs 3-5 days from scratch)

---

## Migration Status - Initiative 1

### ✅ Completed (2/12 agencies)
1. **Detroit Board of Police Commissioners** - Orchestration flow (3-stage)
2. **Detroit Police and Fire Retirement System** - Simple listing scraper

### 🔄 Remaining (10/12 agencies)

**Simple Listing Scrapers** (6 agencies × 1 day = 6 days)
- Greater Cleveland Regional Transit Authority
- Cleveland City Planning Commission
- Michigan Belle Isle Park Advisory Committee
- Detroit Wayne County Port Authority
- Cuyahoga County Arts & Culture
- Cleveland Board of Building Standards and Building Appeals

**Orchestration Flow** (4 agencies × 2 days = 8 days)
- Great Lakes Water Authority
- Wayne County Commission
- Cuyahoga County Emergency Services Advisory Board
- Cuyahoga County Council

**Total remaining work**: 14 days (2.8 weeks)

---

## Timeline & Resources - Initiative 1

### PROJECT PHASES FOR INITIATIVE 1

#### Phase 1: Platform Preparation (5 days)

**What we're doing**: Upgrading our system to handle returning agencies

**Note**: This phase benefits BOTH Initiative 1 and Initiative 2. The platform upgrades enable both the Reworkd migration and conventional scraper upgrades.

**Work Item 1: Enhanced Meeting Data Storage** (0.5 days)

**Current situation**: Reworkd automatically tracks when each meeting was scraped and when it was first created. Conventional scrapers don't track this information.

**What we need**: Enable conventional scrapers to record:
- **Last scraped timestamp**: When we last checked this meeting (like "last verified on Nov 4, 2025 at 10:30am")
- **Creation timestamp**: When we first discovered this meeting

**Why it matters**: These timestamps let the system detect when meeting data becomes stale (hasn't been updated in >24 hours), helping distinguish between:
- Meetings that were truly canceled/deleted vs.
- Meetings where the scraper simply failed

**How Reworkd stores it**: In `meeting.data.reworkd.last_scraped_date` and `meeting.data.reworkd.create_date`

**How conventional scrapers will store it**: In `meeting.data.cityscrapers.last_scraped_date` and `meeting.data.cityscrapers.create_date`

**Files to modify**: Meeting data builder (`builders.py`) and scraper output format

**Work Item 2: Smart Status Management** (1.5 days)

**Current situation**: The Meeting Analysis Service has advanced logic that:
- Detects outdated meetings (not scraped in >24 hours)
- Prevents false "canceled" status when data is stale
- Distinguishes between DELETED vs RESCHEDULED meetings
- Handles duplicate detection when meetings appear multiple times

**Problem**: This logic ONLY works for Reworkd meetings (checks `data.reworkd.last_scraped_date`)

**What we need**: Extend this logic to work with BOTH sources:
- Check Reworkd timestamps: `data.reworkd.last_scraped_date`
- Check conventional timestamps: `data.cityscrapers.last_scraped_date`

**Key capabilities to preserve**:
1. **Status preservation**: If meeting data is >24 hours old, keep existing status instead of marking as "canceled"
2. **Deletion detection**: Mark meeting as DELETED if not scraped for >72 hours (3 days)
3. **Rescheduling detection**: If an old meeting disappears but a similar meeting appears later, mark as RESCHEDULED
4. **Duplicate handling**: If two meetings exist for same time/agency, mark older one as DELETED

**Files to modify**: Meeting analysis service (`services.py`)

**Benefit**: Prevents false cancellations for ALL 300+ agencies, not just the 12 Reworkd ones

**Work Item 3: Generic Data Properties** (0.5 days)

**Current situation**: The Meeting model has two properties that only work for Reworkd:
- `meeting.reworkd_last_scraped_date` - reads from `data.reworkd.last_scraped_date`
- `meeting.reworkd_create_date` - reads from `data.reworkd.create_date`

**Problem**: Code throughout the system uses these Reworkd-specific properties. If we just add conventional timestamps, we'd need to update code everywhere to check both sources.

**Solution**: Create unified properties that automatically check BOTH sources:
- `meeting.last_scraped_date` - checks conventional first, falls back to Reworkd
- `meeting.create_date` - checks conventional first, falls back to Reworkd

**How it works**:
1. Try to read from conventional source (`data.cityscrapers.last_scraped_date`)
2. If not found, fall back to Reworkd source (`data.reworkd.last_scraped_date`)
3. Return whichever is found

**Benefit**:
- Single API works for all meetings (Reworkd, conventional, or mixed)
- No need to update code in dozens of places
- Future-proof for when we remove Reworkd entirely

**Files to modify**: Meeting model (`models.py`)

**Work Item 4: Meeting Analysis Service Updates** (1.5 days)

**Current situation**: The `MeetingAnalysisService` performs sophisticated data quality checks:
- **Deduplication**: Finds and removes duplicate meetings (same time/agency)
- **Deletion detection**: Identifies meetings that disappeared from source
- **Rescheduling detection**: Links canceled meetings to their rescheduled versions
- Uses timestamps to determine which meeting is "newer" in duplicate scenarios

**Problem**: All these checks use Reworkd-specific timestamp properties:
- `meeting.reworkd_last_scraped_date` - to determine if data is stale
- `meeting.reworkd_create_date` - to determine which duplicate is newer

**What we need**: Update service to use the new unified properties:
- Replace `meeting.reworkd_last_scraped_date` → `meeting.last_scraped_date`
- Replace `meeting.reworkd_create_date` → `meeting.create_date`

**How it works** (deduplication example):
1. Find all meetings at same date/time for same agency
2. Compare their `create_date` timestamps to see which came first
3. Mark older meeting as DELETED (duplicate of newer one)
4. Preserve the newer meeting

**Why this matters**: These are the MOST critical features from Reworkd that we want to preserve:
- Automatic duplicate cleanup
- Smart deletion vs. reschedule detection
- Prevents data quality issues at scale

**Files to modify**: Meeting analysis service (`services.py` - lines 124-297)

**Work Item 5: Anomaly Detection Enhancement** (1 day)

**Current situation**: The system has anomaly detection that monitors for unusual patterns:
- Sudden spike in number of meetings
- Meetings with missing critical data (no date, no location)
- Unusual meeting times (e.g., 3am meetings)
- Duplicate meetings being created

**Problem**: May not work properly with conventional scraper data due to:
- Different field names (Reworkd uses "title", conventional uses "name")
- Different data structures (Reworkd stores in `data.reworkd.data`, conventional in `data.extras`)
- Different status values or formats

**What we need**:
1. **Field mapping**: Ensure anomaly detector can read data regardless of format
2. **Unified checks**: Apply same quality standards to both Reworkd and conventional data
3. **Testing**: Verify anomaly detection triggers correctly for conventional scrapers

**Example scenarios to detect**:
- A scraper that suddenly returns 500 meetings instead of usual 20
- Meetings with no start_date or malformed dates
- Same meeting imported twice with different IDs

**Why this matters**: Catches scraper bugs early before bad data reaches users

**Files to modify**: Anomaly detection service (need to locate this - may be in monitoring/alerts)

**Work Item 6: Import Filter System** (1.5 days)
- Add new database field `conventional_import_from_date` to track cutoff dates
- Implement bi-directional migration logic (TO Reworkd and FROM Reworkd)
- Create smart filtering to prevent duplicate imports
- **→ Most critical update - prevents data corruption during migration**

**Business value**: One-time investment that benefits ALL agencies going forward

---

#### Phase 2: Agency Migration

**What we're doing**: Migrating each agency individually

**For Agencies with Existing Scrapers (1 day each):**

1. **Update Scraper Code** (0.5 days)
   - Add timestamp tracking
   - Ensure compatibility with new platform features

2. **Staging Migration** (0.5 days)
   - Find last Reworkd meeting date (or decide the cut off date, clear Reworkd meetings after that date)
   - Set cutoff date (last date + 1 day) to prevent duplicates
   - Clear Reworkd migration flag to stop Reworkd imports
   - Run scraper

**For Agencies Needing New Scrapers (using Harambe + Reworkd code):**

**Why Harambe + Reworkd Code (Not Scrapy from Scratch):**
- **Higher Accuracy**: Reworkd code already QA'd and tested in production
- **Better Data Handling**: Reworkd code handles edge cases and special scenarios
- **Faster Development**: Reuse proven logic vs building from scratch (1-2 days vs 3-5 days)
- **Less Risk**: Known working code reduces chance of data quality issues

**Alternative (Not Recommended)**: Building new Scrapy scrapers from scratch would take 3-5 days per agency and require re-discovering all edge cases that Reworkd already handles.

---

##### Approach A: Simple Listing Scraper (1 day per agency)

1. **Copy Reworkd code** (2 hours)
   - Copy `listing.py` scrape function from Reworkd
   - Create new file in `harambe_scrapers/agency_name.py`

2. **Add integration wrapper** (2 hours)
   - Add observer pattern with `DataCollector`
   - Transform data to OCD format using `create_ocd_event()`
   - Add main function with SDK.run() setup

3. **Test and validate** (2 hours)
   - Run scraper and verify data output
   - Check data format matches OCD schema
   - Validate timestamps and metadata

4. **Write unit tests** (2 hours)
   - Create test file `tests/test_agency_name_v2.py`
   - Test scraper logic, data transformation, error handling
   - Validate meeting data structure

**Example**: `det_police_fire_retirement.py`, `det_dwcpa.py`

**Estimate**: 6 agencies × 1 day = 6 days

##### Approach B: Orchestration Flow (2 days per agency)

**Implementation steps**:
1. **Copy Reworkd code** (4 hours)
   - Copy `category.py`, `listing.py`, `detail.py` from Reworkd
   - Place in `harambe_scrapers/extractor/agency_name/` directory
   - Create `__init__.py` file

2. **Build orchestrator** (6 hours)
   - Create orchestrator class with three stages:
     - Stage 1: Category scraper finds listing pages
     - Stage 2: Listing scraper finds event detail pages
     - Stage 3: Detail scraper extracts meeting data
   - Add observer pattern for data collection
   - Handle fallback extraction for missing data

3. **Test full workflow** (4 hours)
   - Run complete orchestration flow
   - Verify data from all three stages
   - Test error handling and fallback logic
   - Validate data quality and completeness

4. **Write comprehensive tests** (2 hours)
   - Test each stage independently
   - Test full orchestration flow
   - Test error handling and edge cases

**Example**: `det_police_department.py` (3-stage orchestration)

**Estimate**: 4 agencies × 2 days = 8 days

##### Staging Migration Process (Same for both approaches)

**For each agency**:
1. Find last Reworkd meeting date (or decide cutoff date)
2. Clear Reworkd meetings after cutoff date in staging
3. Set `conventional_import_from_date` (last date + 1 day) to prevent duplicates
4. Clear Reworkd migration flag to stop Reworkd imports
5. Run new scraper in staging
6. Validate data quality and completeness
7. Deploy to production

**Business value**: Each agency migrates independently, minimizing risk

---

#### Phase 3: QA the new scrapers data

**What we're doing**: Comprehensive quality assurance for the migrated agencies

**QA checklist**:
- ✅ Verify no meetings were lost during migration
- ✅ Check for duplicate meetings at the cutoff dates
- ✅ Confirm data quality matches what Reworkd provided
- ✅ Test that all new features work (deletion detection, status preservation, anomaly detection)
- ✅ Monitor scraper performance and reliability
- ✅ Compare before/after data to ensure consistency
- ✅ Document any issues found and fix them

**Business value**: Ensures data integrity and user confidence

---

#### Phase 4: Cleanup (1.5 days)

**What we're doing**: Removing old Reworkd code and optimizing the system after MIGRATING ALL Reworkd scrapers in production to conventional scrapers

**Cleanup Work Item 1: Remove Reworkd Dependencies** (1 day)
- Remove the `with_reworkd_migration()` queryset dependency
- Simplify import filter logic (no longer needs TO Reworkd direction)
- Clean up unnecessary complexity in codebase
- Ensure all agencies use unified code path

**Cleanup Work Item 2: Archive Reworkd Properties** (0.5 days)
- Removal of `reworkd_last_scraped_date` and `reworkd_create_date`
- Keep `conventional_import_from_date` permanently (prevents reimporting old data)

**Business value**: Cleaner, faster, more maintainable system

---

## WEEK-BY-WEEK SCHEDULE

### Week 1: Platform Preparation (5 days)
- Days 1-5: Complete all 6 work items from Phase 1
- Deliverable: Enhanced platform ready for migration

### Week 2: Simple Scrapers - Batch 1 (5 days)
- Day 1: Greater Cleveland Regional Transit Authority
- Day 2: Cleveland City Planning Commission
- Day 3: Michigan Belle Isle Park Advisory Committee
- Day 4: Detroit Wayne County Port Authority
- Day 5: Cuyahoga County Arts & Culture

### Week 3: Simple + Orchestration Start (5 days)
- Day 1: Cleveland Board of Building Standards (simple)
- Day 2-3: Great Lakes Water Authority (orchestration)
- Day 4-5: Wayne County Commission (orchestration)

### Week 4: Orchestration Finish + QA (4-5 days)
- Day 1-2: Cuyahoga County Emergency Services (orchestration)
- Day 3-4: Cuyahoga County Council (orchestration)
- Day 5: Comprehensive QA across all 10 agencies

### Week 5 (Optional): Final QA & Cleanup (2-3 days if needed)
- Validate all migrations successful
- Remove Reworkd dependencies
- Production deployment
- Monitor initial production runs

**Total Timeline**: 17-23 days = 3.5-4.5 weeks (with buffer)

---

## TECHNICAL APPROACH

### Why Harambe Framework?

**Advantages**:
- ✅ **Reuse existing code** - Reworkd already built and tested all scraper logic
- ✅ **Faster development** - Just copy scrape functions and add wrapper
- ✅ **JavaScript support** - Handles dynamic content with Playwright browsers
- ✅ **Proven patterns** - Already built 2 production scrapers successfully
- ✅ **Better reliability** - Real browser context handles complex websites

### Implementation Patterns

**Pattern 1: Simple Listing Scraper**
1. Copy Reworkd's listing scrape function (unchanged extraction logic)
2. Add integration wrapper with data collector
3. Configure to save output to JSONLINES file format
4. Add observer pattern to collect meeting data

**Pattern 2: Orchestration Flow**
1. Create orchestrator class with three stages:
   - **Stage 1 (Category)**: Find all listing pages on website
   - **Stage 2 (Listing)**: Find all event detail pages from listings
   - **Stage 3 (Detail)**: Extract meeting data from each event page
2. Add data collection observer at each stage
3. Transform extracted data to Open Civic Data (OCD) format
4. Handle fallback logic when data is missing

---

## RISK MITIGATION

### Risk 1: Scraper Failures During Migration
**Mitigation**:
- Deploy new monitoring system first (Phase 1)
- Migrate agencies one at a time
- Keep Reworkd running in parallel during transition

### Risk 2: Data Duplication
**Mitigation**:
- Import filter system prevents duplicates (`conventional_import_from_date`)
- Careful cutoff date selection per agency
- QA validation checks for duplicates

### Risk 3: Missing Meetings
**Mitigation**:
- Run both systems in parallel during staging
- Compare meeting counts before/after
- Manual review of high-priority agencies

### Risk 4: Timeline Delays
**Mitigation**:
- Buffer time built into schedule (3.5-4.5 weeks with buffer)
- Can parallelize work with multiple developers
- Simple scrapers can be done independently

---

---

## OPTIONAL FUTURE ENHANCEMENTS (Post-Migration)

After completing both initiatives, these optional improvements could further enhance the platform:

### a. Enhanced Monitoring & Alerting (3-5 days)
- **What**: Real-time failure detection and notification system
- **Channels**: Slack, email, or SMS alerts for critical failures
- **Benefits**: Reduce detection time from hours/days to minutes
- **Effort**: 3-5 days development + infrastructure setup
- **When**: After Initiative 1 complete, before scaling Initiative 2

### b. Advanced Data Tracking (2-3 days)
- **What**: Extended metadata beyond basic timestamps
- **Include**: Scrape duration, retry count, data quality scores
- **Purpose**: Enable detailed freshness monitoring and quality assurance
- **Effort**: 2-3 days development
- **When**: Can be done anytime after Phase 0 complete

### c. Infrastructure Modernization (5-10 days)
- **Logging**: Centralized log aggregation for better debugging
- **Dashboard**: Visual monitoring interface for scraper health
- **Analytics**: Performance trends and anomaly detection
- **Effort**: 5-10 days development + infrastructure setup
- **When**: After both initiatives stabilize in production

**Total Optional Enhancements**: 10-18 days additional work (can be spread over time)

**Note**: These are nice-to-have improvements. The core platform (Phase 0) plus both initiatives already provide significant value without these extras.

---

# INITIATIVE 2: UPGRADE 300+ CONVENTIONAL SCRAPERS

---

## Business Impact - Initiative 2

**What This Means for Users:**
- **Fewer false cancellations** - System won't mark meetings as "canceled" when scrapers fail
- **Cleaner data** - Automatic duplicate removal
- **Better accuracy** - Rescheduled meetings properly linked to originals
- **Consistent experience** - All 300+ agencies have same data quality

**What This Means for Operations:**
- **Reduced maintenance** - 20-30% less time spent on manual data cleanup
- **Unified platform** - All agencies work the same way
- **Better data quality** - Consistent behavior across all scrapers
- **Scalable solution** - Future scrapers automatically get these features

---

## OVERVIEW - Initiative 2

### The Goal: Give Conventional Scrapers Reworkd's Advanced Features

**This is a SEPARATE initiative from migrating the 12 Reworkd agencies.** This is about upgrading the existing 300+ conventional scrapers to have the same advanced features that Reworkd provides.

**What Reworkd does that conventional scrapers don't:**
- Tracks **last_scraped_date** - when we last checked this meeting
- Tracks **create_date** - when we first discovered this meeting
- Uses these timestamps to:
  - Detect stale data (not updated in >24 hours)
  - Distinguish deleted meetings from scraper failures
  - Find and remove duplicate meetings
  - Detect when meetings are rescheduled vs canceled

**What conventional scrapers currently do:**
- Extract meeting data from websites
- Save to database
- **Missing:** No timestamp tracking = can't tell if data is fresh or stale

### What Needs to Change

**Phase 1: Platform Preparation (Already Covered Above):**

The same Phase 1 work items (1-6) from Initiative 1 ALSO enable Initiative 2 (conventional scraper upgrades). This is the shared infrastructure that makes both initiatives possible.

**After Phase 1 is complete:** Platform is ready to receive timestamps from conventional scrapers, but each scraper needs a small update to start sending timestamps

---

### Upgrading Individual Scrapers (5-10 minutes each)

**Current state (verified from codebase analysis):**
- ❌ Harambe scrapers: DO NOT currently output timestamp fields
- ❌ Scrapy scrapers: DO NOT currently output timestamp fields
- ✅ Both types already output meeting data in correct format, just missing timestamps

**What needs to be added:**

Each scraper needs to add two timestamp fields to its output:
- **last_scraped_date**: Current date/time when scraper runs (ISO format with timezone)
- **create_date**: Current date/time when scraper runs (ISO format with timezone)

**Where to add:** In the meeting data extras section (same section that already contains agency name and meeting ID)

**Developer effort:** 5-10 minutes per scraper

---

### Benefits of Adding Timestamps

**Without timestamps** (current state):
- ❌ Scraper fails → meetings appear "canceled" (false positive)
- ❌ Duplicate meetings can accumulate
- ❌ No way to detect rescheduled meetings
- ❌ Manual cleanup required

**With timestamps** (after upgrade):
- ✅ Scraper fails → system knows data is stale, preserves status
- ✅ Duplicate meetings automatically detected and removed
- ✅ Rescheduled meetings linked to originals
- ✅ Better data quality with zero manual work

---

## Timeline & Resources - Initiative 2

### Rollout Strategy

**Important**: Initiative 2 can proceed independently after Phase 1 (Platform Preparation) is complete.

| Phase | Target | What Gets Updated | Effort | Timeline |
|-------|--------|-------------------|--------|----------|
| **Phase 1** | Platform code (shared with Initiative 1) | 6 work items in documenters codebase | 5 days | Week 1 |
| **After Initiative 1 Complete** | 12 Reworkd agencies | Already have timestamps from Harambe migration | 0 additional | Done in Weeks 2-4 |
| **Wave 1** | 20-30 high-priority conventional scrapers | Add timestamps to existing Scrapy scrapers | 5-10 min each | Weeks 5-8 (or later) |
| **Wave 2** (Ongoing) | Remaining 270+ scrapers | Add timestamps during maintenance | 5-10 min each | Ongoing as needed |

---

### Which Scrapers to Upgrade First?

**High Priority** (upgrade in Phase 3):
- Chicago, Detroit, Cleveland city councils (high traffic)
- Agencies with frequent cancellations/rescheduling
- Agencies with assignment/documenter activity
- Agencies where duplicates are common

**Medium Priority**:
- Stable scrapers with moderate traffic
- Agencies with occasional data issues

**Low Priority**:
- Rarely updated agencies
- Deprecated agencies
- Scrapers already scheduled for Harambe migration

**Note:** The 12 Reworkd agencies being migrated with Harambe will automatically get timestamps built-in.

---

### Expected Impact

**After Phase 1 (platform ready):**
- Infrastructure ready for 300+ scrapers
- No user-facing changes yet (scrapers need updates first)

**After Phase 3 (20-30 high-priority scrapers upgraded):**
- 50-80% reduction in false cancellations for upgraded agencies
- Better duplicate detection and removal
- Automatic rescheduling detection
- Covers ~40-50% of total meeting volume

**After Phase 4 (most scrapers upgraded):**
- Consistent data quality across all 300+ agencies
- 20-30% reduction in maintenance time
- Unified platform behavior
- Same advanced features as Reworkd for all agencies

---

# SHARED FOUNDATION (PHASE 1)

---

## Phase 1: Platform Preparation (5 days) - Benefits BOTH Initiatives

**What we're doing**: Upgrading platform infrastructure to support Reworkd-like features for ALL scrapers

**Why it's shared**: These platform upgrades enable:
- Initiative 1: Migrating 12 Reworkd agencies back with full feature preservation
- Initiative 2: Upgrading 300+ conventional scrapers with advanced features

### Work Items (Already Approved)

**Work Item 1: Enhanced Meeting Data Storage** (0.5 days)
- Update how meetings store timestamp information
- Add capability to track when each meeting was last checked by scrapers
- Store the original date when meetings were first discovered
- Ensures we can detect stale or deleted meetings

**Work Item 2: Smart Status Management** (1.5 days)
- Implement logic to preserve meeting status when data becomes stale (>24 hours old)
- Prevent false "canceled" status for meetings that simply haven't been updated
- Add intelligent detection for DELETED vs RESCHEDULED meetings
- Mirrors the advanced features in Reworkd import flow

**Work Item 3: Generic Data Properties** (0.5 days)
- Create/update two properties of Meeting model that check both data from scrapers and reworkd
- Property 1: last_scraped_date - checks cityscrapers last scrape date first, falls back to reworkd
- Property 2: create_date - checks cityscrapers create date first, falls back to reworkd

**Work Item 4: Meeting Analysis Service Updates** (1.5 day)
- Upgrade service to detect outdated meetings from both Reworkd and conventional sources
- Update duplicate detection to work with new timestamp fields
- Support both data formats simultaneously during transition

**Work Item 5: Anomaly Detection Enhancement** (1 day)
- Extend anomaly detection to work with conventional scraper data
- Map different field names between systems (e.g., "name" vs "title")
- Ensure quality checks work for all agencies, not just Reworkd ones

**Work Item 6: Import Filter System** (1.5 days)
- Add new database field 'conventional_import_from_date' to track cutoff dates
- Implement bi-directional migration logic (TO Reworkd and FROM Reworkd), create smart filterings to prevent duplicate imports
- Most critical update - prevents data corruption during migration

**Business value**: One-time investment (5 days) that enables both initiatives and benefits ALL 300+ agencies

---

## SUCCESS CRITERIA

### Initiative 1 (Reworkd Migration - Required)
- ✅ All 12 Reworkd agencies successfully migrated to conventional scrapers
- ✅ Zero data loss (all meetings preserved)
- ✅ No duplicate meetings at migration cutoff dates
- ✅ Scraper success rate matches or exceeds Reworkd baseline
- ✅ Reworkd dependencies completely removed from codebase
- ✅ Team trained on Harambe scraper maintenance

### Initiative 2 (Conventional Scraper Upgrades - Important)
- ✅ Platform enhancements deployed (Phase 1 shared foundation complete)
- ✅ 20-30 high-priority scrapers upgraded with timestamp tracking
- ✅ Measurable reduction in false cancellations for upgraded agencies (50-80%)
- ✅ Documentation for upgrading remaining scrapers
- ✅ Rollout plan for remaining 270+ scrapers

---

## NEXT STEPS

### Phase 1: Shared Foundation (Week 1)
1. ✅ Approve both initiatives and shared platform work
2. ✅ Begin Platform Preparation - Phase 1 (5 days)
3. Complete all 6 work items
4. Deliverable: Platform ready for both initiatives

### Initiative 1: Reworkd Migration (Weeks 2-5)
1. Start migrating Reworkd agencies - Phase 2
2. QA and validate migrations - Phase 3
3. Clean up Reworkd dependencies - Phase 4 (1.5 days)
4. Communicate with stakeholders about migration schedule
5. Monitor production performance

### Initiative 2: Conventional Upgrades (Weeks 5+ or parallel)
1. Identify 20-30 high-priority scrapers for first wave
2. Schedule developer time for scraper upgrades (5-10 min each)
3. Monitor impact and data quality improvements
4. Create rollout plan for remaining 270+ scrapers
5. Expand incrementally based on priority

---

*Last Updated: 2025-11-04*

**Initiative 1 Progress:** 2/12 agencies completed (17%) | Estimated Completion: 3.5-4.5 weeks

**Initiative 2 Status:** Platform preparation required first | Then ongoing incremental rollout
