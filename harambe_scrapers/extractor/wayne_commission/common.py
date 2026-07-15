"""Shared HTTP constants and session setup for the Wayne County Commission scraper.

The county site sits behind Akamai bot protection that rejects requests
pretending to be a desktop browser (spoofed Chrome/Edge User-Agent and
sec-ch-* headers) when they don't come from a real browser. Plain,
honestly-identified HTTP clients are allowed, so we identify ourselves
as a scraper and use the same JSON endpoints the calendar widget uses.
"""

import re

import requests

BASE_URL = "https://www.waynecountymi.gov"
CALENDAR_PAGE_URL = f"{BASE_URL}/Government/County-Calendar"
GET_CALENDARS_URL = f"{BASE_URL}/ocapi/calendars/getcalendars"
GET_CALENDAR_ITEMS_URL = f"{BASE_URL}/ocapi/calendars/getcalendaritems"
GET_CONTENT_INFO_URL = f"{BASE_URL}/ocapi/get/contentinfo"

# Fallback for the combined-calendar widget on CALENDAR_PAGE_URL, used if
# the entity id can't be parsed out of the page HTML.
DEFAULT_CALENDAR_ENTITY_ID = "126c63c0-c42f-43aa-8168-1867f0ae80f1"
DEFAULT_CALENDAR_ENTITY_TYPE = "combinedCalendar"

USER_AGENT = "city-scrapers-det (+https://github.com/City-Bureau/city-scrapers-det)"

REQUEST_TIMEOUT = 30


def create_session() -> requests.Session:
    """Create a requests session with an honest User-Agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }
    )
    return session


# The Documenters platform matches meetings to agencies by the exact
# scraper name prefix of extras["cityscrapers/id"]. Agency "Wayne County
# Commission" registers these individual names, keyed here by normalized
# county-calendar label. Meetings stamped with anything else (including
# the old comma-joined 13-name string) are silently skipped at import.
REGISTERED_CALENDAR_SCRAPER_NAMES = {
    "full commission meeting": "wayne_full_commission",
    "full commission": "wayne_full_commission",
    "committee of the whole": "wayne_cow",
    "audit committee": "wayne_audit",
    "economic development committee": "wayne_economic_development",
    "government operations committee": "wayne_government_operations",
    "health and human services committee": "wayne_health_human_services",
    ("public safety, judiciary and homeland security committee"): "wayne_public_safety",
    "public services committee": "wayne_public_services",
    "ways and means committee": "wayne_ways_means",
    "election commission": "wayne_election_commission",
    "building authority": "wayne_building_authority",
    "ethics board": "wayne_ethics_board",
    "local emergency planning committee": "wayne_local_emergency_planning",
    "local emergency planning": "wayne_local_emergency_planning",
    # The county also has a departmental "Economic Development" calendar
    # distinct from the commission committee; keep it from colliding with
    # the registered committee name.
    "economic development": "wayne_economic_development_events",
}

# Calendars with no registered agency get a stable derived name; the
# platform skips them harmlessly until an agency registers that name.
FALLBACK_SCRAPER_NAME = "wayne_commission"


def _normalize_calendar_label(label: str) -> str:
    label = (label or "").replace("&", "and").replace("’", "'").lower()
    return " ".join(label.split())


def scraper_name_for_calendar(label: str) -> str:
    """Map a county-calendar label to a per-body scraper name."""
    normalized = _normalize_calendar_label(label)
    if normalized in REGISTERED_CALENDAR_SCRAPER_NAMES:
        return REGISTERED_CALENDAR_SCRAPER_NAMES[normalized]
    derived = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return f"wayne_{derived}" if derived else FALLBACK_SCRAPER_NAME
