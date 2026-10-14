from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetEconomicDevelopmentCorporationSpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_economic_development_corporation"
    agency = "Detroit Economic Development Corporation"
    agency_url = "https://www.degc.org/edc"
    tab_title = "EDC"
    video_link = "https://www.youtube.com/channel/UCYOkOt8yzAfrbgxFSH7_WNA/videos"
