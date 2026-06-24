import io
import re
import scrapy
import pandas as pd
import pdfplumber

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    CURRENT_YEAR,
    RANK_VALUE,
    RANK_NAMES,
    get_era_year_by_text,
    convert_reiwa_to_ce_year,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    RankParser,
    normalize_df
)

SOURCE_URL = 'http://www.kochikenkyudo.server-shared.com/shinsa/shinsa-chuo/'
TARGET_PDF = '//a[contains(@href, ".pdf") and contains(., "審査会日程")]/@href'

class KochiSpider(scrapy.Spider):
    name = "kochi_spider"
    allowed_domains = ['aikyuren.com']
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

        curr_year = CURRENT_YEAR
        all_dfs = []

        with pdfplumber.open(pdf_file) as pdf:
            if pdf.pages:
                first_page_text = pdf.pages[0].extract_text() or ''
                era_year = get_era_year_by_text(first_page_text)

                if era_year is None:
                    print("因找不到年度，取消此 PDF 的後續解析流程。")
                    return

                curr_year = convert_reiwa_to_ce_year(era_year)

            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue

                self.logger.info("整理表頭與欄位...")
                clean_headers = [str(cell).replace(' ', '').replace('\n', '') for cell in table[0]]
                df_page = pd.DataFrame(table[1:], columns = clean_headers)

                if df_page.shape[1] > 0:
                    df_page = df_page.iloc[:, :]

                all_dfs.append(df_page)

        if not all_dfs:
            print('沒有找到任何表格')
            return
        
        # 去除各頁表頭
        flattened_df = pd.concat(all_dfs, ignore_index = True)

        # 過濾非地連審查
        type_column = [col for col in df_page.columns if '連合' in col or '地連' in col]
        if not type_column:
          print("警告：找不到名稱含有 🔸 的欄位，跳過過濾步驟。")
          return
        
        type_column_name = type_column[0]
        flattened_df = flattened_df[flattened_df[type_column_name].str.contains('🔸', na=False)]

        shinsa_dicts = []

        target_df = normalize_df(
            flattened_df,
            ['日時', '審査名', '場所']
        )

        # 處理日期
        if '日時' not in target_df.columns:
            print("找不到指定的日期欄位")
            return

        extracted_date = target_df['日時'].str.extract(r'(?P<month>\d+)月(?P<day>\d+)日')

        target_df['year'] = curr_year
        target_df['month'] = pd.to_numeric(extracted_date['month'], errors='coerce')
        target_df['day'] = pd.to_numeric(extracted_date['day'], errors='coerce')

        for row in target_df.to_dict(orient='records'):
            rank_dicts = []
            shinsa_name = str(row.get('審査名', '')).strip()

            # 產生段位 columns
            for rank in RANK_NAMES:
                row[rank] = ''

            match = re.search(r'([初弐参四五]段)まで', shinsa_name)

            if match:
                max_rank = match.group(1)

                for rank in RANK_NAMES:
                    row[rank] = RANK_VALUE

                    if rank == max_rank:
                        break

            shinsa_data = ShinsaData(
                name = shinsa_name,
                location = str(row.get('場所', '')).strip(),
                year = row.get('year', 0),
                month = row.get('month', 0),
                day = row.get('day', 0)
            )

            shinsa = ShinsaEntity(
                data = shinsa_data,
                delivery_method_parser = DeliveryMethodParser
            )

            rankParser = RankParser()
            rank_dicts.extend(rankParser.parse_row(row))

            shinsa_dict = {
                'name': shinsa.name,
                'type': shinsa.type,
                'location': shinsa.location,
                'start_at': shinsa.start_at,
                'delivery_method_type': shinsa.delivery_method_type,

                'ranks': rank_dicts
            }

            shinsa_dicts.append(shinsa_dict)

        for shinsa in shinsa_dicts:
            yield ShinsaItem(**shinsa)