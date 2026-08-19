"""Framework-general contract checks that every spider should satisfy.

These checks run against each spider's saved fixture and its source, and are
written to catch classes of failure we have actually been burned by rather
than to restate the JSON schema (``scrapy validate`` already does that).

The failure that motivated most of this file: a spider can break in a way
that produces no error at all. Wayne County's scrapers returned zero meetings
for months while every run "succeeded", and a separate parsing bug dropped
individual meetings by raising an exception that was caught and ignored
upstream. Both were invisible to the test suite because the tests only ever
asserted on a fixture that still parsed cleanly.

Nothing here is specific to this repository. Spiders are discovered through
Scrapy, fixtures by naming convention, so the module can be copied into any
city-scrapers repo unchanged.

Not to be confused with Scrapy's own "spider contracts" (``scrapy check``),
which are assertions written into a callback's docstring and run against the
live site. These run offline against a saved fixture and apply to every spider
without anyone having to opt in.
"""

import inspect
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional

from city_scrapers_core.constants import CLASSIFICATIONS, STATUSES
from city_scrapers_core.items import Meeting
from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy.http import TextResponse
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings

FIXTURE_DIR = Path(__file__).parent / "files"
FIXTURE_EXTENSIONS = ("html", "json", "ics", "xml", "txt", "csv")

# Spoofed browser identities and replayed session cookies are what got the
# Wayne County scraper blocked by the county's bot protection.
SPOOFED_UA_RE = re.compile(
    r"(Mozilla/5\.0|AppleWebKit|Chrome/\d|Safari/\d|Edg/\d)", re.I
)
COOKIE_LITERAL_RE = re.compile(r"""["']cookie["']\s*:""", re.I)
# ``except ...: pass`` with nothing logged is how a per-item parsing error
# becomes a silently missing meeting.
SILENT_EXCEPT_RE = re.compile(r"except[^\n:]*:\s*\n\s+(pass|continue)\s*(\n|$)", re.M)


@dataclass
class CheckResult:
    check_id: str
    spider: str
    passed: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class SpiderContext:
    """Everything a check needs about one spider, computed once."""

    name: str
    spider: object
    source: str
    fixture: Optional[Path] = None
    parse_method: Optional[str] = None
    meetings: List[Meeting] = field(default_factory=list)
    requests_yielded: int = 0
    degraded: dict = field(default_factory=dict)
    response_builder: Optional[str] = None
    meetings_complete: bool = True
    captured_at: Optional[str] = None
    load_error: Optional[str] = None


CHECKS: List[tuple] = []


def check(check_id: str, summary: str, requires_meetings: bool = True):
    """Register a contract check.

    A check returns None when the spider satisfies it, or a string explaining
    the violation. ``requires_meetings`` marks checks that cannot say anything
    unless the fixture actually parsed into meetings; those are reported as
    skipped rather than passed, so an uncovered spider never looks clean.
    """

    def wrap(fn: Callable[[SpiderContext], Optional[str]]):
        CHECKS.append((check_id, summary, requires_meetings, fn))
        return fn

    return wrap


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def spider_loader() -> SpiderLoader:
    return SpiderLoader.from_settings(get_project_settings())


def discover_spider_names() -> List[str]:
    return sorted(spider_loader().list())


def _find_fixture(name: str) -> Optional[Path]:
    for ext in FIXTURE_EXTENSIONS:
        candidate = FIXTURE_DIR / f"{name}.{ext}"
        if candidate.exists():
            return candidate
    return None


def _flatten(result) -> tuple:
    """Split whatever a parse method returned into meetings and requests."""
    meetings, requests = [], 0
    if result is None:
        return meetings, requests
    if isinstance(result, (Meeting, dict)):
        result = [result]
    try:
        items = list(result)
    except TypeError:
        return meetings, requests
    for item in items:
        if isinstance(item, Meeting):
            meetings.append(item)
        elif item.__class__.__name__.endswith("Request"):
            requests += 1
    return meetings, requests


PARSER_NAME_RE = re.compile(r"(parse|meeting)", re.I)

# Helpers that mint a blank Meeting from the spider's class attributes. They
# return something for any input at all, so treating them as parse methods
# reports coverage without a single selector having been exercised.
NON_PARSER_NAME_RE = re.compile(r"(default|template|blank)", re.I)


def _parse_methods(spider) -> List[str]:
    """Methods that might turn a response into meetings, most likely first.

    Spiders in this framework split parsing across helpers with a range of
    names - ``parse``, ``parse_legistar``, ``_parse_item``, ``_next_meetings``
    - so anything that takes a single argument and is named like a parser is
    worth trying. Ones that raise on a response are skipped harmlessly.
    """
    names = []
    if hasattr(spider, "parse"):
        names.append("parse")
    for attr in sorted(dir(spider)):
        if attr.startswith("__") or attr == "parse":
            continue
        if not PARSER_NAME_RE.search(attr):
            continue
        if NON_PARSER_NAME_RE.search(attr):
            continue
        if callable(getattr(spider, attr, None)):
            fn = getattr(spider, attr)
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                continue
            required = [
                p
                for p in params.values()
                if p.default is p.empty and p.kind is p.POSITIONAL_OR_KEYWORD
            ]
            if len(required) == 1:
                names.append(attr)
    return names


def _run_parse(spider, method_name: str, response):
    """Call one parse method, capturing output, exceptions and error logs."""
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    logging.getLogger().addHandler(handler)
    raised = None
    meetings, requests = [], 0
    try:
        meetings, requests = _flatten(getattr(spider, method_name)(response))
    except Exception as exc:  # noqa: BLE001 - the point is to observe it
        raised = f"{type(exc).__name__}: {exc}"
    finally:
        logging.getLogger().removeHandler(handler)
    return {
        "meetings": meetings,
        "requests": requests,
        "raised": raised,
        "logged": [r.getMessage() for r in records],
    }


def _meetings_are_plausible(meetings) -> bool:
    """Whether this looks like a real parse rather than an empty shell.

    A Meeting with no start never came from reading the page - it came from a
    helper filling in class attributes - so it is not evidence the spider can
    parse anything.
    """
    return bool(meetings) and all(m.get("start") for m in meetings)


def _meetings_are_complete(meetings) -> bool:
    """Whether these look like finished meetings rather than half-built ones."""
    return all(m.get("id") and m.get("status") for m in meetings)


def _file_response(fixture: Path, url: str, body: bytes):
    response = file_response(str(fixture), url=url)
    if body != fixture.read_bytes():
        response = response.replace(body=body)
    return response


def _text_response(fixture: Path, url: str, body: bytes):
    return TextResponse(url=url, body=body, encoding="utf-8")


def _json_payload(fixture: Path, url: str, body: bytes):
    """Legistar spiders are handed decoded events, not a Response."""
    if fixture.suffix != ".json":
        raise ValueError("not a json fixture")
    return json.loads(body)


def _fixture_captured_at(fixture: Path) -> str:
    """When this fixture was saved, as far as git knows.

    Falls back to the file's own timestamp, which is what a fresh clone has.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(fixture)],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        stamp = out.stdout.strip()
        if stamp:
            return stamp
    except (OSError, subprocess.SubprocessError):
        pass
    return datetime.fromtimestamp(fixture.stat().st_mtime).strftime("%Y-%m-%d")


def _strip_digits(value):
    if isinstance(value, str):
        return re.sub(r"\d", "", value)
    if isinstance(value, list):
        return [_strip_digits(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_digits(v) for k, v in value.items()}
    return value


def _halve(payload):
    if isinstance(payload, list):
        return payload[: len(payload) // 2]
    return {}


# The same three ways an upstream page goes wrong, expressed for each input
# shape: a raw body for spiders that read HTML, decoded events for the ones
# handed JSON.
DEGRADATIONS = {
    "empty": {
        "bytes": lambda body: b"",
        "json": lambda payload: [],
    },
    "truncated": {
        "bytes": lambda body: body[: len(body) // 2],
        "json": _halve,
    },
    "undated": {
        "bytes": lambda body: re.sub(rb"\d", b"", body),
        "json": _strip_digits,
    },
}


def build_context(name: str, loader: Optional[SpiderLoader] = None) -> SpiderContext:
    loader = loader or spider_loader()
    spider_cls = loader.load(name)
    spider = spider_cls()
    if getattr(spider, "settings", None) is None:
        # Scrapy attaches settings when it opens a spider, so a direct call has
        # to supply them. Archive mode is on because several spiders drop
        # meetings older than a rolling cutoff without it, and a fixture is
        # always older than the day it is replayed - the contract wants to see
        # everything the selectors can extract, not what a scheduled run keeps.
        spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": True})
    source = inspect.getsource(inspect.getmodule(spider_cls))
    for base in spider_cls.__mro__[1:]:
        module = inspect.getmodule(base)
        if module and "city_scrapers" in getattr(module, "__name__", ""):
            try:
                source += "\n" + inspect.getsource(module)
            except OSError:
                pass
    ctx = SpiderContext(name=name, spider=spider, source=source)

    ctx.fixture = _find_fixture(name)
    if ctx.fixture is None:
        ctx.load_error = f"no fixture at tests/files/{name}.<ext>"
        return ctx

    url = (spider.start_urls or ["https://example.org"])[0]
    body = ctx.fixture.read_bytes()
    ctx.captured_at = _fixture_captured_at(ctx.fixture)

    # Spiders that filter out meetings older than a cutoff yield nothing when
    # run against a fixture captured years ago, so the clock is frozen to when
    # the fixture was captured rather than to today.
    with freeze_time(ctx.captured_at):
        partial = None
        for builder in (_file_response, _text_response, _json_payload):
            for method in _parse_methods(spider):
                run = _run_parse(spider, method, builder(ctx.fixture, url, body))
                ctx.requests_yielded = max(ctx.requests_yielded, run["requests"])
                if not _meetings_are_plausible(run["meetings"]):
                    continue
                candidate = (method, builder.__name__, run["meetings"])
                if _meetings_are_complete(run["meetings"]):
                    ctx.parse_method, ctx.response_builder, ctx.meetings = candidate
                    break
                # An intermediate helper that builds meetings before the
                # caller stamps id and status onto them. Fallback only.
                partial = partial or candidate
            if ctx.meetings:
                break
        if not ctx.meetings and partial:
            ctx.parse_method, ctx.response_builder, ctx.meetings = partial
            ctx.meetings_complete = False

        if ctx.parse_method:
            builders = {
                b.__name__: b for b in (_file_response, _text_response, _json_payload)
            }
            build = builders[ctx.response_builder]
            reads_json = ctx.response_builder == "_json_payload"
            for label, mutators in DEGRADATIONS.items():
                if reads_json:
                    degraded = mutators["json"](json.loads(body))
                else:
                    degraded = build(ctx.fixture, url, mutators["bytes"](body))
                ctx.degraded[label] = _run_parse(spider, ctx.parse_method, degraded)

    return ctx


# --------------------------------------------------------------------------
# Output shape — what a meeting must look like to be usable downstream
# --------------------------------------------------------------------------


@check("C01", "The fixture parses into at least one meeting", requires_meetings=False)
def produces_meetings(ctx):
    if ctx.load_error:
        return ctx.load_error
    if ctx.meetings:
        return None
    if ctx.requests_yielded:
        return (
            "entry parse yielded only requests; add a fixture for the page the "
            "callback parses so its output is covered"
        )
    return "no parse method produced a meeting from the fixture"


@check("C02", "Meeting ids are prefixed with the spider's own name")
def id_prefix_matches_spider(ctx):
    bad = [
        m.get("id")
        for m in ctx.meetings
        if not str(m.get("id") or "").startswith(ctx.name + "/")
    ]
    if bad:
        return f"{len(bad)} id(s) not prefixed with '{ctx.name}/', e.g. {bad[0]!r}"
    return None


@check("C03", "Meeting ids are unique within one run")
def ids_unique(ctx):
    seen, dupes = set(), set()
    for meeting in ctx.meetings:
        key = meeting.get("id")
        if key in seen:
            dupes.add(key)
        seen.add(key)
    if dupes:
        return f"{len(dupes)} duplicate id(s), e.g. {sorted(dupes)[0]!r}"
    return None


@check("C04", "Title, start and source are present on every meeting")
def required_fields_present(ctx):
    problems = []
    for meeting in ctx.meetings:
        if not str(meeting.get("title") or "").strip():
            problems.append("empty title")
        if not isinstance(meeting.get("start"), datetime):
            problems.append(f"start is {type(meeting.get('start')).__name__}")
        if not str(meeting.get("source") or "").strip():
            problems.append("empty source")
    if problems:
        return f"{len(problems)} problem(s): {sorted(set(problems))}"
    return None


@check("C05", "End times are absent or after the start")
def end_not_before_start(ctx):
    bad = 0
    for meeting in ctx.meetings:
        end, start = meeting.get("end"), meeting.get("start")
        if isinstance(end, datetime) and isinstance(start, datetime):
            if end < start:
                bad += 1
    if bad:
        return f"{bad} meeting(s) end before they start"
    return None


@check("C06", "Datetimes are consistently naive or consistently aware")
def datetime_awareness_consistent(ctx):
    aware = set()
    for meeting in ctx.meetings:
        for key in ("start", "end"):
            value = meeting.get(key)
            if isinstance(value, datetime):
                aware.add(value.tzinfo is not None)
    if len(aware) > 1:
        return "mix of naive and timezone-aware datetimes in one run"
    return None


@check("C07", "Classification is one the framework recognises")
def classification_recognised(ctx):
    bad = {
        m.get("classification")
        for m in ctx.meetings
        if m.get("classification") not in CLASSIFICATIONS
    }
    if bad:
        return f"unrecognised classification(s): {sorted(map(str, bad))}"
    return None


@check("C08", "Status is one the framework recognises")
def status_recognised(ctx):
    bad = {m.get("status") for m in ctx.meetings if m.get("status") not in STATUSES}
    if bad:
        return f"unrecognised status(es): {sorted(map(str, bad))}"
    return None


@check("C09", "Location is a mapping with name and address")
def location_shape(ctx):
    for meeting in ctx.meetings:
        location = meeting.get("location")
        if not isinstance(location, dict):
            return f"location is {type(location).__name__}, expected dict"
        missing = {"name", "address"} - set(location)
        if missing:
            return f"location missing key(s): {sorted(missing)}"
        # Both keys present but both blank is the shape a selector returns
        # after the page it targeted was restructured.
        if not any(str(location.get(k) or "").strip() for k in ("name", "address")):
            return "location has neither a name nor an address"
    return None


@check("C10", "Links are a list of mappings with href and title")
def links_shape(ctx):
    for meeting in ctx.meetings:
        links = meeting.get("links")
        if links in (None, []):
            continue
        if not isinstance(links, list):
            return f"links is {type(links).__name__}, expected list"
        for link in links:
            if not isinstance(link, dict) or "href" not in link:
                return f"link entry missing href: {link!r}"
            if not str(link.get("href") or "").strip():
                return f"link entry has an empty href: {link!r}"
    return None


@check("C11", "Text fields carry no leftover markup")
def no_markup_in_text(ctx):
    for meeting in ctx.meetings:
        for key in ("title", "description"):
            value = str(meeting.get(key) or "")
            if re.search(r"<\s*[a-zA-Z/][^>]*>", value):
                return f"{key} contains markup: {value[:60]!r}"
    return None


# --------------------------------------------------------------------------
# Failure signalling — the lesson from the Wayne County outage
# --------------------------------------------------------------------------


def _silence_violation(ctx, label, what_broke):
    run = ctx.degraded.get(label)
    if run is None:
        return None
    if run["meetings"]:
        return None
    if run["raised"] or run["logged"]:
        return None
    return (
        f"{what_broke} produced no meetings, raised nothing and logged nothing "
        "- a real break of this kind would look like a successful run"
    )


@check("C12", "An empty page is reported, not passed over in silence")
def empty_input_is_not_silent(ctx):
    return _silence_violation(ctx, "empty", "an empty response body")


@check("C13", "A truncated page is reported, not passed over in silence")
def truncated_input_is_not_silent(ctx):
    return _silence_violation(ctx, "truncated", "a half-truncated response body")


@check("C14", "Unparseable dates are reported, not passed over in silence")
def undated_input_is_not_silent(ctx):
    return _silence_violation(ctx, "undated", "a response with every digit removed")


@check("C15", "Degraded input never yields a malformed meeting")
def degraded_output_still_valid(ctx):
    for label, run in ctx.degraded.items():
        for meeting in run["meetings"]:
            if not isinstance(meeting.get("start"), datetime):
                return f"{label} input produced a meeting with no usable start"
            if not str(meeting.get("title") or "").strip():
                return f"{label} input produced a meeting with an empty title"
    return None


# --------------------------------------------------------------------------
# Source policy
# --------------------------------------------------------------------------


@check("C16", "Exceptions are not swallowed without a trace", requires_meetings=False)
def no_silent_exception_swallowing(ctx):
    hits = SILENT_EXCEPT_RE.findall(ctx.source)
    if hits:
        return (
            f"{len(hits)} 'except: pass/continue' block(s) with no logging - this "
            "is how one unparseable page becomes a silently missing meeting"
        )
    return None


@check("C17", "The spider does not impersonate a browser", requires_meetings=False)
def no_spoofed_browser_identity(ctx):
    match = SPOOFED_UA_RE.search(ctx.source)
    if match:
        return (
            f"source contains a browser user-agent fragment ({match.group(0)!r}); "
            "identify the project honestly instead"
        )
    return None


@check("C18", "The spider carries no hardcoded session cookie", requires_meetings=False)
def no_hardcoded_cookie(ctx):
    if COOKIE_LITERAL_RE.search(ctx.source):
        return "source sets a literal cookie header; sessions go stale silently"
    return None


@check("C19", "Ids and statuses come from the framework helpers")
def uses_framework_helpers(ctx):
    missing = []
    if "_get_id(" not in ctx.source:
        missing.append("_get_id()")
    if "_get_status(" not in ctx.source:
        missing.append("_get_status()")
    if missing:
        return (
            f"does not call {', '.join(missing)}; hand-built ids and statuses "
            "drift from what the platform matches on"
        )
    return None


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


# Checks that only mean something once id and status have been stamped on.
FINISHED_ONLY = {"C02", "C03", "C08"}


def run_checks(ctx: SpiderContext) -> List[CheckResult]:
    results = []
    for check_id, _summary, requires_meetings, fn in CHECKS:
        if check_id in FINISHED_ONLY and ctx.meetings and not ctx.meetings_complete:
            results.append(
                CheckResult(
                    check_id,
                    ctx.name,
                    True,
                    "only an intermediate parse helper was reachable",
                    skipped=True,
                )
            )
            continue
        if requires_meetings and not ctx.meetings:
            results.append(
                CheckResult(
                    check_id, ctx.name, True, "no meetings parsed", skipped=True
                )
            )
            continue
        detail = fn(ctx)
        results.append(CheckResult(check_id, ctx.name, detail is None, detail or ""))
    return results


def summary_line(check_id: str) -> str:
    for cid, summary, _requires, _fn in CHECKS:
        if cid == check_id:
            return summary
    return check_id
