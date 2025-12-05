# Reworkd Migration: Options & Estimates

## Executive Summary

**The Situation:**
- Reworkd (external scraping vendor) shutting down by end of 2025
- 12 government agencies must migrate back to in-house system
- Must choose migration path and complete before vendor shutdown

**Business Impact:**
- ✅ Cost savings: Eliminate monthly Reworkd subscription fees
- ✅ Vendor independence: Full control over scraping infrastructure
- ✅ Unified system: All 300+ agencies on same platform
- ✅ No user disruption: Seamless transition for meeting data

---

## Migration Options Comparison

### Option 1: Enhanced Conventional Scrapers (RECOMMENDED)
**Upgrade existing Python/Scrapy infrastructure with modern monitoring**

#### Timeline: 3-5 weeks total
- **Phase 1: Platform Preparation** (5 days)
  - Enhanced meeting data storage (0.5 days)
  - Smart status management (1.5 days)
  - Generic data properties (0.5 days)
  - Meeting analysis service updates (1.5 days)
  - Anomaly detection enhancement (1 day)
  - Import filter system (1.5 days)

- **Phase 2: Agency Migration** (2-3 weeks)
  - Agencies with existing scrapers: 1 day each × 8 agencies = 8 days
  - Agencies needing new scrapers: 2-3 days each × 4 agencies = 8-12 days

- **Phase 3: QA & Validation** (2-3 days)
  - Verify no data loss
  - Check for duplicates
  - Monitor scraper performance

- **Phase 4: Cleanup** (1.5 days)
  - Remove Reworkd dependencies
  - Archive old properties

#### Advantages
✅ **Full control** - Complete ownership of code and infrastructure
✅ **Cost-effective** - No vendor fees, only infrastructure costs
✅ **Proven technology** - Already managing 300+ agencies successfully
✅ **Customizable** - Can implement any specific business logic
✅ **Enhanced monitoring** - Real-time failure detection and alerts
✅ **Fastest migration** - Leverages existing code and knowledge

#### Disadvantages
❌ **Manual updates required** - Must update selectors when websites change
❌ **Technical expertise needed** - Requires skilled Python/Scrapy developers
❌ **Limited JavaScript support** - Struggles with heavily dynamic content
❌ **Maintenance overhead** - Ongoing monitoring and fixes needed

#### Cost Estimate
- **Development**: 3-5 weeks × developer rate
- **Ongoing**: Infrastructure costs only (~100-500/month for Azure)
- **Maintenance**: 2-4 hours/month per scraper on average

---

### Option 2: Harambe (Reworkd's Open Source Framework)
**Self-hosted browser automation using Playwright**

#### Implementation Approaches

**Approach A: Single-Stage Scraper (Reuse Reworkd Listing Logic)**
- Copy Reworkd's listing.py scrape function directly
- Add observer pattern + OCD transformation wrapper
- Examples: `det_police_fire_retirement.py`, `det_dwcpa.py`

**Approach B: Multi-Stage Orchestration (Category → Listing → Detail)**
- Reuse Reworkd's category.py, listing.py, detail.py files
- Build orchestrator to coordinate all three stages
- Example: `det_police_department.py` (3-stage orchestration)

**Approach C: Hybrid**
- Some agencies use single-stage (simpler websites)
- Some agencies use multi-stage (complex pagination/detail pages)

#### Timeline: 2.5-3.5 weeks total (FASTEST OPTION)

- **Phase 1: Platform Preparation** (5 days) - Same as Option 1

- **Phase 2: Harambe Setup** (SKIP - Already Done!)
  - ✅ Harambe already installed and working
  - ✅ Team already built 2 production scrapers successfully
  - ✅ Patterns documented and proven

- **Phase 3: Agency Migration** (2-2.5 weeks for 10 remaining agencies)

  **Already Completed** (2 agencies)
  - ✅ Detroit Board of Police Commissioners (orchestration)
  - ✅ Detroit Police and Fire Retirement System (simple)

  **Approach A: Simple Listing Scraper** (1 day per agency)
  - Reuse Reworkd listing.py scrape logic
  - Integrate to scraping workflow (observer pattern + OCD transformation)
  - Observe result and fix if failed
  - Write unit tests
  - **Estimate**: 6 agencies × 1 day = 6 days

  **Approach B: Orchestration Flow** (2 days per agency)
  - Reuse Reworkd category.py, listing.py, detail.py logic
  - Build orchestration flow to coordinate stages
  - Observe result and fix if failed
  - Write unit tests
  - **Estimate**: 4 agencies × 2 days = 8 days

  **Total Migration**: 6 + 8 = 14 days (2.8 weeks)

  **Can parallelize**: Multiple developers can work on different agencies simultaneously

- **Phase 4: QA & Cleanup** (2-3 days)
  - Final validation of all scrapers
  - Remove Reworkd dependencies
  - Production deployment

#### Advantages
✅ **FASTEST development** - 2.5-3.5 weeks total (vs 3-5 weeks for Option 1)
✅ **LOWEST development cost** - Just copy existing Reworkd code + add wrapper
✅ **Proven code quality** - Reworkd already built and tested all scraper logic
✅ **Team ready** - Already built 2 production Harambe scrapers successfully
✅ **Ahead of schedule** - 2 of 12 already completed!
✅ **JavaScript support** - Handles dynamic content effectively
✅ **Real browser context** - Executes JavaScript, handles sessions
✅ **Open source** - No licensing costs
✅ **Minimal code writing** - Reuse existing scrape functions, just add integration layer

#### Disadvantages
❌ **Higher infrastructure costs** - Browser servers more expensive than basic scrapers (~500-1500/month vs 100-500/month)
❌ **Resource intensive** - Browser instances consume significant memory
❌ **Slower performance** - Browser rendering adds latency vs direct HTTP requests
❌ **No LLM integration** - Still relies on CSS selectors (manual updates needed when sites change)
❌ **No vendor support** - Must handle all maintenance internally (but we have Reworkd's working code as reference)

#### Cost Estimate
- **Development**: 3-4 weeks × developer rate (**LOWEST** - just integration work, not building from scratch)
- **Ongoing**: Higher infrastructure costs (~500-1500/month for browser servers)
- **Maintenance**: 2-4 hours/month per scraper (same as Option 1, but can reference Reworkd code)

---

### Option 3: Browserbase + Stagehand (LLM-Powered)
**AI-driven scraping with serverless deployment**

#### Timeline: 5-8 weeks total
- **Phase 1: Platform Preparation** (5 days) - Same as Option 1
- **Phase 2: Browserbase Integration** (5-7 days)
  - Set up Browserbase API account
  - Configure serverless infrastructure (AWS Lambda/Azure Functions)
  - Implement LLM integration (OpenAI/Claude API)
  - Build extraction prompt templates
  - Set up cloud storage pipeline
- **Phase 3: Agency Migration** (3-5 weeks)
  - Design LLM prompts per agency: 2 days each × 12 = 24 days
  - Test and refine prompts: 0.5 days each × 12 = 6 days
  - (Note: Faster initial development, but requires extensive testing)
- **Phase 4: Extended QA & Validation** (5-7 days)
  - Validate LLM output consistency
  - Test across multiple scraping runs
  - Tune prompts for accuracy
- **Phase 5: Cleanup** (1.5 days)

#### Advantages
✅ **Reduced development effort** - LLMs generate scraping logic automatically
✅ **Adaptive intelligence** - Automatically handles website structure changes
✅ **Self-healing** - Can adapt when websites update layouts
✅ **Better accuracy** - Semantic understanding of content
✅ **Future-proof** - Requires minimal maintenance for website changes

#### Disadvantages
❌ **Output consistency issues** - LLM outputs may vary between runs
❌ **No universal solution** - Each website needs custom prompts
❌ **High operational costs** - LLM API calls + Browserbase sessions
❌ **Performance impact** - Increased latency (LLM processing time)
❌ **Service dependencies** - Relies on external APIs (OpenAI/Claude + Browserbase)
❌ **Unproven at scale** - Limited track record for production use
❌ **Quality assurance complexity** - Harder to validate AI-generated outputs

#### Cost Estimate
- **Development**: 5-8 weeks × developer rate
- **Ongoing operational costs** (PER SCRAPER, PER DAY):
  - Browserbase sessions: Low per-scrape cost
  - LLM API calls: Low per-scrape cost
  - **Example**: 12 scrapers running daily = moderate monthly cost
  - **At scale**: Could reach 500-2000/month depending on volume
- **Infrastructure**: Serverless function costs (~50-200/month)
- **Maintenance**: 1-2 hours/month per scraper (less manual updates)

---

### Option 4: Scrapfly.io (Commercial Service)
**Managed anti-blocking API with extraction options**

#### Timeline: 4-6 weeks (similar to Harambe)
- Platform preparation, API integration, migration, QA, cleanup

#### Advantages
✅ **Anti-blocking features** - High success rate bypassing protections
✅ **Managed infrastructure** - Service handles scaling and reliability
✅ **Multiple extraction methods** - CSS selectors or AI models
✅ **Cloud browser support** - Handles dynamic JavaScript content

#### Disadvantages
❌ **Vendor dependency** - Same risk as Reworkd situation
❌ **Ongoing subscription costs** - Per-API-call pricing
❌ **CSS selector maintenance** - Still requires manual updates (unless using AI)
❌ **AI extraction limitations** - Fixed models or variable LLM outputs
❌ **Not cost-effective** - Similar costs to Browserbase without advantages

#### Cost Estimate
- **Development**: 4-6 weeks × developer rate
- **Ongoing**: 200-1000+/month depending on volume
- **Maintenance**: 2-4 hours/month per scraper

---

## Side-by-Side Comparison

| Criteria | Option 1: Enhanced Conventional | Option 2: Harambe | Option 3: Browserbase+LLM | Option 4: Scrapfly |
|----------|-------------------------------|-------------------|--------------------------|-------------------|
| **Timeline** | 3-5 weeks | **2.5-3.5 weeks** ⭐ | 5-8 weeks | 4-6 weeks |
| **Development Cost** | $$ | **$** ⭐ (2/12 done!) | $$$ | $$ |
| **Monthly Operational Cost** | **100-500** ⭐ | 500-1500 | 500-2000+ | 200-1000+ |
| **Maintenance Burden** | Medium | Medium | Low | Medium |
| **JavaScript Support** | Poor | **Excellent** ⭐ | Excellent | Excellent |
| **Auto-adapts to Changes** | ❌ | ❌ | ✅ | Partial |
| **Vendor Independence** | ✅ | ✅ | ❌ | ❌ |
| **Proven at Scale** | ✅ | **Partial** (3 built) | ❌ | ✅ |
| **Team Expertise** | High | **Medium** (3 built) | Low | Medium |
| **Risk Level** | Low | **Low** ⭐ | High | Medium |
| **Code Reusability** | Low (build from scratch) | **High** ⭐ (copy Reworkd) | Medium | Low |

---

## Recommendation: Option 2 (Harambe) - REVISED

### Why This Option? (Key Insights)

1. **FASTEST Development**: 2.5-3.5 weeks (faster than Option 1!)
   - Simply copy existing Reworkd scrape functions
   - 2 of 12 agencies already completed (17% done!)
   - Only 10 agencies remaining to migrate

2. **LOWEST Development Cost**: Just integration work
   - No need to build scrapers from scratch
   - Reworkd already did the hard work (CSS selectors, pagination logic, edge cases)
   - Team just adds observer pattern wrapper + OCD transformation

3. **Better Technology**: Handles JavaScript properly
   - Conventional scrapers struggle with dynamic content
   - Harambe uses real browsers (Playwright)
   - More robust for modern government websites

4. **Low Risk**: Team already proven capable
   - Successfully built 3 Harambe scrapers already
   - Pattern is well-established and documented
   - Can reference Reworkd code when issues arise

5. **Full Control**: No vendor dependency
   - Open source framework
   - Self-hosted infrastructure
   - Can customize as needed

### Trade-off: Higher Operational Cost

**The Cost Difference:**
- Option 1: 100-500/month (basic HTTP scrapers)
- Option 2: 500-1500/month (browser automation servers)
- **Extra cost**: ~400-1000/month

**Why It's Worth It:**
- ✅ Saves ~2 weeks of development time ($$$$ in developer costs)
- ✅ Better reliability for JavaScript-heavy sites
- ✅ Can reuse proven Reworkd code (less debugging)
- ✅ Future-proof for modern web technologies

### Alternative: Option 1 (Enhanced Conventional)

**Choose Option 1 if:**
- Budget is extremely tight (need lowest operational cost)
- Most agencies have simple HTML websites
- Team wants to build from scratch for learning purposes
- Long-term maintenance cost is priority over development speed

**Trade-offs:**
- Slower development (3-5 weeks vs 3-4 weeks)
- More development work (build from scratch vs copy code)
- JavaScript limitations (may need Harambe for 2-3 agencies anyway)
- Higher risk of scraper failures on dynamic sites

### Hybrid Approach (Not Recommended)

Mixing Option 1 + Option 2 creates complexity:
- Two different infrastructures to maintain
- Two different monitoring systems
- Two different debugging processes
- Marginal cost savings (200-300/month) not worth operational complexity

---

## Implementation Plan (Option 2: Harambe)

### Week 1: Platform Preparation (5 days)
- Upgrade meeting data models with timestamp tracking
- Implement smart status management
- Build import filter system
- Deploy to staging environment
- ✅ Pattern already documented (2 production examples)

### Week 2: Simple Listing Scrapers - Batch 1 (5 days)
- Day 1: Greater Cleveland Regional Transit Authority
- Day 2: Cleveland City Planning Commission
- Day 3: Michigan Belle Isle Park Advisory Committee
- Day 4: Detroit Wayne County Port Authority (✅ **DONE TODAY**)
- Day 5: Cuyahoga County Arts & Culture

### Week 3: Simple + Orchestration (5 days)
- Day 1: Cleveland Board of Building Standards (simple)
- Day 2-3: Great Lakes Water Authority (orchestration) - 2 days
- Day 4-5: Wayne County Commission (orchestration) - 2 days

### Week 4: Orchestration Scrapers + QA (4-5 days)
- Day 1-2: Cuyahoga County Emergency Services Advisory Board (orchestration)
- Day 3-4: Cuyahoga County Council (orchestration)
- Day 5: Comprehensive QA across all 10 remaining agencies

### Week 5 (Optional): Final QA & Cleanup (2-3 days if needed)
- Validate no data loss or duplicates
- Remove Reworkd dependencies
- Production deployment
- Monitor initial production runs

**Total**: 17-19 days = 3.5-4 weeks (with buffer)
**Progress**: 2/12 completed (17% done)

---

## Risk Mitigation

### Risk 1: Scraper Failures During Migration
**Mitigation**:
- Deploy new monitoring system first (Phase 1)
- Migrate agencies one at a time
- Keep Reworkd running in parallel during transition

### Risk 2: Data Duplication
**Mitigation**:
- Import filter system prevents duplicates (conventional_import_from_date)
- Careful cutoff date selection per agency
- QA validation checks for duplicates

### Risk 3: Missing Meetings
**Mitigation**:
- Run both systems in parallel during staging
- Compare meeting counts before/after
- Manual review of high-priority agencies

### Risk 4: JavaScript-Heavy Websites
**Mitigation**:
- Identify JavaScript-heavy sites upfront
- Use Harambe for those specific agencies if needed
- Hybrid approach keeps costs down

---

## Next Steps

1. **Decision Required**: Choose between Option 1 (Enhanced Conventional) vs Option 2 (Harambe)
   - **Option 2 recommended**: Faster development, proven code reuse, better technology
   - **Trade-off**: ~400-1000/month higher operational cost

2. **Resource Allocation**:
   - 1 senior developer for 4-5 weeks (Option 2) or 3-5 weeks (Option 1)
   - Can parallelize with junior developers after Week 1 (platform prep)

3. **Infrastructure Setup** (Option 2 only):
   - Provision Playwright browser servers
   - Set up monitoring for Harambe scrapers
   - Estimate: 1-2 days during Week 1

4. **Kickoff**: Begin Phase 1 (Platform Preparation) immediately

5. **Stakeholder Communication**: Notify affected agencies of migration timeline

---

## Questions for PM Review

### Key Decision: Option 1 or Option 2?

**Option 1: Enhanced Conventional Scrapers**
- Development: 3-5 weeks
- Operational Cost: 100-500/month
- Trade-off: Build from scratch, JavaScript limitations

**Option 2: Harambe (RECOMMENDED)**
- Development: 2.5-3.5 weeks (faster!)
- Progress: 2/12 already done (17% complete!)
- Operational Cost: 500-1500/month (higher)
- Trade-off: Reuse Reworkd code, better technology

### Follow-up Questions:

1. **Budget**: Approve 400-1000/month extra operational cost for Option 2?
2. **Timeline**: When does Reworkd shut down? Any hard deadlines?
3. **Priority**: Which agencies to migrate first?

---

## Appendix: 12 Production Reworkd Agencies

### Already Migrated (2 agencies)
1. ✅ Detroit Board of Police Commissioners (workflow) - **COMPLETED**
2. ✅ Detroit Police and Fire Retirement System (simple) - **COMPLETED**

### Remaining to Migrate (10 agencies)

**Simple Listing Scrapers** (6 agencies × 1 day = 6 days)
3. Greater Cleveland Regional Transit Authority
4. Cleveland City Planning Commission
5. Michigan Belle Isle Park Advisory Committee
6. Detroit Wayne County Port Authority
7. Cuyahoga County Arts & Culture
8. Cleveland Board of Building Standards and Building Appeals

**Orchestration Flow** (4 agencies × 2 days = 8 days)
9. Great Lakes Water Authority
10. Wayne County Commission
11. Cuyahoga County Emergency Services Advisory Board
12. Cuyahoga County Council

**Total Migration Time**: 6 + 8 = 14 days (2.8 weeks)

---

*Document Version: 1.0*
*Last Updated: 2025-11-04*
*Prepared for: Project Manager Review*
