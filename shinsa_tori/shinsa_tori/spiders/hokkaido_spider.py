
import scrapy
import re

from datetime import datetime
from loguru import logger
from shinsa_tori.items import DocumentItem
from shinsa_tori.utils import (
    convert_full_to_half,
    convert_ce_to_reiwa_year
)

SOURCE_URL = "https://sapporokyudo.jp/schedule/"
TARGET_PDF = './/a[contains(@href, ".pdf") and contains(., "審査予定表")]'

class HokkaidoSpider(scrapy.Spider):
    name = 'hokkaido_spider'
    allowed_domains = ["sapporokyudo.jp"]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        logger.info(f"[{self.name}] Successfully arrived at {response.url}")

        current_ce_year = datetime.now().year
        current_reiwa_year = convert_ce_to_reiwa_year(current_ce_year)

        pdf_node = response.xpath(TARGET_PDF)
        file_url = pdf_node.xpath("@href").get()
        link_text = pdf_node.xpath("string(.)").get("").strip()
        clean_link_text = convert_full_to_half(link_text)

        target_year_pattern = fr"""^.*(令和{current_reiwa_year}年).*$"""

        if not re.match(target_year_pattern, clean_link_text):
            logger.debug(f"[{self.name}] Bypassed out-of-date fiscal link: '{clean_link_text}'")

        absolute_url = response.urljoin(file_url)

        yield DocumentItem(
            file_urls=[absolute_url],
            title="hokkaido",
            year=current_ce_year
        )