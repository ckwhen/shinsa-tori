import io
import os
import re
import scrapy
import pandas as pd

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    RANK_NAMES,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    ShinsaYearParser,
    convert_full_to_half,
)

FEDERATION_NAME = '大阪府弓道連盟'
LOCAL_EXCEL_PATH = os.path.abspath('shinsa_tori/manual_excels/osaka_2026_gyouji_r080314.xlsx')
SOURCE_URL = f'file://{LOCAL_EXCEL_PATH}'

LOCATION_MAP = {
    '万博': '万博記念公園弓道場',
    '吹田': '吹田市立武道館弓道場',
    '枚方': '昌栄工務店ひらかた渚体育館弓道場',
    '岸和田': 'きんでんアリーナ（岸和田市立総合体育館）弓道場',
    '堺': '堺市立初芝体育館弓道場',
    '八尾': '八尾市立総合体育館弓道場',
}

class OsakaSpider(scrapy.Spider):
    name = "osaka_spider"
    start_urls = [SOURCE_URL]

    def parse(self, response):
        self.logger.info(f"成功鎖定本地手動 Excel 檔案: {LOCAL_EXCEL_PATH}")

        yield scrapy.Request(
            url=response.url,
            callback=self.parse_excel,
            dont_filter=True
        )

    def parse_excel(self, response):
        self.logger.info("開始解構 Excel 表格數據...")
        excel_file = io.BytesIO(response.body)

        curr_year = ShinsaYearParser.get_ce_year_by_url(response.url)

        df = pd.read_excel(excel_file, engine='openpyxl')

        header_row_index = 0 

        df.columns = [str(val).strip() for val in df.iloc[header_row_index]]
        df = df.iloc[1:, 1:8].copy()

        print(df.columns.tolist())
        column_mapping = {
            '府    連    主    催    ・    主    管    行    事': 'name',
            '担当': 'type',
            '於': 'location',
            '月': 'month',
            '日': 'day',
        }
        df = df.rename(columns=column_mapping)
        df.columns = [str(col).strip() for col in df.columns]

        if 'month' in df.columns:
            df['month'] = df['month'].astype(str).str.extract(r'(\d+)')
            df['month'] = df['month'].ffill()
            df['month'] = df['month'].astype(str).apply(convert_full_to_half)
            df['month'] = pd.to_numeric(df['month'], errors='coerce').fillna(0).astype(int)
            df['day'] = pd.to_numeric(df['day'], errors='coerce').fillna(0).astype(int)

        # 過濾非地連審查
        cond_shinsa = df['type'].str.contains('審査', na=False)
        cond_not_yobi = ~df['name'].str.contains('予備会場', na=False)

        df = df[cond_shinsa & cond_not_yobi]

        if 'location' in df.columns:
            df['location'] = df['location'].astype(str).str.strip()
            df['location'] = df['location'].map(lambda x: LOCATION_MAP.get(x, x))

        range_pattern = r'([初弐参四五]+段)\s*[~～〜]\s*([初弐参四五]+段)'

        for row in df.to_dict(orient='records'):
            raw_name = str(row.get('name', '')).strip()

            clean_name = raw_name.replace('\n', ' ').replace('\r', ' ')
            clean_name = " ".join(raw_name.split())
            match = re.search(range_pattern, clean_name)

            if match:
                start_rank = match.group(1)
                end_rank = match.group(2)

                if start_rank in RANK_NAMES and end_rank in RANK_NAMES:
                    start_idx = RANK_NAMES.index(start_rank)
                    end_idx = RANK_NAMES.index(end_rank)
                    parsed_ranks = RANK_NAMES[start_idx : end_idx + 1]
            else:
                parsed_ranks = [rank for rank in RANK_NAMES if rank in clean_name]

            if not parsed_ranks:
                parsed_ranks = ["無指定"]

            shinsa_data = ShinsaData(
                name = clean_name,
                location = str(row.get('location', '')).strip(),
                year = curr_year,
                month = row.get('month', 0),
                day = row.get('day', 0),
            )

            shinsa = ShinsaEntity(
                data = shinsa_data,
                delivery_method_parser = DeliveryMethodParser
            )

            yield ShinsaItem(
                name = shinsa.name,
                type = shinsa.type,
                location = shinsa.location,
                start_at = shinsa.start_at,
                delivery_method_type = shinsa.delivery_method_type,
                federation_name = FEDERATION_NAME,

                ranks = parsed_ranks
            )