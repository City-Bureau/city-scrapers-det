from city_scrapers_core.constants import BOARD
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetEconomicDevelopmentCorporationSpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_economic_development_corporation"
    agency = "Detroit Economic Development Corporation"
    agency_url = "https://www.degc.org/edc/"
    title = "Board of Directors"
    tab_title = "EDC"
    classification = BOARD
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def _validate_location(self, text):
        # Overriding for now
        pass

    def _parse_title(self, meeting):
        link_text = " ".join([l["title"] for l in meeting["links"]])
        if "committee" in link_text.lower():
            return "{} Committee".format(
                link_text.upper().split(" COMMITTEE")[0]
            ).replace("EDC ", "")
        elif "special" in link_text.lower():
            return "Special Board Meeting"
        else:
            return "Board of Directors"
