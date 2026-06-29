import io
import scrapy
import pandas as pd

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    MONTH_DAY_PATTERN,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    RankParser,
    ShinsaYearParser,
    PDFLoader,
    PDFDataCleaner
)

SOURCE_URL = 'https://www.kyudo-kagoshima.org/events/'
TARGET_PDF = '//a[contains(@href, ".pdf") and contains(., "昇段審査")]/@href'


class KagoshimaSpider(scrapy.Spider):
    name = "kagoshima_spider"
    allowed_domains = ["kyudo-kagoshima.org"]
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
            'name': '審査名称',
            'location': '会場名',
            'date': '期日',
            'ranks_range': '審査範囲',
        }
        data_cleaner = PDFDataCleaner(
            column_mapping=column_mapping,
        )
        df = data_cleaner.clean_tables(raw_tables)
        df = data_cleaner.trim_cells(df, ['name', 'location'])

        # 過濾非地連審查
        name_pattern = r'^(?!.*連合).*審査'
        df = df[df['name'].str.contains(name_pattern, na=False, regex=True)]

        # TODO: 暫時過濾不確定日期
        is_vague_date = (
            df['date'].str.contains('後日|吉日', na=False) | 
            df['location'].str.contains('後日|吉日', na=False)
        )

        df = df[~is_vague_date]

        # 處理日期
        extracted_date = df['date'].str.extract(MONTH_DAY_PATTERN)

        df['month'] = pd.to_numeric(extracted_date['month'], errors='coerce').astype('Int64')
        df['day'] = pd.to_numeric(extracted_date['day'], errors='coerce').astype('Int64')

        rankParser = RankParser()
        shinsa_dicts = []

        for row in df.to_dict(orient='records'):
            rank_dicts = []

            shinsa_data = ShinsaData(
                name = str(row.get('name', '')).strip(),
                location = str(row.get('location', '')).strip(),
                year = curr_year,
                month = row.get('month', 0),
                day = row.get('day', 0),
                note = str(row.get('note', '')).strip(),
            )

            shinsa = ShinsaEntity(
                data = shinsa_data,
                delivery_method_parser = DeliveryMethodParser
            )

            rank_dicts.extend(rankParser.parse_rank_text(str(row.get('ranks_range', '')).strip()))

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