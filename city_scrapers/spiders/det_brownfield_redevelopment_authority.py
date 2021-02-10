import re

from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetBrownfieldRedevelopmentAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_brownfield_redevelopment_authority"
    agency = "Detroit Brownfield Redevelopment Authority"
    timezone = "America/Detroit"
    agency_url = "https://www.degc.org/dbra/"
    tab_title = "DBRA"
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def _parse_title(self, meeting):
        link_text = " ".join([l["title"] for l in meeting["links"]])
        if "committee" in link_text.lower():
            return "{} Committee".format(
                link_text.upper().split(" COMMITTEE")[0]
            ).replace("DBRA ", "")
        elif "public hearing" in link_text.lower():
            return "{} Public Hearing".format(
                link_text.upper().split(" PUBLIC HEARING")[0]
            )
        elif re.match(r"DBRA[\- ]CAC", link_text):
            return "Community Advisory Committee"
        else:
            return "Board of Directors"

    def _parse_prev_links(self, response):
        link_map = super()._parse_prev_links(response)
        for dt, links in link_map.items():
            for link in links:
                link["title"] = link["title"].strip("–").strip()
        return link_map
