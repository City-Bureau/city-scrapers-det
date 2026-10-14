"""Shared setup for the tests of spiders built on DetAuthorityMixin."""

import json
from os.path import dirname, join

from city_scrapers_core.utils import file_response
from freezegun import freeze_time
from scrapy import Request
from scrapy.settings import Settings

FILES_DIR = join(dirname(__file__), "files")
FROZEN_DATE = "2026-09-27"
VIDEO_LINK = {
    "href": "https://www.youtube.com/channel/UCYOkOt8yzAfrbgxFSH7_WNA/videos",
    "title": "YouTube channel",
}


def load_events():
    with open(join(FILES_DIR, "det_authority_events.json")) as f:
        return json.load(f)["events"]


def documents_response(spider):
    return file_response(
        join(FILES_DIR, "{}.html".format(spider.name)), url=spider.agency_url
    )


def detail_response(spider, url):
    return file_response(join(FILES_DIR, "{}_detail.html".format(spider.name)), url=url)


def parse_items(spider, detail_urls=()):
    """Run the documents callback the way Scrapy would after the events API.

    Requests for event detail pages listed in ``detail_urls`` are answered with
    the spider's saved detail page. Others go through the same path as a detail
    page that failed to load, keeping what the events API provided.
    """
    spider.settings = Settings(values={"CITY_SCRAPERS_ARCHIVE": False})
    events = [e for e in load_events() if spider._is_agency_event(e)]
    items = []
    with freeze_time(FROZEN_DATE):
        for result in spider._parse_documents(documents_response(spider), events):
            if not isinstance(result, Request):
                items.append(result)
                continue
            meeting = result.cb_kwargs["meeting"]
            if result.url in detail_urls:
                response = detail_response(spider, result.url)
                items.extend(spider._parse_event_detail(response, meeting=meeting))
            else:
                items.append(spider._finish_meeting(meeting))
    return sorted(items, key=lambda i: (i["start"], i["title"]))


def find_item(items, start):
    return next(i for i in items if i["start"] == start)
