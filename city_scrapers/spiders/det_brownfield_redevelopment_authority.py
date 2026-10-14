import re

from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetBrownfieldRedevelopmentAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_brownfield_redevelopment_authority"
    agency = "Detroit Brownfield Redevelopment Authority"
    agency_url = "https://www.degc.org/dbra"
    tab_title = "DBRA"
    event_keywords = ["DBRA", "Brownfield"]

    def _parse_title(self, text):
        if re.search(r"\bCAC\b|community advisory", text, flags=re.I):
            return "Community Advisory Committee"
        if re.search(r"\bLBRF\b|revolving fund", text, flags=re.I):
            return "Local Brownfield Revolving Fund Committee"
        return super()._parse_title(text)
