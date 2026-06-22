import unicodedata
import pandas as pd
import uuid

from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict

START_AT_PGSQL_FORMAT = "%Y-%m-%d %H:%M:%S"
RANK_NAMES = ["無指定", "級", "初段", "弐段", "参段", "四段", "五段"]

def convert_reiwa_to_ce_year(reiwa_year: int) -> int:
    return reiwa_year + 2018

# 根據日本財政年度規則，推算並回傳最乾淨的 'YYYY-MM-DD 00:00:00' 東京當地時間字串。
def convert_date_by_fiscal_year(reiwa_year: int, month: int, day: int) -> str:
    year = convert_reiwa_to_ce_year(reiwa_year)

    fiscal_start = datetime(year, 4, 1)
    target_dt = fiscal_start.replace(month=month, day=day)

    print(f'{fiscal_start}, {target_dt}')

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
class CandidateType(Enum):
    GENERAL = 1
    STUDENT = 2
    UNIVERSITY = 3
    FACULTY = 4
class DeliveryMethodType(Enum):
    FACING = 1
    VIDEO = 2

class CandidateParser:
    @staticmethod
    def get_type(shinsa_name: str, note: str) -> CandidateType:
        name_upper = shinsa_name.upper()
        note_upper = note.upper()
        
        if '高校' in name_upper or any(k in note_upper for k in ['高校生', '中学生', '小学生', '少年部', '中高生']):
            if any(k in note_upper for k in ['一般', '初段以上', '弐段以上', '参段以上']):
                return CandidateType.GENERAL
            return CandidateType.STUDENT
        elif any(k in name_upper for k in ['大学', '学連', '學生連盟']):
            return CandidateType.UNIVERSITY
        return CandidateType.GENERAL

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
            candidate_parser: CandidateParser,
            delivery_method_parser: DeliveryMethodParser
        ):
        self._year = data.get('year', 0)
        self._month = data.get('month', 0)
        self._day = data.get('day', 0)

        self.id = str(uuid.uuid4())
        self.name = str(data.get('name', '')).strip()
        self.location = str(data.get('location', '')).strip()
        self.note = str(data.get('note', '')).strip()
        self.type = self._get_type().value

        self.start_at = self._get_start_at(
            self._year,
            self._month,
            self._day
        )

        self.candidate_type = candidate_parser.get_type(
            self.name, self.note
        ).value
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

    def _get_start_at(self, reiwa_year: int, month: int, day: int) -> str:
      year = convert_reiwa_to_ce_year(reiwa_year)

      return datetime(year, month, day).strftime(START_AT_PGSQL_FORMAT)

class RankParser:
    def __init__(
            self,
            shinsa_id: str
        ):
        self.target_value = '〇'

        self.shinsa_id = shinsa_id

    def parse_row(self, row: dict) -> list:
        filtered_names = []
        
        for dan in RANK_NAMES:
            col = next((k for k in row.keys() if str(k) in dan), None)

            if col:
                cell_value = str(row.get(col, '')).strip()

                if cell_value == self.target_value:
                    filtered_names.append(dan)
                    
        return [
            {
                'shinsa_id': self.shinsa_id, 
                'rank_name': name
            } for name in filtered_names
        ]