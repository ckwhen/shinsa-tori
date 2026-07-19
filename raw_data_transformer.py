import sys
import re
import numpy as np
import pandas as pd
import config_helper

from pathlib import Path

EMPTY_CELLS_TOLERANCE = 3
DATE_EXTRACT_REGEX_MAP = {
    # 情況 A: 4月19日 (日)
    "combined_text": r"(?P<month>\d+)\s*月\s*(?P<day>\d+)\s*日.*",
}
RANK_NAMES = ["無指定", "初段", "弐段", "参段", "四段", "五段"]
RANK_ABBREVIATION_MAP = {
    "無": "無指定",
    "初": "初段",
    "弐": "弐段",
    "参": "参段",
    "四": "四段",
    "五": "五段"
}

def parse_ranks_semantic(input: str, parse_type: str) -> str:
    """
    型態 1：點對點條列型 (無指定・初段・参段)
    """
    if not input or pd.isna(input):
        return ""
    
    input = str(input).strip()
    result_set = set()

    # 💡 型態 1：一個蘿蔔一個坑 (無指定・初段・参段)
    if parse_type == "peer_to_peer":
        tokens = re.split(r"[・,、/]", input)
        for t in tokens:
            norm_t = RANK_ABBREVIATION_MAP.get(t, t)

            if len(norm_t) == 1 and norm_t != "無":
                norm_t += "段"
                
            if norm_t in RANK_NAMES:
                result_set.add(norm_t)

    if not result_set:
        return ""
        
    sorted_output = [r for r in RANK_NAMES if r in result_set]

    return " | ".join(sorted_output)

def transform_raw_data(prefecture):
    """
    [Transform 階段]
    讀取 Staging 原始 CSV 矩陣，執行多重欄位特徵清洗與過濾，
    移除重複表頭與多餘雜訊，並依據 YAML 設定檔轉換為標準 ShinsaItem 數據結構。
    """
    print(f"Transform: 正在啟動 [{prefecture}] 任務的 CSV 數據清洗流程...")

    # 設定檔初始化
    try:
        pref_config = config_helper.load_config_by_prefecture(
            config_path="config.yaml",
            prefecture=prefecture
        )
        transform_settings = pref_config.get("transform", {})
    except Exception as e:
        print(f"❌ Transformer 初始化設定失敗: {e}")
        return

    # 定義輸入與輸出路徑
    input_dir = Path(transform_settings.get("input_folder", "./shinsa_tori/downloads"))
    output_dir = Path(transform_settings.get("output_folder", "./shinsa_tori/outputs"))

    if not input_dir.exists():
        print(f"❌ 錯誤：找不到 RAW CSV 目錄 [{input_dir}]，請先執行 Extractor。")
        return

    raw_csv_files = list(input_dir.glob(f"*_{prefecture}_*.csv"))

    if len(raw_csv_files) == 0:
        print(f"❌ 錯誤：在 [{input_dir}] 找不到任何符合 *_{prefecture}_raw.csv 的檔案。")
        return

    print(f"📂 尋找到 {len(raw_csv_files)} 個年份的 CSV 檔案，開始合併載入...")

    # 載入該連盟 RAW CSV
    df_list = [
        pd.read_csv(csv_path, encoding="utf-8-sig", encoding_errors="replace")
        for csv_path in raw_csv_files
    ]
    raw_df = pd.concat(df_list, ignore_index=True)

    # 直接用 [0] 拿出那唯一一個檔案的路徑，徹底消滅迴圈
    csv_path = raw_csv_files[0]

    print(f"📂 來源目錄: {input_dir}")
    print(f"🎯 目標縣市: {prefecture}")
    print(f"📄 鎖定唯一目標檔案，開始資料清洗: {csv_path.name}")

    # =====================================================================
    # Preparation: 讀取 YAML 中的核心設定
    # =====================================================================
    federation_name = pref_config.get("federation_name")
    ignore_keywords = transform_settings.get("ignore_keywords", [])
    ffill_cols = transform_settings.get("ffill_columns", [])
    shinsa_columns_map = transform_settings.get("shinsa_columns_map", {})
    note_columns_map = transform_settings.get("note_columns_map", {})
    ranks_setup = transform_settings.get("ranks_setup", {})
    date_extract_type = transform_settings.get("date_extract_type", "")
    rank_source_column = ranks_setup.get("source_column", "")
    ranks_parse_type = str(ranks_setup.get("parse_type", ""))
    ranks_text_regex = ranks_setup.get("text_regex")

    current_year = csv_path.name.split("_")[0]

    raw_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if raw_df.empty:
        print("⚠️ 原始 CSV 檔案內容為空。")
        return

    # =====================================================================
    # Phase 1: 清除可能的無效資料
    # =====================================================================
    # 取得每列平均有效資料格數，用以清除無效行
    valid_cells_per_row = ((raw_df != "") & raw_df.notna()).sum(axis=1)
    mean_valid_cells = valid_cells_per_row.mean()
    dynamic_threshold = mean_valid_cells - EMPTY_CELLS_TOLERANCE
    raw_df = raw_df[valid_cells_per_row >= dynamic_threshold]

    # 依據 ignore_keywords 移除所有包含 keyword 的列
    is_any_keyword = raw_df.isin(ignore_keywords).any(axis=1)
    raw_df = raw_df[~is_any_keyword]

    if raw_df.empty:
        print("⚠️ 經過 Phase 1 過濾後，已無有效審查日程資料。")
        return

    # =====================================================================
    # Phase 2: 開始清洗 shinsa 所需資料
    # =====================================================================
    clean_df = raw_df.copy()

    # 依據 ffill_columns 填補指定欄位中的 rowspan
    existing_ffill_cols = [col for col in ffill_cols if col in clean_df.columns]
    if not existing_ffill_cols:
        print("⚠️ 警告: YAML 中設定的 ffill_columns 在資料表中皆不存在，跳過填充。")
    else:
        # 將指定欄位中的「空字串」與「純空格」先轉成可以使用 ffill 的 NaN
        for col in existing_ffill_cols:
            clean_df[col] = clean_df[col].replace(r"^\s*$", np.nan, regex=True)

        # 進行向下填補
        clean_df[existing_ffill_cols] = clean_df[existing_ffill_cols].ffill()
        
        # 防呆: 將 NaN 轉回空字串
        clean_df[existing_ffill_cols] = clean_df[existing_ffill_cols].fillna("")
        
        print(f"已成功向下補全合併儲存格欄位: {existing_ffill_cols}")

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

    # 處理月、日拆分
    if date_extract_type == "combined_text":
        regex = DATE_EXTRACT_REGEX_MAP.get("combined_text")
        extracted = clean_df["start_at"].astype(str).str.extract(regex)
        clean_df["month"] = extracted["month"]
        clean_df["day"] = extracted["day"]

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

    # 依據 ranks_setup 提取受審段位
    if rank_source_column not in clean_df.columns:
        print(f"⚠️ 警告: 找不到 YAML 指定的段位來源欄位 [{rank_source_column}]，將跳過段位提取。")
    else:
        extracted_ranks_text = clean_df[rank_source_column].astype(str).str.extract(ranks_text_regex)
        raw_ranks_series = extracted_ranks_text["ranks_text"].fillna("")

        clean_df["ranks"] = raw_ranks_series.apply(lambda x: parse_ranks_semantic(x, ranks_parse_type))

    # TODO: 後續補上審查類型, 受審者類型和審查方式
    clean_df["type"] = 1
    clean_df["candidate_type"] = 1
    clean_df["delivery_method_type"] = 1

    # 依據 note_columns_map 產生 note 欄位資料
    if "note" not in clean_df.columns:
        clean_df["note"] = ""

    clean_df["note"] = clean_df["note"].fillna("").astype(str).str.strip()
    valid_note_cols = [col for col in note_columns_map.keys() if col in raw_df.columns]

    if not valid_note_cols:
        print("⚠️ 提示: YAML 中未設定額外備註欄位，維持原始 note 資料。")
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

    # =====================================================================
    # Final Phase: 輸出 shinsa 資料成 csv
    # =====================================================================
    final_headers = [
        "name", "type", "location", "start_at", "candidate_type", 
        "delivery_method_type", "note", "federation_name", "ranks",
        "file_name", "url_hash"
    ]
    clean_df = clean_df.reindex(columns=final_headers)

    # 組成輸出資料夾和檔名
    file_name = f"{current_year}_{prefecture}_shinsas.csv"
    output_csv_path = output_dir / file_name
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")

    print("\n--------------------------------------------------")
    print(f"Transform 階段成功：檔案更名與數據清洗完畢。")
    print(f"成功過濾無效表頭與雜訊資料，共計產出 {len(clean_df)} 筆標準審查數據。")
    print(f"清洗後的資料已寫入目標路徑：{output_csv_path.resolve()}")
    print("--------------------------------------------------")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\n❌ 啟動失敗：執行時必須在後方指定縣市代號！")
        print("💡 正確執行範例： python raw_data_transformer.py chiba")
        sys.exit(1)

    target_prefecture = config_helper.validate_and_format_prefecture(sys.argv[1])

    print(f"\n🎯 [工作流啟動] 已成功鎖定標準目標縣市: {target_prefecture}")

    transform_raw_data(prefecture=target_prefecture)
