from city_scrapers_core.constants import BOARD
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetNextMichiganDevelopmentCorporationSpider(
    DetAuthorityMixin, CityScrapersSpider
):
    name = "det_next_michigan_development_corporation"
    agency = "Detroit Next Michigan Development Corporation"
    agency_url = "https://www.degc.org/d-nmdc/"
    title = "Board of Directors"
    tab_title = "D-NMDC"
    classification = BOARD
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def _parse_title(self, meeting):
        link_text = " ".join([l["title"] for l in meeting["links"]])
        if "special" in link_text.lower():
            return "Special Board Meeting"
        else:
            return "Board of Directors"
