import io
import scrapy
import pandas as pd

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    MAX_LOCAL_RANK,
    RANK_VALUE,
    RANK_NAMES,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    RankParser,
    ShinsaYearParser,
    PDFLoader,
    PDFDataCleaner
)

DISTRICT_NAME = '第一地区'
SOURCE_URL = 'https://kyudo-tokyo1.jp/%e5%b9%b4%e9%96%93%e8%a1%8c%e4%ba%8b%e4%ba%88%e5%ae%9a/'
TARGET_PDF = '//a[contains(@href, ".pdf") and contains(., "第一地区行事予定")]/@href'


class TokyoDistrictOneSpider(scrapy.Spider):
    name = "tokyo_district_one_spider"
    allowed_domains = ["kyudo-tokyo1.jp"]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        pdf_relative_url = response.xpath(TARGET_PDF).get()

        if not pdf_relative_url:
            return

        pdf_absolute_url = response.urljoin(pdf_relative_url)
        self.logger.info(f"成功鎖定全國總表 PDF 網址: {pdf_absolute_url}")

        yield scrapy.Request(
            url = pdf_absolute_url,
            callback = self.parse_pdf,
            dont_filter = True
        )

    def parse_pdf(self, response):
        self.logger.info("開始解構 PDF 表格數據...")
        pdf_file = io.BytesIO(response.body)

        curr_year = ShinsaYearParser.get_ce_year_by_url(response.url)

        loader = PDFLoader()
        raw_tables = loader.extract_document(pdf_file)

        column_mapping = {
            'name': '第一地区',
            'location': '会場',
            'month': '月',
            'day': '日',
        }
        data_cleaner = PDFDataCleaner(
            column_mapping=column_mapping,
            column_range=(0, 5)
        )
        df = data_cleaner.clean_tables(raw_tables)

        if 'month' in df.columns:
            df['month'] = df['month'].ffill()

        df['month'] = pd.to_numeric(df['month'], errors='coerce').fillna(0).astype(int)
        df['day'] = pd.to_numeric(df['day'], errors='coerce').fillna(0).astype(int)

        # 過濾非地連審查
        type_column = [col for col in df.columns if 'name' in col]
        if not type_column:
          print("警告：找不到名稱含有 name 的欄位，跳過過濾步驟。")
          return
        
        type_column_name = type_column[0]
        df = df[df[type_column_name].str.contains('地方審査', na=False)]

        rankParser = RankParser()
        shinsa_dicts = []

        for row in df.to_dict(orient='records'):
            rank_dicts = []

            # 產生段位 columns
            for rank in RANK_NAMES:
                row[rank] = ''

            for rank in RANK_NAMES:
                row[rank] = RANK_VALUE

                if rank == MAX_LOCAL_RANK:
                    break

            shinsa_data = ShinsaData(
                name = str(row.get('name', '')).strip(),
                location = str(row.get('location', '')).strip(),
                year = curr_year,
                month = row.get('month', 0),
                day = row.get('day', 0),
                note = DISTRICT_NAME,
            )

            shinsa = ShinsaEntity(
                data = shinsa_data,
                delivery_method_parser = DeliveryMethodParser
            )

            rank_dicts.extend(rankParser.parse_row(row))

            shinsa_dict = {
                'name': shinsa.name,
                'type': shinsa.type,
                'location': shinsa.location,
                'start_at': shinsa.start_at,
                'delivery_method_type': shinsa.delivery_method_type,
                'note': shinsa.note,

                'ranks': rank_dicts
            }

            shinsa_dicts.append(shinsa_dict)

        for shinsa in shinsa_dicts:
            yield ShinsaItem(**shinsa)