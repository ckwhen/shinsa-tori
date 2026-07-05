import io
import scrapy
import pandas as pd
import pdfplumber

from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    CURRENT_YEAR,
    get_era_year_by_text,
    convert_reiwa_to_ce_year,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    RankParser,
    normalize_df
)

FEDERATION_NAME = '愛知県弓道連盟'
SOURCE_URL = 'http://www.aikyuren.com/shinsanittei.html'
TARGET_PDF = '//a[contains(@href, ".pdf") and contains(., "地方審査日程")]/@href'

class AichiSpider(scrapy.Spider):
    name = "aichi_spider"
    allowed_domains = ['aikyuren.com']
    start_urls = [SOURCE_URL]

    def parse(self, response):
        pdf_relative_url = response.xpath(TARGET_PDF).get()

        if pdf_relative_url:
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
                    df_page = df_page.iloc[:, 1:]

                all_dfs.append(df_page)

        if all_dfs:
            # 去除各頁表頭
            flattened_df = pd.concat(all_dfs, ignore_index = True)

            flattened_df['year'] = curr_year

            # 過濾非地連審查
            flattened_df = flattened_df[flattened_df['審査区分'].str.contains('地方', na=False)]

            shinsa_dicts = self.convert_df_to_items(flattened_df)

            for shinsa in shinsa_dicts:
                yield ShinsaItem(**shinsa)

        else:
            print('沒有找到任何表格')

    @staticmethod
    def convert_df_to_items(df: pd.DataFrame) -> list:
        shinsa_dicts = []

        # 正規化日文字串
        target_df = normalize_df(
            df,
            ['年', '月', '日', '審査名']
        )

        # 清除空列
        if '審査名' in target_df.columns:
            target_df = target_df[target_df['審査名'].str.strip().ne('')]

        for row in target_df.to_dict(orient='records'):
            raw_day = str(row.get('日', '')).strip()

            days_list = []
            if '・' in raw_day:
                # 遇到「５・６」，利用全形中點拆開成字串清單 ['５', '６']
                split_days = raw_day.split('・')
                for d in split_days:
                    if d.isdigit():
                        days_list.append(int(d.strip()))
            else:
                # 常規單一日，直接轉成 int 丟進清單
                if raw_day.isdigit():
                    days_list.append(int(raw_day))

            for day in days_list:
                rank_dicts = []

                shinsa_data = ShinsaData(
                    name = str(row.get('審査名', '')).strip(),
                    location = str(row.get('会場名', '')).strip(),
                    note = str(row.get('備考', '')).strip(),
                    year = row.get('year', 0),
                    month = int(row.get('月')),
                    day = day,
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
                    'note': shinsa.note,
                    'federation_name': FEDERATION_NAME,

                    'ranks': rank_dicts
                }

                shinsa_dicts.append(shinsa_dict)

        return shinsa_dicts