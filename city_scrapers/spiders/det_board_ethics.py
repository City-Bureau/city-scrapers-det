from city_scrapers_core.constants import BOARD
from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetCityMixin


class DetBoardEthicsSpider(DetCityMixin, CityScrapersSpider):
    name = "det_board_ethics"
    agency = "Detroit Board of Ethics"
    agency_cal_id = "1356"
    agency_doc_id = ["1356", "5116"]

    def _parse_title(self, response):
        title = super()._parse_title(response)
        if "board" not in title.lower():
            return title
        return "Board of Ethics"

    def _parse_description(self, response):
        return ""

    def _parse_classification(self, response):
        return BOARD
