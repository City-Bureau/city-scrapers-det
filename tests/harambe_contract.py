"""Contract checks for the harambe scrapers.

The Scrapy spiders are checked by replaying a saved fixture through the parse
method (``tests/spider_contract.py``). The harambe scrapers cannot be checked
that way: most of them drive a real browser, and there is no per-scraper fixture
convention to discover. What they do share is ``create_ocd_event`` in
``harambe_scrapers/utils.py`` - every harambe meeting, from every scraper, is
built by that one function. So that is where the checks go.

Both harambe bugs this repo has actually shipped are visible at that seam:

* Wayne County meetings were stamped with a comma-joined 13-name string as their
  scraper name, so the Documenters importer - which splits ``cityscrapers/id``
  on ``/`` and looks the prefix up in ``Agency.scraper_names`` - matched nothing
  and skipped every meeting. ``H01`` rejects that shape.
* A detail page publishing a lone start time with no ``" - <end>"`` range fell
  outside a gate (``if meeting_date and " - " in time_text``), so the start was
  never set, nothing was raised, and the meeting was dropped downstream. None of
  these checks catch that: with no start there is no event to inspect, so the
  parse layer is where it has to be caught, and the regression test added with
  its fix is what covers it. ``H05`` covers only the adjacent case of a range
  parsed the wrong way round.

These checks are properties of the funnel rather than of any one scraper. Their
coverage of real scrapers comes from ``declared_scraper_names``, which imports
each module and reads the names it actually stamps on a meeting; without that
they would only ever grade values written in the test file. See ``KNOWN_GAPS``
at the bottom for what this does not reach.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

HARAMBE_DIR = Path(__file__).resolve().parent.parent / "harambe_scrapers"

# The platform's own vocabulary. A status outside this set silently fails to
# match on import.
RECOGNISED_STATUSES = {"cancelled", "canceled", "tentative", "confirmed", "passed"}

# A scraper name is one registered identifier - no commas, no whitespace, no
# slashes. The Wayne bug was a comma-joined list of thirteen of them.
SCRAPER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


@dataclass
class EventCheckResult:
    check_id: str
    passed: bool
    detail: str = ""


CHECKS: List[tuple] = []


def check(check_id: str, summary: str):
    def register(fn):
        CHECKS.append((check_id, summary, fn))
        return fn

    return register


def summary_line(check_id: str) -> str:
    for cid, summary, _ in CHECKS:
        if cid == check_id:
            return summary
    return check_id


def scraper_segment(event: dict) -> str:
    """The part of cityscrapers/id the Documenters importer matches on."""
    scraper_id = event.get("extras", {}).get("cityscrapers/id", "")
    return scraper_id.split("/")[0]


def _parse_iso(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Checks on one event
# --------------------------------------------------------------------------


@check("H01", "The id's scraper name is one registered name, not a list")
def scraper_name_is_singular(event):
    segment = scraper_segment(event)
    if not segment:
        return "cityscrapers/id has no scraper-name prefix"
    if not SCRAPER_NAME_RE.match(segment):
        return (
            f"scraper name {segment!r} is not a single registered identifier; "
            "the importer looks this exact string up in Agency.scraper_names, "
            "so anything joined, spaced or capitalised matches nothing"
        )
    return None


@check("H02", "The id encodes the event's own start time")
def id_encodes_start(event):
    """Tautological for events built by ``create_ocd_event``, deliberately kept.

    ``generate_id`` derives the datetime segment from the same ``start_time``
    field this compares against, so an event that went through the funnel cannot
    fail. It exists to catch a scraper that assembles an id itself and bypasses
    the funnel, which is exactly what the Wayne code did with the scraper name.
    """
    scraper_id = event.get("extras", {}).get("cityscrapers/id", "")
    parts = scraper_id.split("/")
    if len(parts) < 2:
        return f"cityscrapers/id {scraper_id!r} has no datetime segment"
    start = _parse_iso(event.get("start_time"))
    if start is None:
        return f"start_time {event.get('start_time')!r} is not a parseable datetime"
    if parts[1] != start.strftime("%Y%m%d%H%M"):
        return (
            f"id datetime segment {parts[1]!r} does not match start_time "
            f"{event.get('start_time')!r}; ids drift out of sync with reality"
        )
    return None


@check("H09", "The id has exactly the four segments the format defines")
def id_segment_count(event):
    scraper_id = event.get("extras", {}).get("cityscrapers/id", "")
    parts = scraper_id.split("/")
    if len(parts) != 4:
        return (
            f"cityscrapers/id {scraper_id!r} has {len(parts)} '/'-separated "
            "segments, expected 4 (name/datetime/x/slug). A scraper name or "
            "slug containing a slash truncates the prefix the importer reads "
            "rather than failing outright"
        )
    return None


@check("H03", "Title and source are present")
def required_fields_present(event):
    problems = []
    if not str(event.get("name") or "").strip():
        problems.append("empty name")
    sources = event.get("sources") or []
    if not sources or not str(sources[0].get("url") or "").strip():
        problems.append("no source url")
    if problems:
        return ", ".join(problems)
    return None


@check("H04", "start_time is a parseable, timezone-aware datetime")
def start_is_usable(event):
    start = _parse_iso(event.get("start_time"))
    if start is None:
        return f"start_time {event.get('start_time')!r} is not a parseable datetime"
    if start.tzinfo is None:
        return (
            "start_time carries no UTC offset; the same wall time means "
            "different instants to the importer and the scraper"
        )
    return None


@check("H05", "end_time is absent or after the start")
def end_not_before_start(event):
    end_raw = event.get("end_time")
    if end_raw in (None, ""):
        return None
    end = _parse_iso(end_raw)
    if end is None:
        return f"end_time {end_raw!r} is set but is not a parseable datetime"
    start = _parse_iso(event.get("start_time"))
    if start is None:
        return None  # H04 reports this
    if end.tzinfo is None or start.tzinfo is None:
        return "cannot compare start and end: one is timezone-naive"
    if end < start:
        return f"end_time {end_raw!r} is before start_time {event['start_time']!r}"
    return None


@check("H06", "status agrees with the meeting's own start time")
def status_agrees_with_start(event):
    """Membership alone was a tautology, since the status is computed.

    ``determine_status`` can only ever return one of the recognised values, so
    checking membership proved nothing. What can actually go wrong is the status
    disagreeing with the time it was derived from: a meeting stamped "passed"
    that has not happened, or "tentative" for one that has.
    """
    status = event.get("status")
    if status not in RECOGNISED_STATUSES:
        return (
            f"status {status!r} is not one of {sorted(RECOGNISED_STATUSES)}; "
            "an unrecognised status is dropped rather than corrected"
        )
    if status in ("cancelled", "canceled"):
        return None
    start = _parse_iso(event.get("start_time"))
    if start is None:
        return None  # H04 reports this
    now = datetime.now(start.tzinfo)
    if start > now and status == "passed":
        return (
            f"start_time {event['start_time']!r} is in the future "
            "but status is 'passed'"
        )
    if start < now and status == "tentative":
        return (
            f"start_time {event['start_time']!r} is in the past "
            "but status is 'tentative'"
        )
    return None


@check("H07", "Links carry a usable url")
def links_shape(event):
    links = event.get("links")
    if links in (None, []):
        return None
    if not isinstance(links, list):
        return f"links is {type(links).__name__}, expected list"
    for link in links:
        if not isinstance(link, dict):
            return f"link entry is {type(link).__name__}, expected dict"
        url = link.get("url") or link.get("href")
        if not str(url or "").strip():
            return f"link entry has no url: {link!r}"
    return None


@check("H08", "The host agency is named")
def agency_named(event):
    hosts = [
        p
        for p in event.get("participants") or []
        if p.get("note") == "host" and str(p.get("name") or "").strip()
    ]
    if not hosts:
        return "no host participant with a name; the meeting has no agency"
    return None


# Registration order follows the source, which is not id order once a check is
# added between two existing ones. Report in id order instead.
CHECKS.sort(key=lambda entry: entry[0])


def run_event_checks(event: dict) -> List[EventCheckResult]:
    results = []
    for check_id, _summary, fn in CHECKS:
        detail = fn(event)
        results.append(
            EventCheckResult(
                check_id=check_id, passed=detail is None, detail=detail or ""
            )
        )
    return results


# --------------------------------------------------------------------------
# Source policy, over every harambe scraper module
# --------------------------------------------------------------------------

SILENT_EXCEPT_RE = re.compile(
    r"except[^:\n]*:\s*\n(?:[ \t]*#[^\n]*\n)*[ \t]*(?:pass|continue)\b"
)
SPOOFED_UA_RE = re.compile(r"Mozilla/5\.0|AppleWebKit/|Chrome/\d|Safari/\d")
COOKIE_LITERAL_RE = re.compile(r"""["']Cookie["']\s*:\s*["'][^"']+["']""")


# Every name a harambe scraper can stamp onto a meeting, discovered from the
# scrapers themselves rather than listed here. The review that prompted this
# found the checks were only ever run against a hardcoded good name, so H01
# could not have caught the bug it was written for.
SCRAPER_NAME_CONSTANTS = ("SCRAPER_NAME", "OUTPUT_NAME", "FALLBACK_SCRAPER_NAME")


def declared_scraper_names() -> dict:
    """Map each harambe scraper module to the scraper names it can emit.

    Imports the modules and reads their real constants, so a name that would
    break the Documenters importer is caught wherever it is introduced.
    """
    import importlib

    found = {}
    for module_path in harambe_modules():
        relative = module_path.relative_to(HARAMBE_DIR)
        dotted = "harambe_scrapers." + ".".join(relative.with_suffix("").parts)
        try:
            module = importlib.import_module(dotted)
        except Exception:  # noqa: BLE001 - a module needing a browser to import
            # is not a naming defect; it is simply out of reach here.
            continue
        for attr in SCRAPER_NAME_CONSTANTS:
            value = getattr(module, attr, None)
            if isinstance(value, str) and value:
                found[f"{relative.as_posix()}:{attr}"] = value
        registry = getattr(module, "REGISTERED_CALENDAR_SCRAPER_NAMES", None)
        if isinstance(registry, dict):
            for label, value in registry.items():
                if isinstance(value, str) and value:
                    found[f"{relative.as_posix()}:{label}"] = value
    return found


def harambe_modules() -> List[Path]:
    """Every harambe scraper source file, scrapers and extractors alike."""
    return sorted(
        p
        for p in HARAMBE_DIR.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"
    )


def silent_except_blocks(source: str) -> List[str]:
    return SILENT_EXCEPT_RE.findall(source)


def spoofed_user_agents(source: str) -> List[str]:
    return SPOOFED_UA_RE.findall(source)


def hardcoded_cookies(source: str) -> List[str]:
    return COOKIE_LITERAL_RE.findall(source)


# Silent except blocks that predate this contract, with the reason each is
# listed. Same intent as tests/spider_contract_baseline.json: the check is
# enforced on every other module, and these entries are debt, not approval.
# Removing a block from a module here means removing its entry too - the test
# fails on a stale one.
KNOWN_SILENT_EXCEPT = {
    "det_police_department.py": (
        "Four blocks: a listing row whose date will not parse is skipped, and "
        "three field extractions fall through to a default. Each drops a "
        "meeting or a field with no record of what was lost."
    ),
    "mi_belle_isle.py": (
        "Two agenda/minutes loops skip a row whose link text will not parse as "
        "a date, so a document goes missing from an otherwise complete meeting."
    ),
}


# A hardcoded browser user-agent, recorded the same way as the silent excepts.
# Listing it is not endorsement: it is a deliberate anti-detection measure that
# predates this contract, and changing it is a scraper-behaviour decision rather
# than a testing one.
KNOWN_SPOOFED_UA = {
    "det_police_department.py": (
        "Sets a Chrome user-agent on the Playwright context under an "
        "'anti-detection' comment. Whether to keep impersonating a browser is a "
        "policy call for whoever owns the relationship with that site, so the "
        "check records it rather than forcing a change."
    ),
}


def baseline_key(module: Path) -> str:
    """How a module is named in KNOWN_SILENT_EXCEPT."""
    return module.relative_to(HARAMBE_DIR).as_posix()


KNOWN_GAPS = """
What these checks do not reach:

* The parse layer. Most harambe scrapers extract through Playwright against a
  live page, and there is no per-scraper fixture convention to replay offline.
  A selector that silently stops matching is caught by the per-scraper tests or
  not at all - unlike the Scrapy side, where tests/spider_contract.py replays
  every fixture and fails on a silent empty result.
* Whether a scraper name is actually registered on an Agency row. H01 checks the
  shape only. A well-formed name for an agency that does not exist in the
  Documenters database still imports nothing, which is what the derived wayne_*
  names currently do by design.
* Feed-level behaviour: how many meetings a run should produce, and whether a
  run producing zero is a real outage. That is the merge script's and the
  monitoring's job, not a unit test's.
"""
