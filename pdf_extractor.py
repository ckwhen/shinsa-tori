import csv
import pdfplumber
import config_helper

from loguru import logger
from pathlib import Path

def stream_pdf_rows(pdf):
    """
    產生器函數：
    橫向榨取 PDF 各頁表格，並自動降維輸出附帶座標（頁碼、表號、行號）的扁平資料流。
    """
    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            # logger.trace(f"Page {page_num} contains no extractable tables")
            continue

        logger.debug(f"Parsing page {page_num}/{len(pdf.pages)} | Found {len(tables)} table(s)")

        for t_idx, table in enumerate(tables, start=1):
            for r_idx, row in enumerate(table, start=1):
                # 用 yield 把每一列的資訊打包丟出去
                yield page_num, t_idx, r_idx, row

def extract_pdf_tables(prefecture):
    """
    Extract 階段：
    解析指定縣市的 PDF 表格，並轉換為結構化的原始矩陣檔案。
    """
    logger.info(f"[{prefecture}] Starting table extraction from PDF files")

    # 讀取設定檔與特化區塊
    try:
        pref_config = config_helper.load_config_by_prefecture(
            config_path="config.yaml",
            prefecture=prefecture
        )
        extract_settings = pref_config.get("extract", {})
    except Exception as e:
        logger.exception(f"[{prefecture}] Extractor initialization failed: Configuration block load error")
        raise e

    # 定義輸入與輸出路徑
    input_dir = Path(extract_settings.get("download_folder", "./shinsa_tori/downloads"))
    pdf_dir = input_dir / "full"
    
    # 讀取編碼設定
    encoding_choice = (
        "utf-8-sig" if extract_settings.get("excel_compatible", True) else "utf-8"
    )

    logger.debug(f"[{prefecture}] Scanning input file directory: '{pdf_dir}'")

    if not pdf_dir.exists():
        logger.error(f"[{prefecture}] Directory error: Target source folder '{pdf_dir}' does not exist")
        raise FileNotFoundError(f"Source PDF directory missing: {pdf_dir}")

    pdf_files = list(pdf_dir.glob(f"*_{prefecture}_*.pdf"))

    logger.info(f"[{prefecture}] Scan completed | Found {len(pdf_files)} PDF files to process")

    # 定義中繼欄位 + 10 個寬度容納列
    csv_headers = [
        "file_year",
        "pref_name",
        "url_hash",
        "file_name",
        "page_number",
        "table_index",
        "row_index"
    ] + [f"col_{i}" for i in range(10)]

    total_tables_extracted = 0

    for pdf_path in pdf_files:
        logger.debug(f"[{prefecture}] Opening file for parsing: '{pdf_path.name}'")

        file_name_without_ext = pdf_path.stem
        parts = file_name_without_ext.split("_")
        
        file_year = parts[0] if len(parts) >= 3 else "9999"
        url_hash = parts[-1] if len(parts) >= 3 else "unknown"
        pref_name = "_".join(parts[1:-1]) if len(parts) >= 3 else file_name_without_ext

        raw_pdf_items = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, t_idx, r_idx, row in stream_pdf_rows(pdf):
                    if r_idx == 1:
                        total_tables_extracted += 1

                    # 清洗格子內碎裂的換行與頭尾空格
                    clean_row = [
                        str(cell).replace("\n", " ").strip() if cell else ""
                        for cell in row
                    ]

                    # 填滿或截斷至 10 碼長度（標準對齊）
                    if len(clean_row) < 10:
                        clean_row += [""] * (10 - len(clean_row))
                    else:
                        clean_row = clean_row[:10]

                    raw_pdf_items.append([
                        file_year,
                        pref_name,
                        url_hash,
                        pdf_path.name,
                        page_num,
                        t_idx,
                        r_idx
                    ] + clean_row)

            logger.info(f"[{prefecture}] Parsed file successfully: '{pdf_path.name}' | Extracted {len(raw_pdf_items)} rows")

        except Exception as e:
            logger.exception(f"[{prefecture}] Skip file | Failed to extract tables from: '{pdf_path.name}'")
            continue

        # RAW CSV 初始設定
        raw_table_path = Path(
            extract_settings.get(
                "raw_table_path", 
                f"./shinsa_tori/downloads/{file_year}_{prefecture}_raw.csv"
            )
        )
        raw_table_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(f"[{prefecture}] Writing records to disk: '{raw_table_path}'")

        with open(raw_table_path, mode="w", encoding=encoding_choice, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            writer.writerows(raw_pdf_items)

    logger.info(f"[{prefecture}] Extraction pipeline finished | Total tables extracted: {total_tables_extracted} | Output file: '{raw_table_path.resolve() if raw_table_path else 'None'}'")

if __name__ == "__main__":
    # 局部除錯
    config_helper.setup_global_logger(log_dir="logs", screen_level="DEBUG")
    debug_target = "chiba"
    logger.info(f"Local debug mode | Executing pdf_extractor.py independently for: {debug_target}")

    extract_pdf_tables(prefecture=debug_target)
