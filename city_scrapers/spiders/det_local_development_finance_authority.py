from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetLocalDevelopmentFinanceAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_local_development_finance_authority"
    agency = "Detroit Local Development Finance Authority"
    agency_url = "https://www.degc.org/ldfa"
    tab_title = "LDFA"
