"""Shared HTTP constants and session setup for the Wayne County Commission scraper.

The county site sits behind Akamai bot protection that rejects requests
pretending to be a desktop browser (spoofed Chrome/Edge User-Agent and
sec-ch-* headers) when they don't come from a real browser. Plain,
honestly-identified HTTP clients are allowed, so we identify ourselves
as a scraper and use the same JSON endpoints the calendar widget uses.
"""

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
