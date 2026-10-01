from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetDowntownDevelopmentAuthoritySpider(DetAuthorityMixin, CityScrapersSpider):
    name = "det_downtown_development_authority"
    agency = "Detroit Downtown Development Authority"
    agency_url = "https://www.degc.org/dda"
    tab_title = "DDA"
    video_link = "https://www.youtube.com/channel/UCYOkOt8yzAfrbgxFSH7_WNA/videos"
