import io
import os
import re
import scrapy
import pandas as pd
import pdfplumber

from urllib.parse import urljoin
from shinsa_tori.items import ShinsaItem
from shinsa_tori.utils import (
    MONTH_DAY_PATTERN,
    MONTH_DAY_SLASH_PATTERN,
    RANK_NAMES,
    ShinsaData,
    ShinsaEntity,
    DeliveryMethodParser,
    ShinsaYearParser,
    convert_full_to_half,
    strip_whitespace,
    collapse_whitespace,
)

FEDERATION_NAME = '石川県弓道連盟'
START_URL = "http://kyudo-ishikawa.com"
SOURCE_URL = f'{START_URL}/r08/d_sinsa/sinsa.html'

RANK_RANGE_PATTERN = r'([初弐参四五]+段)\s*[~～〜]\s*([初弐参四五]+段)'
LOCATION_MAP = {
    '県武': '石川県立武道館弓道場',
    '小松': '小松市武道館弓道場',
}

def get_cleaned_location(raw_loc_str: str, location_map: dict) -> str:
    """
    字串壓縮防禦比對：從帶有雜訊的字串中映射出標準會場名稱
    """
    if not raw_loc_str:
        return '' # 預設安全防禦地點
        
    # 1. 字串壓縮防禦：移除所有空格（包含全形/半形空格）與強制換行
    pure_str = "".join(str(raw_loc_str).split())
    
    # 2. 遍歷字典鍵值進行子字串模糊比對
    for key, standard_name in location_map.items():
        if key in pure_str:
            return standard_name
            
    # 3. 容錯防禦：若完全沒匹配到，則保留原始清理後的文字或返回預設值
    return pure_str

def truncate_at_first_whitespace(input: str) -> str:
    match = re.match(r'[^\s]*', input)
    return match.group(0) if match else ""

class IshikawaSpider(scrapy.Spider):
    name = "ishikawa_spider"
    allowed_domains = ["kyudo-ishikawa.com"]
    start_urls = [SOURCE_URL]

    def parse(self, response):
        self.logger.info(f"成功鎖定線上即時網址: {response.url}")

        yield scrapy.Request(
            url=response.url,
            callback=self.parse_html,
            dont_filter=True,
        )

    def parse_html(self, response):
        self.logger.info("開始解構 HTML 表格數據...")

        # 防禦 Shift-JIS 亂碼（日本老舊網頁常見編碼修正）
        try:
            body_text = response.body.decode("cp932")
        except UnicodeDecodeError:
            body_text = response.text

        # 利用 ShinsaYearParser 或網頁文字特徵自動撈取西元年度
        curr_year = ShinsaYearParser.get_ce_year_by_url(response.url)

        base_dir_url = response.url.rsplit('/', 1)[0] + '/'
        self.logger.info(f"🎯 當前動態基礎目錄網址: {base_dir_url}")

        if not curr_year:
            year_match = re.search(r"(?:令和|R)\s*(\d+)\s*年度", body_text)
            curr_year = 2018 + int(year_match.group(1)) if year_match else 2026

        selector = scrapy.Selector(text=body_text)

        # 欄位模糊撈取原則：定位包含「審査」的主活動列元素 (<tr>)
        # 排除包含「規程、細則、申込」等純文件說明的雜訊列
        table_node = selector.xpath("//font[contains(., '県内審査予定')]/following::table[1]")
        raw_table = table_node.get()
        
        if not raw_table:
            self.logger.error("❌ 找不到『県内審査予定』或其後方沒有任何 table！")
            return

        tr_nodes = table_node.xpath(".//tr[not(.//th) and position() > 1]")

        dfs = pd.read_html(io.StringIO(raw_table))
        df = dfs[0]

        if df.empty or len(df) == 0:
            self.logger.error("❌ 抓到的 Table 內沒有任何資料列，無法進行標頭提拔！")
            print(f"抓到的無效 HTML 片段為: {raw_table[:200]}") 
            return

        column_mapping = {
            '実施月日': 'date',
            '審 査 名': 'name',
            '実施要項': 'detial',
            '県連締切(必着)': 'reg_end_at',
            '結果': 'result',
        }
        df = df.rename(columns=column_mapping)

        for idx, row in enumerate(df.to_dict(orient='records')):
            raw_name = str(row.get('name', '')).strip()
            clean_name = truncate_at_first_whitespace(raw_name)

            requirement_url = None
            if idx < len(tr_nodes):
                current_tr_node = tr_nodes[idx]
                # 撈取該列中任何指向 .pdf 的超連結 href
                pdf_href = current_tr_node.xpath(".//a[contains(@href, '.pdf') and contains(., '審査要項')]/@href").get()
                if pdf_href:
                    requirement_url = urljoin(base_dir_url, pdf_href.strip())


            row_data = {
                "name": clean_name,
                "year": curr_year,
            }

            if requirement_url:
                self.logger.info(f"📄 發現審査要項 PDF 連結，啟動記憶體不落地解析: {requirement_url}")
                yield scrapy.Request(
                    url=requirement_url,
                    callback=self.parse_pdf,
                    meta={"row_data": row_data},
                    dont_filter=True, 
                )

    def parse_pdf(self, response):
        row_data = response.meta["row_data"]
        parsed_items = []

        try:
            pdf_bytes = io.BytesIO(response.body)

            with pdfplumber.open(pdf_bytes) as pdf:
                first_page = pdf.pages[0]
                tables = first_page.extract_tables()
                
                # 尋找目標表格
                target_table = None
                for table in tables:
                    header_text = strip_whitespace("".join(str(cell) for cell in table[0]))
                    keywords = ["実施日", "審査日", "会場"]

                    if any(keyword in header_text for keyword in keywords):
                        target_table = table
                        break

                if not target_table:
                    return

                self.logger.info(f"🎯 成功定位 PDF 內的『{header_text}』表格！")

                detial_df = pd.DataFrame(target_table)
                detial_df.columns = [strip_whitespace(str(val)) for val in detial_df.iloc[0]]
                detial_df = detial_df.iloc[1:].reset_index(drop=True)

                column_mapping = {
                    '審査日': 'date',
                    '実施日': 'date',
                    '会場': 'location',
                    '審査種別': 'ranks',
                    '備考': 'note',
                }
                detial_df = detial_df.rename(columns=column_mapping)

                if 'date' in detial_df.columns:
                    detial_df['date'] = detial_df['date'].replace('', None).ffill()

                for row in detial_df.to_dict(orient='records'):
                    raw_date = str(row.get('date', '')).strip()
                    raw_ranks = str(row.get('ranks', '')).strip()
                    raw_loc  = str(row.get('location', '')).strip()

                    pure_date = convert_full_to_half(raw_date)

                    date_match = (
                        re.search(MONTH_DAY_PATTERN, pure_date)
                        or re.search(MONTH_DAY_SLASH_PATTERN, pure_date)
                    )

                    month = int(date_match.group("month"))
                    day = int(date_match.group("day"))

                    ranks_text = collapse_whitespace(raw_ranks)

                    location = get_cleaned_location(raw_loc, LOCATION_MAP)

                    parsed_item = {
                        "name": f"{row_data['name']} {ranks_text}",
                        "location": location,
                        "year": row_data["year"],
                        "month": month,
                        "day": day,
                        "ranks_text": ranks_text,
                    }
                    parsed_items.append(parsed_item)

            pdf_bytes.close()

        except Exception as e:
            self.logger.error(f"❌ 記憶體解析 PDF 內文失敗: {e}")

        if parsed_items:
            # 如果成功從 PDF 拆解出精準的「多日/多會場」分流明細，則以 PDF 的資料為準發射 Item
            for item_data in parsed_items:
                yield from self.build_item(item_data)

    def build_item(self, row_data):
        ranks_text = row_data["ranks_text"]

        parsed_ranks = []

        if "と" in ranks_text:
            actual_target_text = ranks_text.split("と")[-1]
        else:
            actual_target_text = ranks_text

        if "無指定" in actual_target_text:
            parsed_ranks.append("無指定")

        mock_text = actual_target_text.replace("無指定", "初段")

        range_match = re.search(RANK_RANGE_PATTERN, mock_text)
        
        if range_match:
            start_rank = range_match.group(1)
            end_rank = range_match.group(2)
            if start_rank in RANK_NAMES and end_rank in RANK_NAMES:
                start_idx = RANK_NAMES.index(start_rank)
                end_idx = RANK_NAMES.index(end_rank)
                parsed_ranks.extend(RANK_NAMES[start_idx : end_idx + 1])

        for rank in RANK_NAMES:
            if rank in actual_target_text and rank not in parsed_ranks:
                parsed_ranks.append(rank)
        parsed_ranks = sorted(parsed_ranks, key=lambda x: RANK_NAMES.index(x) if x in RANK_NAMES else -1)

        shinsa_data = ShinsaData(
            name = row_data["name"],
            location = row_data["location"],
            year = row_data["year"],
            month = row_data["month"],
            day = row_data["day"],
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