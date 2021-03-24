from city_scrapers_core.constants import COMMISSION
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetCityMixin


class DetEntertainmentCommissionSpider(DetCityMixin, CityScrapersSpider):
    name = "det_entertainment_commission"
    agency = "Detroit Entertainment Commission"
    agency_cal_id = "1616"
    agency_doc_id = ["1616", "7066", "7071"]

    def _parse_title(self, response):
        title = super()._parse_title(response)
        if "commission" not in title.lower():
            return title
        return "Entertainment Commission"

    def _parse_description(self, response):
        return ""

    def _parse_classification(self, response):
        return COMMISSION
