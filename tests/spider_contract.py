"""Framework-general contract checks that every spider should satisfy.

These checks run against each spider's saved fixture and its source, and are
written to catch classes of failure we have actually been burned by rather
than to restate the JSON schema (``scrapy validate`` already does that).

The failure that motivated most of this file: a spider can break in a way
that produces no error at all. Wayne County's scrapers returned zero meetings
for months while every run "succeeded". A separate bug dropped individual
meetings because a gate (``if meeting_date and " - " in time_text``) simply did
not run on pages publishing a lone start time, leaving the start unset with
nothing raised and nothing logged. Both were invisible to the test suite
because the tests only ever asserted on a fixture that still parsed cleanly.

Read HONEST_LIMITS at the bottom before trusting a green run. Two independent
reviews of this file found real gaps, and they are recorded there rather than
quietly fixed.

Nothing here is specific to this repository. Spiders are discovered through
Scrapy, fixtures by naming convention, so the module can be copied into any
city-scrapers repo unchanged.

Not to be confused with Scrapy's own "spider contracts" (``scrapy check``),
which are assertions written into a callback's docstring and run against the
live site. These run offline against a saved fixture and apply to every spider
without anyone having to opt in.
"""

import ast
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

REPO_ROOT = Path(__file__).resolve().parent.parent
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
class Skip:
    """A check that cannot say anything; run_checks reports it skipped, not passed."""

    detail: str = ""


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
    builder_errors: dict = field(default_factory=dict)
    entry_parse: Optional[dict] = None
    source_units: List[str] = field(default_factory=list)
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


def called_helper_names(sources) -> set:
    """Names actually called in these sources, via the syntax tree.

    Searching raw text counted a mention in a comment or a string literal as
    evidence of a call, so a spider could hand-build its ids and still satisfy
    C19 by naming the helper in a docstring. Falls back to a text search only
    when a source unit will not parse, which should not happen for code that
    imported successfully.
    """
    called = set()
    for source in sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            called.update(
                name for name in ("_get_id", "_get_status") if f"{name}(" in source
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
    return called


def _is_project_module(module) -> bool:
    """Whether this module's source belongs to this repository.

    Matching on the name "city_scrapers" also matched the installed
    city_scrapers_core, which meant the source-policy checks graded a
    third-party library: C19 always found the _get_id and _get_status the base
    class *defines*, and C16 reported an except/pass inside site-packages as
    repo debt. Only mixins and spiders in this tree should count.
    """
    path = getattr(module, "__file__", None)
    if not path:
        return False
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return False
    # The virtualenv usually sits inside the repo, so "under the repo root" on
    # its own still lets installed packages through.
    return not any(
        part == "site-packages" or part.startswith(".") for part in relative.parts
    )


def _builders_for(fixture: Path):
    """The response shapes worth trying for this fixture's type.

    Legistar spiders are handed decoded events, everything else a Response, and
    offering a builder that cannot apply is how the engine used to crash.
    """
    if fixture.suffix == ".json":
        return (_json_payload, _file_response, _text_response)
    return (_file_response, _text_response)


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
    units = [inspect.getsource(inspect.getmodule(spider_cls))]
    for base in spider_cls.__mro__[1:]:
        module = inspect.getmodule(base)
        if _is_project_module(module):
            try:
                units.append(inspect.getsource(module))
            except OSError:
                pass
    source = "\n".join(units)
    ctx = SpiderContext(name=name, spider=spider, source=source)
    ctx.source_units = units

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
        # A .json fixture is decoded events, not the Response parse() receives,
        # so there is nothing honest to probe with; C20 reports the gap.
        if hasattr(spider, "parse") and ctx.fixture.suffix != ".json":
            try:
                ctx.entry_parse = _run_parse(
                    spider, "parse", _file_response(ctx.fixture, url, body)
                )
            except Exception as exc:  # noqa: BLE001
                ctx.builder_errors["_file_response"] = f"{type(exc).__name__}: {exc}"

        for builder in _builders_for(ctx.fixture):
            for method in _parse_methods(spider):
                try:
                    response = builder(ctx.fixture, url, body)
                except Exception as exc:  # noqa: BLE001 - a builder that cannot
                    # apply to this fixture is not a spider defect. Record it and
                    # move on; letting it escape would take the session fixture
                    # down and hide the C01 failure this is meant to report.
                    ctx.builder_errors[builder.__name__] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    break
                run = _run_parse(spider, method, response)
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


@check("C05", "End times are absent or strictly after the start")
def end_not_before_start(ctx):
    bad = 0
    for meeting in ctx.meetings:
        end, start = meeting.get("end"), meeting.get("start")
        if isinstance(end, datetime) and isinstance(start, datetime):
            # An end equal to the start is a zero-length meeting, which in
            # practice means a parser read the same value twice. No meeting in
            # this repo legitimately does it.
            if end <= start:
                bad += 1
    if bad:
        return f"{bad} meeting(s) do not end after they start"
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


@check("C10", "Links are a list of mappings with a usable href")
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
    """Whatever a damaged page yields still has to satisfy the output checks.

    This used to assert two rules of its own, start and title, which left a
    degraded parse free to emit an unrecognised status or a malformed location.
    It now runs the real C02-C11 functions over the degraded meetings, so the
    two sets cannot drift apart.
    """
    for label, run in ctx.degraded.items():
        if not run["meetings"]:
            continue
        probe = SpiderContext(
            name=ctx.name,
            spider=ctx.spider,
            source=ctx.source,
            meetings=run["meetings"],
            meetings_complete=_meetings_are_complete(run["meetings"]),
        )
        for check_id, _summary, _needs, fn in CHECKS:
            if check_id not in OUTPUT_CHECKS:
                continue
            if check_id in FINISHED_ONLY and not probe.meetings_complete:
                continue
            detail = fn(probe)
            if detail:
                return (
                    f"{label} input produced a meeting that fails {check_id}: {detail}"
                )
    return None


# --------------------------------------------------------------------------
# Source policy
# --------------------------------------------------------------------------


@check(
    "C20",
    "The spider's own entry point runs without raising on its fixture",
    requires_meetings=False,
)
def entry_parse_does_not_raise(ctx):
    """The engine falls back to internal helpers, which can hide a broken entry.

    When ``parse`` raises on the committed fixture, the engine moves on to the
    next parser-named method and the contract ends up grading a helper rather
    than the code Scrapy actually calls. That substitution is useful for
    coverage and dangerous for confidence, so the substitution itself is
    reported.
    """
    if ctx.fixture is not None and ctx.fixture.suffix == ".json":
        return Skip(
            "the committed fixture is decoded events, not the page parse() "
            "receives, so the entry point cannot be probed from it"
        )
    if ctx.entry_parse is None:
        return None
    raised = ctx.entry_parse.get("raised")
    if raised:
        return (
            f"parse() raised {raised} on {ctx.fixture.name}; the checks below "
            f"graded {ctx.parse_method!r} instead, so they do not cover the "
            "path Scrapy calls"
        )
    return None


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
    called = called_helper_names(ctx.source_units or [ctx.source])
    missing = [f"{name}()" for name in ("_get_id", "_get_status") if name not in called]
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

# The output-shape group. C15 replays these over degraded output, so a damaged
# page cannot yield a meeting that would fail on a good one.
OUTPUT_CHECKS = {"C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11"}


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
        if isinstance(detail, Skip):
            results.append(
                CheckResult(check_id, ctx.name, True, detail.detail, skipped=True)
            )
            continue
        results.append(CheckResult(check_id, ctx.name, detail is None, detail or ""))
    return results


def summary_line(check_id: str) -> str:
    for cid, summary, _requires, _fn in CHECKS:
        if cid == check_id:
            return summary
    return check_id


HONEST_LIMITS = """
Known gaps in this file, from two independent reviews on 19 August 2026. These
are recorded rather than fixed because each needs a design decision, and a
reader deserves to know what a green run does not mean.

1. The checks often grade an internal helper, not the entry point. When
   ``parse`` yields nothing usable from the fixture, the engine tries other
   parser-named methods and grades the first that works. In this repo that
   means 17 of 21 spiders are graded on a helper. C20 now reports when the
   entry point raised, but not when it merely returned nothing. Demonstrated
   consequence: breaking all three listing selectors in DetCityMixin produced
   zero new failures across the seven spiders that use it.

2. A silence check is satisfied by any exception, including an unrelated one.
   ``_silence_violation`` accepts meetings, an exception, or a log line as
   evidence the spider noticed. In this repo every current C12-C14 pass is
   earned by an incidental crash (a JSONDecodeError, an AttributeError on
   None) rather than by a spider reporting anything. In a scheduled run both a
   callback exception and a lone warning still produce a run that exits zero
   with zero items, which is the outage being tested for.

3. Archive mode is forced on, so the checks do not model a scheduled run.
   Several spiders drop meetings older than a rolling cutoff when the flag is
   off, silently. With the flag at its production value, 9 of 21 spiders
   produce nothing from their own fixtures. Running both ways would be the fix.

4. The 'truncated' degradation is not a break for list-shaped input. Halving a
   decoded JSON list yields valid events, and halving HTML often yields half
   the rows, so C13 frequently passes by succeeding. A truncated HTTP body of a
   JSON endpoint would be invalid JSON, which is not what this simulates.

5. The 'undated' degradation corrupts markup, not just dates. Stripping every
   digit also renames h1/h2 tags and mangles class names and HTML entities, so
   C14 exercises broken markup more than unparseable dates.

6. SILENT_EXCEPT_RE misses the common shapes. ``except X:  # noqa`` on the same
   line defeats it, and ``except X: return None`` is not matched at all even
   though that is closer to the bug that motivated the file. An AST-based
   implementation shared with tests/harambe_contract.py would fix both.

7. The frozen clock is inert without full git history. ``git log`` in a shallow
   clone returns the same date for every fixture, and the mtime fallback
   returns the checkout date. Verified in a depth-1 clone of the Chicago repo:
   all 83 fixtures reported one identical date. This repo's CI escapes it only
   because its checkout sets fetch-depth 0.

8. Portability is repo-shaped, not general. Run unchanged against City Bureau's
   Chicago repo, 38 of 58 spiders parsed, 3 had no fixture, and several helpers
   matching PARSER_NAME_RE take a datetime or a regex match rather than a
   response. It runs there; it does not run cleanly there.
"""
