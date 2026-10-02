from city_scrapers_core.spiders import CityScrapersSpider

from city_scrapers.mixins import DetAuthorityMixin


class DetEightMileWoodwardCorridorImprovementAuthoritySpider(
    DetAuthorityMixin, CityScrapersSpider
):
    name = "det_eight_mile_woodward_corridor_improvement_authority"
    agency = "Detroit Eight Mile Woodward Corridor Improvement Authority"
    agency_url = "https://www.degc.org/emwcia"
    tab_title = "EMWCIA"
    event_keywords = ["EMWCIA", "Woodward Corridor Improvement Authority"]
