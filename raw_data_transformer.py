import numpy as np
import pandas as pd
import config_helper

from loguru import logger
from pathlib import Path
from functools import partial
from shared.constants import RANK_NAMES
from shared.ranks_helper import (
    extract_ranks_by_regexs,
    parse_peer_to_peer,
    parse_range,
    parse_hybrid,
    format_parsed_ranks
)
from shared.string_helper import clean_empty_and_type

EMPTY_CELLS_TOLERANCE = 3
DATE_EXTRACT_REGEX_MAP = {
    # 情況 A: 4月19日 (日)
    "combined_text": r"(?P<month>\d+)\s*月\s*(?P<day>\d+)\s*日.*",
    # 情況 B: | 4月 | 19日 |
    "split_columns": r"\s*(?P<digit>\d{1,2})\s*",
}

def parse_ranks_semantic(ranks_str: str, parse_type: str) -> str:
    rank_list = []

    if parse_type == "peer_to_peer":
        rank_list = parse_peer_to_peer(ranks_str)
    elif parse_type == "range":
        rank_list = parse_range(ranks_str)
    elif parse_type == "hybrid":
        rank_list = parse_hybrid(ranks_str)

    parsed_ranks_str = format_parsed_ranks(rank_list, RANK_NAMES)

    if not parsed_ranks_str:
        logger.debug(f"Rank semantic parsing returned empty result | Input: '{ranks_str}' | Type: '{parse_type}'")
        return ""

    logger.info(f"Rank parsed | '{ranks_str}' -> '{parsed_ranks_str}'")

    return parsed_ranks_str

def transform_raw_data(prefecture):
    """
    Transform 階段：
    讀取 Staging 原始 CSV 矩陣，執行多重欄位特徵清洗與合併。
    """
    logger.info(f"[{prefecture}] Starting CSV data transformation and cleaning pipeline")

    # 設定檔初始化
    try:
        pref_config = config_helper.load_config_by_prefecture(
            config_path="config.yaml",
            prefecture=prefecture
        )
        transform_settings = pref_config.get("transform", {})
    except Exception as e:
        logger.exception(f"[{prefecture}] Transformer initialization failed: Configuration block load error")
        raise e

    # 定義輸入與輸出路徑
    input_dir = Path(transform_settings.get("input_folder", "./shinsa_tori/downloads"))
    output_dir = Path(transform_settings.get("output_folder", "./shinsa_tori/outputs"))

    logger.debug(f"[{prefecture}] Scanning Staging CSV directory: '{input_dir}'")

    if not input_dir.exists():
        logger.error(f"[{prefecture}] Directory error: Staging folder '{input_dir}' does not exist")
        raise FileNotFoundError(f"Staging CSV directory missing: {input_dir}")

    raw_csv_files = list(input_dir.glob(f"*_{prefecture}_*.csv"))

    if len(raw_csv_files) == 0:
        logger.error(f"[{prefecture}] Data missing: No matching *_{prefecture}_*.csv files found in '{input_dir}'")
        raise FileNotFoundError(f"No Staging CSV files found for prefecture: {prefecture}")

    logger.info(f"[{prefecture}] Loading and merging {len(raw_csv_files)} CSV files into memory")

    try:
        df_list = [
            pd.read_csv(csv_path, encoding="utf-8-sig", encoding_errors="replace")
            for csv_path in raw_csv_files
        ]
        raw_df = pd.concat(df_list, ignore_index=True)
    except Exception as e:
        logger.exception(f"[{prefecture}] DataFrame merge failed: Pandas I/O or concatenation error")
        raise e

    # 鎖定目標檔案（以第一個檔案為基準作為日誌上下文）
    csv_path = raw_csv_files[0]

    logger.info(f"[{prefecture}] DataFrame merged successfully | Total raw rows: {len(raw_df)} | Primary baseline file: '{csv_path.name}'")

    # =====================================================================
    # Preparation
    # =====================================================================
    # 讀取 YAML 中的核心設定
    federation_name = pref_config.get("federation_name")
    allow_keywords = transform_settings.get("allow_keywords", [])
    ignore_keywords = transform_settings.get("ignore_keywords", [])
    ffill_cols = transform_settings.get("ffill_columns", [])
    shinsa_columns_map = transform_settings.get("shinsa_columns_map", {})
    note_columns_map = transform_settings.get("note_columns_map", {})
    ranks_setup = transform_settings.get("ranks_setup", {})
    date_extract_type = transform_settings.get("date_extract_type", "")
    rank_source_column = ranks_setup.get("source_column", "")
    ranks_parse_type = str(ranks_setup.get("parse_type", ""))
    ranks_text_regexs = ranks_setup.get("text_regexs")

    current_year = csv_path.name.split("_")[0]

    # 將 RAW CSV 轉成 DataFrame
    logger.debug(f"[{prefecture}] Loading csv string profile from: '{csv_path.name}'")
    raw_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if raw_df.empty:
        logger.error(f"[{prefecture}] Data validation error: Source DataFrame is completely empty from '{csv_path.name}'")
        raise ValueError(f"Source raw data file is empty: {csv_path.name}")

    clean_df = raw_df.copy()

    # 依據 ffill_columns 填補指定欄位中的 rowspan
    existing_ffill_cols = [col for col in ffill_cols if col in clean_df.columns]
    if not existing_ffill_cols:
        logger.warning(f"[{prefecture}] Metadata discrepancy: Configured ffill_columns '{ffill_cols}' do not exist in DataFrame")
    else:
        # 將指定欄位中的「空字串」與「純空格」先轉成可以使用 ffill 的 NaN
        for col in existing_ffill_cols:
            clean_df[col] = clean_df[col].replace(r"^\s*$", np.nan, regex=True)

        # 進行向下填補
        clean_df[existing_ffill_cols] = clean_df[existing_ffill_cols].ffill()
        
        # 防呆: 將 NaN 轉回空字串
        clean_df[existing_ffill_cols] = clean_df[existing_ffill_cols].fillna("")
        
        logger.debug(f"[{prefecture}] Rowspan padding applied successfully for columns: {existing_ffill_cols}")

    # 全量去頭尾空格
    clean_df = clean_df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

    # 補足其餘 shinsa 必要標準欄位
    clean_df["type"] = ""
    clean_df["delivery_method_type"] = ""
    clean_df["federation_name"] = federation_name
    clean_df["year"] = pd.to_numeric(current_year, errors="coerce")
    clean_df["ranks"] = ""
    clean_df["file_name"] = raw_df["file_name"]
    clean_df["url_hash"] = raw_df["url_hash"]

    # 依據 shinsa_columns_map 對 rename 進行向量化更名映射
    clean_df = clean_df.rename(columns=shinsa_columns_map, errors="ignore")

    # =====================================================================
    # Phase 1: 清除可能的無效資料
    # =====================================================================
    initial_row_count = len(raw_df)
    logger.debug(f"[{prefecture}] Initiating Phase 1 row filtration | Initial rows: {initial_row_count}")

    # 取得每列平均有效資料格數，用以清除無效行
    valid_cells_per_row = ((clean_df != "") & clean_df.notna()).sum(axis=1)
    mean_valid_cells = valid_cells_per_row.mean()
    dynamic_threshold = mean_valid_cells - EMPTY_CELLS_TOLERANCE

    # 執行密度過濾
    clean_df = clean_df[valid_cells_per_row >= dynamic_threshold]
    after_density_count = len(clean_df)

    # 依據 allow_keywords 保留所有包含 keyword 的列
    allow_pattern = '|'.join(allow_keywords)
    is_any_allow = clean_df.apply(
        lambda col: col.astype(str).str.contains(allow_pattern, case=False, na=False)
    ).any(axis=1)
    clean_df = clean_df[is_any_allow]

    # 依據 ignore_keywords 移除所有包含 keyword 的列
    if not ignore_keywords:
        logger.info(f"[{prefecture}] Blocklist bypass skipped | Reason: ignore_keywords configuration is empty.")
    else:
        deny_pattern = '|'.join(ignore_keywords)

        is_any_deny = clean_df.apply(
            lambda col: col.astype(str).str.contains(deny_pattern, case=False, na=False)
        ).any(axis=1)

        logger.debug(f"[{prefecture}] Blocklist match pattern: '{deny_pattern}' | Detected noise rows: {is_any_deny.sum()}")
        clean_df = clean_df[~is_any_deny]

    logger.debug(f"[{prefecture}] Dynamic density threshold filtration applied | Threshold: {dynamic_threshold:.2f} | Remaining rows: {after_density_count}")

    final_phase_count = len(clean_df)
    logger.info(f"[{prefecture}] Phase 1 filtration completed | Removed {initial_row_count - final_phase_count} noise rows | Remaining rows: {final_phase_count}")
    if clean_df.empty:
        logger.error(f"[{prefecture}] Integrity failure: Zero records remained after Phase 1 keyword filtering")
        raise ValueError(f"Data survival check failed: All rows filtered out as noise for prefecture {prefecture}")

    # =====================================================================
    # Phase 2: 開始清洗 shinsa 所需資料
    # =====================================================================
    # 處理月、日拆分
    if date_extract_type == "combined_text":
        regex = DATE_EXTRACT_REGEX_MAP.get("combined_text")
        extracted = clean_df["start_at"].astype(str).str.extract(regex)
        clean_df["month"] = extracted["month"]
        clean_df["day"] = extracted["day"]

    elif date_extract_type == "split_columns":
        logger.debug(f"[{prefecture}] Multi-column date extraction triggered [split_columns mode]")

        # 檢查 config.yaml 是否設定了 shinsa_columns_map
        if not shinsa_columns_map or not isinstance(shinsa_columns_map, dict):
            critical_err = (
                f"[{prefecture}] Configuration Hazard: 'date_extract_type' is set to 'split_columns', "
                f"but 'shinsa_columns_map' is missing or malformed in config.yaml!"
            )
            logger.error(critical_err)
            raise ValueError(critical_err)

        # 反查月份與日期的實體欄位
        # 查找 shinsa_columns_map，將 "month" 與 "day" 的擁有者找出來
        month_source_col = None
        day_source_col = None
        for physical_col, semantic_name in shinsa_columns_map.items():
            if semantic_name == "month":
                month_source_col = physical_col
            elif semantic_name == "day":
                day_source_col = physical_col

        if not month_source_col or not day_source_col:
            critical_err = (
                f"[{prefecture}] Matrix Alignment Failure: Could not resolve physical mapping "
                f"for semantic 'month' or 'day' tokens from shinsa_columns_map: {shinsa_columns_map}"
            )
            logger.error(critical_err)
            raise KeyError(critical_err)

        # 檢查這些實體欄位是否存在於目前讀取的 clean_df 當中
        month_source_col = shinsa_columns_map[month_source_col]
        day_source_col = shinsa_columns_map[day_source_col]
        if month_source_col not in clean_df.columns or day_source_col not in clean_df.columns:
            critical_err = (
                f"[{prefecture}] Data Integrity Fault: Resolved columns ['{month_source_col}', '{day_source_col}'] "
                f"do not exist within extracted PDF dataframe grid system! Existing columns: {list(clean_df.columns)}"
            )
            logger.error(critical_err)
            raise LookupError(critical_err)

        logger.info(
            f"[{prefecture}] Dynamic Routing Synced | "
            f"Month channel mapped to '{month_source_col}' | Day channel mapped to '{day_source_col}'"
        )

        digit_regex = DATE_EXTRACT_REGEX_MAP.get("split_columns")
        extracted_month = clean_df[month_source_col].astype(str).str.extract(digit_regex)
        extracted_day = clean_df[day_source_col].astype(str).str.extract(digit_regex)

        clean_df["month"] = extracted_month["digit"]
        clean_df["day"] = extracted_day["digit"]

    # 依據日本財政年度規則調整審查年份
    fiscal_start_at = pd.to_datetime(
        clean_df["year"].astype(str) + "-04-01", 
        errors="coerce"
    )
    temp_start_at = pd.to_datetime(
        clean_df["year"].astype(str) + "-" + 
        clean_df["month"].astype(str) + "-" + 
        clean_df["day"].astype(str),
        errors="coerce"
    )
    clean_df["temp_year"] = np.where(
        temp_start_at < fiscal_start_at,
        clean_df["year"].astype(int) + 1,
        clean_df["year"].astype(int)
    )
    final_start_at = pd.to_datetime(
        clean_df["temp_year"].astype(str) + "-" + 
        clean_df["month"].astype(str) + "-" + 
        clean_df["day"].astype(str),
        errors="coerce"
    )
    clean_df["start_at"] = final_start_at.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    logger.debug(f"[{prefecture}] Fiscal calendar synchronization applied to datetime features")

    # 依據 ranks_setup 提取受審段位
    if rank_source_column not in clean_df.columns:
        logger.warning(f"[{prefecture}] Rank extraction bypassed: Source column '{rank_source_column}' not found in DataFrame")
    else:
        ranks_str_extractor = partial(extract_ranks_by_regexs, regexs=ranks_text_regexs)
        ranks_parser = partial(parse_ranks_semantic, parse_type=ranks_parse_type)
        clean_df["ranks"]  = (
            clean_df[rank_source_column]
                .pipe(lambda s: s.apply(clean_empty_and_type))
                .pipe(lambda s: s.apply(ranks_str_extractor))
                .pipe(lambda s: s.apply(ranks_parser))
        )
        logger.debug(f"[{prefecture}] Rank semantic parsing completed using regex pattern matching")

    # 預留欄位賦值
    clean_df["type"] = 1
    clean_df["candidate_type"] = 1
    clean_df["delivery_method_type"] = 1

    # 依據 note_columns_map 產生 note 欄位資料
    if "note" not in clean_df.columns:
        clean_df["note"] = ""

    clean_df["note"] = clean_df["note"].fillna("").astype(str).str.strip()
    valid_note_cols = [col for col in note_columns_map.keys() if col in raw_df.columns]

    if not valid_note_cols:
        logger.debug(f"[{prefecture}] Custom metadata note skipped: No mapped notes columns found in config")
    else:
        for col in valid_note_cols:
            # 建立 "標籤: 數值" 陣列
            label = note_columns_map[col]
            formatted_cell = np.where(
                clean_df[col] != "",
                f"{label}: " + clean_df[col].astype(str),
                ""
            )

            clean_df["note"] = np.where(
                (clean_df["note"] != "") & (formatted_cell != ""),
                clean_df["note"] + " | " + formatted_cell,
                clean_df["note"] + formatted_cell
            )

        logger.debug(f"[{prefecture}] Dynamic note field concatenation completed for columns: {valid_note_cols}")

    # =====================================================================
    # Final Phase: 輸出 shinsa 資料成 csv
    # =====================================================================
    final_headers = [
        "name", "type", "location", "start_at", "candidate_type", 
        "delivery_method_type", "note", "federation_name", "ranks",
        "file_name", "url_hash"
    ]

    if clean_df.columns.duplicated().any():
        duplicated_columns_list = clean_df.columns[clean_df.columns.duplicated()].unique().tolist()
        logger.warning(f"Memory alignment conflict! Duplicate column elements tracked: {duplicated_columns_list}")

        # 保留第一個欄位，丟棄後續的同名欄位
        clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()]
        logger.info("Successfully pruned duplicated memory columns by keeping the first occurrence.")
    else:
        logger.info("DataFrame schema structural verification passed. No duplicate columns found.")

    clean_df = clean_df.reset_index(drop=True)

    missing_headers = [col for col in final_headers if col not in clean_df.columns]
    if missing_headers:
        logger.warning(f"Expected schema headers missing from source: {missing_headers}. Initializing with NaN.")

    try:
        clean_df = clean_df.reindex(columns=final_headers)
        logger.info("DataFrame successfully aligned to final shinsa schema layout.")
    except Exception as e:
        logger.exception("Fatal crash on reindex even after explicit metadata deduplication.")
        raise e

    # 組成輸出資料夾和檔名
    file_name = f"{current_year}_{prefecture}_shinsas.csv"
    output_csv_path = output_dir / file_name
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug(f"[{prefecture}] Writing transformed dataset to disk: '{output_csv_path}'")
    clean_df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")

    logger.info(f"[{prefecture}] Transformation pipeline finished | Generated {len(clean_df)} standardized records | Output file: '{output_csv_path.resolve()}'")


if __name__ == "__main__":
    # 局部除錯
    config_helper.setup_global_logger(log_dir="logs", screen_level="DEBUG")
    debug_target = "chiba"
    logger.info(f"Local debug mode | Executing pdf_extractor.py independently for: {debug_target}")

    transform_raw_data(prefecture=debug_target)
