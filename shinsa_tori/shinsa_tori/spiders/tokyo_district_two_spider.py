import io
import os
import scrapy
import pandas as pd

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    ShinsaYearParser,
)

FEDERATION_NAME = '東京都弓道連盟 第二地区'
LOCAL_EXCEL_PATH = os.path.abspath('shinsa_tori/manual_excels/tokyo_district_two_20260421_5_1.xlsx')
SOURCE_URL = f'file://{LOCAL_EXCEL_PATH}'


class TokyoDistrictTwoSpider(scrapy.Spider):
    name = "tokyo_district_two_spider"
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
        df = df.iloc[:, 0:5].copy()

        column_mapping = {
            '行事名（第二地区）': 'name',
            '会場': 'location',
            '月': 'month',
            '日': 'day',
        }
        df = df.rename(columns=column_mapping)
        df.columns = [str(col).strip() for col in df.columns]

        if 'month' in df.columns:
            df['month'] = df['month'].astype(str).str.extract(r'(\d+)')
            df['month'] = df['month'].ffill()
            df['month'] = pd.to_numeric(df['month'], errors='coerce').fillna(0).astype(int)
            df['day'] = pd.to_numeric(df['day'], errors='coerce').fillna(0).astype(int)

        # 過濾非地連審查
        type_column = [col for col in df.columns if 'name' in col]
        if not type_column:
          print("警告：找不到名稱含有 name 的欄位，跳過過濾步驟。")
          return

        type_column_name = type_column[0]
        df = df[df[type_column_name].str.contains('地区審査', na=False)]

        for row in df.to_dict(orient='records'):
            shinsa_data = ShinsaData(
                name = str(row.get('name', '')).strip(),
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

                ranks = ["無指定", "初段", "弐段", "参段", "四段"]
            )