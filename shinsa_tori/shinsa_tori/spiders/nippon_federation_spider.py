import scrapy
import re

from shinsa_tori.items import FederationItem
from shinsa_tori.shared.constants import PREFECTURE_MAP
from shinsa_tori.utils import convert_full_to_half

SOURCE_URL = 'https://www.kyudo.jp/aboutus/org.html'
TARGET = '//div[contains(@id, "area-")]'

class NipponFederationSpider(scrapy.Spider):
    name = "nippon_federation_spider"
    allowed_domains = ["kyudo.jp"]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        region_blocks = response.xpath(TARGET)

        for region_block in region_blocks:
            region_name = region_block.xpath('.//h3/text()').get()

            if not region_name:
                continue

            rows = region_block.xpath('.//table[contains(@class, "organization-list")]//tr')

            for row in rows:
                name_node = row.xpath('.//td[@class="name"]')
                raw_name = name_node.xpath('string(.)').get()
                if not raw_name:
                    continue

                clean_name = convert_full_to_half(raw_name.strip())

                prefecture_code = None
                for pref_name, code in PREFECTURE_MAP.items():
                    if pref_name in clean_name:
                        prefecture_code = code
                        break

                if prefecture_code == "JP-01":
                    yield from self.handle_hokkaido(region_name)

                elif prefecture_code == "JP-13":
                    yield from self.handle_tokyo(region_name)

                elif prefecture_code:
                    name = re.sub(r'一般社団法人\s*', '', clean_name).strip()

                    yield FederationItem(
                        name=name,
                        prefecture_code=prefecture_code,
                        region_name=region_name,
                    )

    def handle_hokkaido(self, region_name):
        yield FederationItem(
            name="北海道弓道連盟",
            prefecture_code="JP-01",
            region_name=region_name
        )

        hokkaido_subs = [
            "札幌弓道連盟",
            "恵庭弓道連盟",
            "小樽弓道連盟",
            "千歳弓道連盟"
        ]
        for name in hokkaido_subs:
            yield FederationItem(
                name=name,
                prefecture_code="JP-01",
                region_name=region_name
            )

    def handle_tokyo(self, region_name):
        yield FederationItem(
            name="東京都弓道連盟",
            prefecture_code="JP-13",
            region_name=region_name
        )

        tokyo_subs = [
            "東京都弓道連盟 第一地区",
            "東京都弓道連盟 第二地区",
            "東京都弓道連盟 第三地区",
        ]
        for name in tokyo_subs:
            yield FederationItem(
                name=name,
                prefecture_code="JP-13",
                region_name=region_name
            )
