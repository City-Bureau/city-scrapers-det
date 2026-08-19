# City Scrapers Detroit

[![CI build status](https://github.com/City-Bureau/city-scrapers-det/workflows/CI/badge.svg)](https://github.com/City-Bureau/city-scrapers-det/actions?query=workflow%3ACI)
[![Cron build status](https://github.com/City-Bureau/city-scrapers-det/workflows/Cron/badge.svg)](https://github.com/City-Bureau/city-scrapers-det/actions?query=workflow%3ACron)

Repo for the [City Scrapers](https://city-scrapers.org) project in Detroit.

See the [development documentation](https://city-scrapers.org/docs/development/) for info how to get started.

## Reviewing a spider

Every spider is checked against a shared contract in `tests/spider_contract.py`.
The checks are derived from failures this repo has actually shipped, so a green
run means something specific rather than "the tests the author thought of pass".

```sh
# what pytest enforces
pipenv run pytest tests/test_spider_contract.py

# what to read while reviewing a new or repaired spider
pipenv run python scripts/spider_contract_report.py det_city_council
pipenv run python scripts/spider_contract_report.py --failures   # all spiders
```

The contract discovers spiders through Scrapy's own spider loader, finds each
one's fixture at `tests/files/<spider_name>.<html|json|ics>`, replays it with the
clock frozen to the day the fixture was captured, and runs twenty checks in
four groups:

- **Output shape** (C01-C11) - the fixture parses at all; ids are namespaced and
  unique; title, start and source are present; an end time is either absent or
  after the start; classification and status are values the framework
  recognises; location and links have the shape downstream code expects; no
  markup survives into text fields.
- **Behaviour under degraded input** (C12-C15) — the same fixture is replayed
  empty, half-truncated, and with every digit stripped out. A spider that
  returns nothing, raises nothing and logs nothing under those conditions
  fails, because that is indistinguishable from a page that legitimately had no
  meetings. This is the failure mode that let a broken scraper look healthy for
  months.
- **Coverage honesty** (C20) - reports when the spider's own `parse` raised on
  its fixture, because the engine then grades an internal helper instead and the
  other checks are not covering the path Scrapy calls. Nine of the 21 spiders
  here are in that state.
- **Source policy** (C16-C19) — no `except: pass` without a log line, no
  spoofed browser user-agent, no hardcoded session cookie, and ids and statuses
  come from `_get_id`/`_get_status` rather than being hand-rolled.

`tests/spider_contract_baseline.json` lists violations that predate the
contract. Those are recorded as expected failures so the suite is green today,
and the file is a debt register, not an approval list: fixing a listed
violation makes `test_baseline_has_no_stale_entries` fail until the entry is
removed. **A new spider has no baseline entries, so every check applies to it from its
first commit.** C01 may never be baselined: a spider whose fixture parses to
nothing skips every check that needs meetings, so recording it would report a
silent pass for the whole contract.

`tests/test_spider_contract_checks.py` tests the checks themselves against
inputs they are supposed to reject, so a check cannot quietly stop firing.

**Read `HONEST_LIMITS` at the bottom of `tests/spider_contract.py` before
treating a green run as an all-clear.** Two independent reviews on 19 August
2026 found real gaps, and they are recorded there rather than quietly fixed.
The largest: for 17 of the 21 spiders here the checks grade an internal helper
rather than the entry point, and a silence check is satisfied by any exception,
including an unrelated one.

### The harambe scrapers

These are on the way out: reworkd is no longer in business and this framework
has not proved reliable, so new work goes to Scrapy. The checks below exist
because these scrapers are still in production until they are replaced, and both
bugs that motivated this whole exercise were on this side.

The scrapers in `harambe_scrapers/` cannot be replayed the same way — most of
them drive a real browser, and there is no per-scraper fixture convention to
discover. What they do share is `create_ocd_event` in `harambe_scrapers/utils.py`:
every harambe meeting, from every scraper, is built by that one function. So the
contract for them (`tests/harambe_contract.py`) checks that funnel instead.

```sh
pipenv run pytest tests/test_harambe_contract.py
```

Nine checks (H01-H09) cover the shape of what comes out: the id's scraper-name
prefix is one registered identifier rather than a joined list, the id's datetime
segment matches the event's own start time, the id has exactly the four segments
the format defines, start_time is parseable and carries an offset, end_time is
absent or after the start, status is a value the platform recognises, links carry
a url, and the host agency is named. Separately, and outside the H-series, one
test runs over every harambe module and fails on `except: pass`/`except: continue`
with no logging.

Coverage of real scrapers comes from `declared_scraper_names()`, which imports
each module and reads the name constants it actually stamps on a meeting. That
matters: before it existed, the checks only ever graded a good name written into
the test file, so H01 could reject the comma-joined string in principle while
nothing ever handed it one. A review caught that, and setting a real module's
`SCRAPER_NAME` to a comma-joined list is now a test failure.

The scraper-name checks exist because of a specific failure: Wayne County
meetings were stamped with all thirteen committee names joined by commas, the
importer looked that string up in `Agency.scraper_names`, matched nothing, and
skipped every meeting — for months, with every run reporting success.

What this does not reach is written out in `KNOWN_GAPS` at the bottom of
`tests/harambe_contract.py`. The largest gap is the parse layer: a harambe
selector that silently stops matching is caught by that scraper's own tests or
not at all.

### Adding a spider

1. `pipenv run scrapy genspider <name> <agency name> <url>`
2. Save a fixture: `pipenv run scrapy fetch <url> > tests/files/<name>.html`
3. Write the spider and its own `tests/test_<name>.py` with the assertions
   specific to that agency (meeting counts, particular titles, particular
   dates). The contract covers what is true of every spider; it does not
   replace per-spider tests.
4. `pipenv run python scripts/spider_contract_report.py <name>` and clear
   everything it reports.
