from city_scrapers_core.constants import BOARD
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetLocalDevelopmentFinanceAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_local_development_finance_authority"
    agency = "Detroit Local Development Finance Authority"
    agency_url = "https://www.degc.org/ldfa/"
    title = "Board of Directors"
    tab_title = "LDFA"
    classification = BOARD
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def _parse_title(self, meeting):
        link_text = " ".join([l["title"] for l in meeting["links"]])
        if "PUBLIC INFORMATION" in link_text.upper():
            return "Public Information Meeting"
        return "Board of Directors"
