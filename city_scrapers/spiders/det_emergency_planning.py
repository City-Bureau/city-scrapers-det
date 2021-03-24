from city_scrapers_core.constants import ADVISORY_COMMITTEE
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetCityMixin


class DetEmergencyPlanningSpider(DetCityMixin, CityScrapersSpider):
    name = "det_emergency_planning"
    agency = "Detroit Local Emergency Planning Committee"
    dept_cal_id = "116"
    dept_doc_id = ["2521"]
    agency_doc_id = ["1461"]

    def _parse_title(self, response):
        title = super()._parse_title(response)
        if "committee" not in title.lower():
            return title
        return "Local Emergency Planning Committee"

    def _parse_description(self, response):
        return ""

    def _parse_classification(self, response):
        return ADVISORY_COMMITTEE
