from city_scrapers_core.constants import BOARD
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetDowntownDevelopmentAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_downtown_development_authority"
    agency = "Detroit Downtown Development Authority"
    agency_url = "https://www.degc.org/dda/"
    title = "Board of Directors"
    tab_title = "DDA"
    classification = BOARD
    location = {
        "name": "DEGC, Guardian Building",
        "address": "500 Griswold St, Suite 2200, Detroit, MI 48226",
    }

    def _parse_title(self, meeting):
        link_text = " ".join([l["title"] for l in meeting["links"]])
        if "committee" in link_text.lower():
            return "{} Committee".format(
                link_text.upper().split(" COMMITTEE")[0]
            ).replace("DDA ", "")
        else:
            return "Board of Directors"
