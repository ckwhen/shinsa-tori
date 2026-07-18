
import scrapy
import re

from shinsa_tori.items import DocumentItem
from shinsa_tori.utils import ShinsaYearParser

SOURCE_URL = "http://kyudo-chiba.jp"
TARGET_PDF = './/a[contains(., "審査要項") and contains(@onclick, ".pdf")]'

class ChibaSpider(scrapy.Spider):
    name = 'chiba_spider'
    allowed_domains = ["kyudo-chiba.jp"]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        self.logger.info(f"正在掃描頁面中的隱藏 PDF 連結: {response.url}")

        header_menu_node = response.xpath('//ul[contains(@id, "MenuBar1")]')
        pdf_node = header_menu_node.xpath(TARGET_PDF)
        onclick_text = pdf_node.xpath("@onclick").get()

        if onclick_text:
            match = re.search(r"window\.open\(\s*['\"]([^'\s]+?\.pdf)['\"]", onclick_text)
            if match:
                relative_url = match.group(1)

        absolute_url = response.urljoin(relative_url)
        curr_year = ShinsaYearParser.get_ce_year_by_url(absolute_url)

        self.logger.info(f"🎯 嘗試下載檔案 [{relative_url}]，嘗試網址: {absolute_url}")

        yield DocumentItem(
            file_urls=[absolute_url],
            title='chiba',
            year=curr_year
        )