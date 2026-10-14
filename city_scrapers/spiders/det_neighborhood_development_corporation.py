from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetNeighborhoodDevelopmentCorporationSpider(
    DetAuthorityMixin, CityScrapersSpider
):
    name = "det_neighborhood_development_corporation"
    agency = "Detroit Neighborhood Development Corporation"
    agency_url = "https://www.degc.org/ndc"
    tab_title = "NDC"
