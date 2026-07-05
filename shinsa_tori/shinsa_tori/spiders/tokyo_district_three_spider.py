import scrapy
import re

from datetime import datetime
from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    RANK_NAMES,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    ShinsaYearParser
)

BR_REGEX = r'<[bB][rR]\s*/?>'

FEDERATION_NAME = '東京都弓道連盟 第三地区'
SOURCE_URL = 'http://www.kyudo-tokyo3.jp/shinsa_toppage.html'

class TokyoDistrictThreeSpiderSpider(scrapy.Spider):
    name = "tokyo_district_three_spider"
    allowed_domains = ['kyudo-tokyo3.jp']
    start_urls = [SOURCE_URL]

    def parse(self, response):
        raw_year_text = response.xpath('//font[contains(., "審査実施要項")]').get('')
        container = response.xpath(
            '//p[contains(., "三地区審査")]/following-sibling::div[contains(@class, "main_top")]'
        )
        rows = container.xpath('.//div[@class="line_left" or @class="bottom_left"]')

        curr_year = ShinsaYearParser.get_ce_year_by_url(raw_year_text)
        shinsa_dicts = []

        for row in rows:
            raw_date = row.get()
            replaced_date = re.sub(BR_REGEX, '\n', raw_date)
            clean_date = scrapy.Selector(text=replaced_date).xpath('string(.)').get('').strip()

            raw_rank = row.xpath('following-sibling::div[2]').get()
            replaced_rank = re.sub(BR_REGEX, '\n', raw_rank)
            clean_rank = scrapy.Selector(text=replaced_rank).xpath('string(.)').get('').strip()

            date_list = [d.strip() for d in clean_date.split('\n') if d.strip()]
            rank_list = [d.strip() for d in clean_rank.split('\n') if d.strip()]

            raw_name = row.xpath('following-sibling::div[1]')
            name = raw_name.xpath('.//a[contains(., "審査会")]/text()').get('').strip()
            note = raw_name.xpath('.//span/text()').get('').strip()

            location = row.xpath('following-sibling::div[3]/text()').get('').strip()

            for date, rank in zip(date_list, rank_list):
                date_obj = datetime.strptime(date, '%Y/%m/%d')
                accepted_ranks = self.parse_target_ranks(rank)

                shinsa_data = ShinsaData(
                    name = name,
                    location = location,
                    year = curr_year,
                    month = date_obj.month,
                    day = date_obj.day,
                    note = note,
                )
                shinsa = ShinsaEntity(
                    data = shinsa_data,
                    delivery_method_parser = DeliveryMethodParser
                )
                shinsa_dict = {
                    'name': shinsa.name,
                    'type': shinsa.type,
                    'location': shinsa.location,
                    'start_at': shinsa.start_at,
                    'delivery_method_type': shinsa.delivery_method_type,
                    'note': shinsa.note,
                    'federation_name': FEDERATION_NAME,

                    'ranks': accepted_ranks
                }
                shinsa_dicts.append(shinsa_dict)

        for shinsa in shinsa_dicts:
            yield ShinsaItem(**shinsa)

    def parse_target_ranks(self, target_text):
        accepted_ranks = []

        if '〜' in target_text:
            parts = target_text.split('〜')
            if len(parts) == 2:
                start_rank = parts[0].strip()
                end_rank = parts[1].strip()

                is_eligible = False
                for rank in RANK_NAMES:
                    if rank == start_rank or start_rank in rank:
                        is_eligible = True
                    if is_eligible:
                        accepted_ranks.append(rank)
                    if rank == end_rank:
                        break

        elif '・' in target_text:
            parts = target_text.split('・')
            for part in parts:
                clean_part = part.strip()
                if clean_part in RANK_NAMES:
                    accepted_ranks.append(clean_part)

        else:
            clean_text = target_text.strip()
            if clean_text in RANK_NAMES:
                accepted_ranks.append(clean_text)

        return accepted_ranks