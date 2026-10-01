from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetNextMichiganDevelopmentCorporationSpider(
    DetAuthorityMixin, CityScrapersSpider
):
    name = "det_next_michigan_development_corporation"
    agency = "Detroit Next Michigan Development Corporation"
    agency_url = "https://www.degc.org/d-nmdc"
    tab_title = "D-NMDC"
    event_keywords = ["D-NMDC", "DNMDC", "Next Michigan Development Corporation"]
