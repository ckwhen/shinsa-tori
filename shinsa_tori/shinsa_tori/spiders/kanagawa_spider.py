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

FEDERATION_NAME = '神奈川県弓道連盟'
SOURCE_URL = 'https://www.kyudo-kanagawa.jp/sinsa/sinsa_1.html'
TARGET_PDF = '//a[contains(@href, ".pdf") and contains(., "地方審査会")]/@href'


class KanagawaSpider(scrapy.Spider):
    name = "kanagawa_spider"
    allowed_domains = ["kyudo-kanagawa.jp"]
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

        first_raw_table = raw_tables[0]
        shinsas_column_mapping = {
            'name': '回数種別',
            'location': '会場',
            'date': '月日',
            'ranks': '種別',
            'note': '会場は指定するので、希望日を書いて申し込む',
        }
        shinsas_data_cleaner = PDFDataCleaner(column_mapping=shinsas_column_mapping)
        shinsas_df = shinsas_data_cleaner.clean_table(first_raw_table)

        if 'name' in shinsas_df.columns:
            shinsas_df['name'] = shinsas_df['name'].ffill()

        shinsas_df['name'] = shinsas_df['name'].astype(str).str.replace('\n', ' ')

        if 'date' in shinsas_df.columns:
            shinsas_df['date'] = shinsas_df['date'].ffill()

        # 處理日期
        extracted_date = shinsas_df['date'].str.extract(MONTH_DAY_PATTERN)

        shinsas_df['month'] = pd.to_numeric(extracted_date['month'], errors='coerce')
        shinsas_df['day'] = pd.to_numeric(extracted_date['day'], errors='coerce')

        if 'ranks' in shinsas_df.columns:
            shinsas_df['ranks'] = shinsas_df['ranks'].ffill()

        if 'note' in shinsas_df.columns:
            shinsas_df['note'] = shinsas_df['note'].ffill()

        shinsas_df['note'] = (
            shinsas_df['note']
            .astype(str)
            .str.replace('\n', '')
            .str.replace('―', '')
        )

        # 處理會場名縮寫
        second_raw_table = raw_tables[1]
        locations_column_mapping = {
            'name': '略称',
            'location': '会場名',
        }
        locations_data_cleaner = PDFDataCleaner(column_mapping=locations_column_mapping)
        locations_df = locations_data_cleaner.clean_table(second_raw_table)
        locations_df['name'] = locations_df['name'].astype(str).str.replace(r'\s+', '', regex=True)

        locations_mapping = locations_df.set_index('name')['location'].to_dict()

        shinsas_df['full_location'] = shinsas_df['location'].map(locations_mapping)

        rankParser = RankParser()
        shinsa_dicts = []

        for row in shinsas_df.to_dict(orient='records'):
            rank_dicts = []

            shinsa_data = ShinsaData(
                name = str(row.get('name', '')).strip(),
                location = str(row.get('full_location', '')).strip(),
                year = curr_year,
                month = int(row.get('month', 0)),
                day = int(row.get('day', 0)),
                note = str(row.get('note', '')).strip(),
            )

            shinsa = ShinsaEntity(
                data = shinsa_data,
                delivery_method_parser = DeliveryMethodParser
            )

            rank_dicts.extend(rankParser.parse_rank_text(str(row.get('ranks', '')).strip()))

            shinsa_dict = {
                'name': shinsa.name,
                'type': shinsa.type,
                'location': shinsa.location,
                'start_at': shinsa.start_at,
                'delivery_method_type': shinsa.delivery_method_type,
                'note': shinsa.note,
                'federation_name': FEDERATION_NAME,

                'ranks': rank_dicts
            }

            shinsa_dicts.append(shinsa_dict)

        for shinsa in shinsa_dicts:
            yield ShinsaItem(**shinsa)