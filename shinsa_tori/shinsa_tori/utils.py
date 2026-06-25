import io
import unicodedata
import pandas as pd
import re
import pdfplumber

from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict
from urllib.parse import unquote

CURRENT_YEAR = str(datetime.now().year)
START_AT_PGSQL_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_LOCAL_RANK = '四段'
RANK_VALUE = '〇'
RANK_NAMES = ["無指定", "級", "初段", "弐段", "参段", "四段", "五段"]


def convert_full_to_half(input: str):
    return unicodedata.normalize('NFKC', input)

def get_era_year_by_text(text: str) -> int | None:
  match = re.search(r'([0-9０-９]+)\s*年度', text)

  if not match:
        print("警告：沒有找到任何年度資訊。")
        return None

  raw_year = match.group(1)
  return int(convert_full_to_half(raw_year))

def convert_reiwa_to_ce_year(reiwa_year: int) -> int:
    return reiwa_year + 2018

# 根據日本財政年度規則，推算並回傳最乾淨的 'YYYY-MM-DD 00:00:00' 東京當地時間字串。
def convert_date_by_fiscal_year(year: int, month: int, day: int) -> str:
    fiscal_start = datetime(year, 4, 1)
    target_dt = fiscal_start.replace(month=month, day=day)

    if target_dt < fiscal_start:
        target_dt = target_dt.replace(year = (year + 1))

    return target_dt.strftime(START_AT_PGSQL_FORMAT)

# DataFrame 欄位 Unicode 正規化
def normalize_df(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    df_copy = df.copy()

    for col in columns:
        if col in df_copy.columns:
            df_copy[col] = df_copy[col].map(
                lambda x: (
                    unicodedata.normalize('NFKC', str(x)) if pd.notna(x) else x
                )
            )

    return df_copy

class ShinsaType(Enum):
    LOCAL = 1
    UNION = 2
    CENTRAL = 3
class DeliveryMethodType(Enum):
    FACING = 1
    VIDEO = 2

class ShinsaYearParser:
    @staticmethod
    def convert_reiwa_to_ce(reiwa_year: int) -> int:
        return 2019 + reiwa_year - 1

    @staticmethod
    def get_ce_year_by_url(url: str) -> int:
        default_year = datetime.now().year

        if not url:
            return default_year

        decoded_url = unquote(str(url))

        # get ce year
        ce_match = re.search(r'.*((?:20|21)\d{2})', decoded_url)
        if ce_match:
            return int(ce_match.group(1))

        # get era year
        era_match = re.search(r'.*令和(\d+)年(度)?', decoded_url)
        if era_match:
            reiwa_year = int(era_match.group(1))
            return ShinsaYearParser.convert_reiwa_to_ce(reiwa_year)

        return default_year

class DeliveryMethodParser:
    @staticmethod
    def get_type(shinsa_name: str, note: str) -> DeliveryMethodType:
        name_upper = shinsa_name.upper()
        note_upper = note.upper()
        
        if "ビデオ" in name_upper or "動画" in name_upper or "ビデオ" in note_upper:
            return DeliveryMethodType.VIDEO
        else:
            return DeliveryMethodType.FACING

@dataclass
class ShinsaData(TypedDict):
    name: str
    location: str
    note: str
    year: int
    month: int
    day: int

class ShinsaEntity:
    def __init__(
            self,
            data: ShinsaData,
            delivery_method_parser: DeliveryMethodParser
        ):
        self._year = data.get('year', 0)
        self._month = data.get('month', 0)
        self._day = data.get('day', 0)

        self.name = str(data.get('name', '')).strip()
        self.location = str(data.get('location', '')).strip()
        self.note = str(data.get('note', '')).strip()
        self.type = self._get_type().value

        self.start_at = self._get_start_at_by_fiscal_year(
            self._year,
            self._month,
            self._day
        )

        self.delivery_method_type = delivery_method_parser.get_type(
            self.name, self.note
        ).value

    def _get_type(self) -> ShinsaType:
        name_upper = self.name.upper()
        
        if '中央' in name_upper:
            return ShinsaType.CENTRAL
        elif '連合' in name_upper:
            return ShinsaType.UNION
        else:
            return ShinsaType.LOCAL

    def _get_start_at_by_fiscal_year(self, year: int, month: int, day: int) -> str:
      return convert_date_by_fiscal_year(year, month, day)

class RankParser:
    def __init__(self):
        self.target_value = RANK_VALUE

    def parse_row(self, row: dict) -> list:
        accepted_names = []
        
        for name in RANK_NAMES:
            col = next((k for k in row.keys() if str(k) in name), None)

            if col:
                cell_value = str(row.get(col, '')).strip()

                if cell_value == self.target_value:
                    accepted_names.append(name)

        return accepted_names

class PDFLoader:
    def extract_document(self, pdf_file: io.BytesIO) -> list[list]:
        raw_tables = []

        with pdfplumber.open(pdf_file, unicode_norm="NFKC") as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    raw_tables.append(table)

        return raw_tables

class PDFDataCleaner:
    def __init__(self,
        column_mapping: dict = None,
        column_range: tuple[int, int] = None
    ):
        self._column_mapping = column_mapping if column_mapping is not None else {}

        self._col_slice = (
            slice(column_range[0], column_range[1])
            if column_range is not None
            else slice(None)
        )

        self._renamed_column_mapping = { value: key for key, value in self._column_mapping.items() }

    def clean_tables(self, raw_tables: list[list]) -> pd.DataFrame:
        all_dfs = []

        for table in raw_tables:
            if not table or len(table) < 2:
                continue

            clean_headers = [str(cell).replace(' ', '').replace('\n', '') for cell in table[0]]
            df_page = pd.DataFrame(table[1:], columns=clean_headers)

            if not df_page.empty:
                df_page = df_page.iloc[:, self._col_slice].copy()

            if self._renamed_column_mapping:
                df_page.rename(columns=self._renamed_column_mapping, inplace=True)

            all_dfs.append(df_page)

        if not all_dfs:
            return pd.DataFrame()

        df = pd.concat(all_dfs, ignore_index=True)

        return df