import scrapy
import re

from shinsa_tori.items import KyudojoItem
from shinsa_tori.shared.constants import PREFECTURE_MAP
from shinsa_tori.utils import (
    convert_full_to_half
)

class NipponKyudojoSpider(scrapy.Spider):
    name = "nippon_kyudojo_spider"
    allowed_domains = ["kyudo.jp"]
    start_urls = ["https://www.kyudo.jp/map/"]

    def parse(self, response):
        raw_dojos = response.xpath('//div[@class="gym"]')

        seen_dojos = set()

        for raw_dojo in raw_dojos:
            all_text_nodes = raw_dojo.xpath('.//text()').getall()
            # 移除 [<=999] 髒資料
            clean_texts = [re.sub(r'\[<=\d+\]', '', t.strip()) for t in all_text_nodes if t.strip()]

            address = None
            phone = None
            lat = None
            lng = None

            for text in clean_texts:
                clean_text = convert_full_to_half(text)

                if (
                    re.match(r'^\d{3}-?\d{4}', clean_text)
                    and any(pref in clean_text for pref in PREFECTURE_MAP)
                ):
                    address = clean_text

                if '電話' in clean_text:
                    parts = clean_text.split(':', 1)
                    if len(parts) > 1:
                        phone = parts[1].strip()

                if re.match(r'^\d{2,3}\.\d+$', clean_text):
                    val = float(clean_text)
                    # 依據日本地理位置，20~46度之間通常是緯度 (Latitude)
                    if 20.0 <= val <= 46.0 and lat is None:
                        lat = clean_text
                    # 122~153度之間通常是經度 (Longitude)
                    elif 122.0 <= val <= 153.0 and lng is None:
                        lng = clean_text

            prefecture_code = None
            if address:
                for pref, pref_code in PREFECTURE_MAP.items():
                    if pref in address:
                        prefecture_code = pref_code
                        break

            raw_name = raw_dojo.xpath('.//b/text()').get()
            # 如果用 XPath 找不到 <b>，就保底拿 clean_texts 的第一個非空文字當名稱
            name = convert_full_to_half(raw_name) if raw_name else (clean_texts[0] if clean_texts else None)

            # 特殊修正：如果地址在岩内町野束222，強制修正名稱為正確的「円山」
            if address and "岩内郡岩内町野束222" in address:
                name = "岩内円山弓道場"

            unique_key = f"{name}_{address}"
            if unique_key in seen_dojos:
                continue
            seen_dojos.add(unique_key)

            yield KyudojoItem(
                name=name,
                address=address,
                phone=phone,
                prefecture_code=prefecture_code,
                latitude=lat,
                longitude=lng,
            )