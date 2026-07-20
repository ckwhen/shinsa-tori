
import scrapy
import re

from datetime import datetime
from loguru import logger
from shinsa_tori.items import DocumentItem
from shinsa_tori.utils import (
    convert_full_to_half,
    convert_ce_to_reiwa_year
)

SOURCE_URL = "https://fukuokakenkyudo.hp-ez.com/page8"

class FukuokaSpider(scrapy.Spider):
    name = 'fukuoka_spider'
    allowed_domains = [
        "fukuokakenkyudo.hp-ez.com",
        "file.www4.hp-ez.com",
        "img.www4.hp-ez.com"
    ]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        logger.info(f"[{self.name}] Successfully arrived at {response.url}")

        current_ce_year = datetime.now().year
        current_reiwa_year = convert_ce_to_reiwa_year(current_ce_year)

        table_node = response.xpath("//h1[contains(., '年間行事予定')]/following::table[1]")
        pdf_link_nodes = table_node.xpath(".//a[contains(@href, '.pdf')]")

        for link_node in pdf_link_nodes:
            link_text = link_node.xpath("string(.)").get("").strip()
            file_url = response.urljoin(link_node.xpath("@href").get())
            
            if not link_text or not file_url:
                continue

            clean_link_text = convert_full_to_half(link_text)
            target_year_pattern = fr"""^.*(令和{current_reiwa_year}年).*$"""

            if not re.match(target_year_pattern, clean_link_text):
                logger.debug(f"[{self.name}] Bypassed out-of-date fiscal link: '{clean_link_text}'")
                continue

            absolute_url = response.urljoin(file_url)
            region_node = link_node.xpath("./ancestor::td/preceding-sibling::td[1]")
            region_name = region_node.xpath("string(.)").get("").strip()
            clean_region_name = convert_full_to_half(region_name)

            if "福岡地区" not in clean_region_name:
                continue

            yield DocumentItem(
                file_urls=[absolute_url],
                title="fukuoka",
                year=current_ce_year
            )

        logger.info(f"[{self.name}] Loop terminated.")