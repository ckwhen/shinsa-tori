import sys
import csv
import pdfplumber
import config_helper

from pathlib import Path

def stream_pdf_rows(pdf):
    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue
            
        for t_idx, table in enumerate(tables, start=1):
            for r_idx, row in enumerate(table, start=1):
                # 用 yield 把每一列的資訊打包丟出去
                yield page_num, t_idx, r_idx, row

def extract_pdf_tables(prefecture):
    """
    📥 [Extract 階段 - 第二步: Extractor]
    暴力拆解 PDF 中的網格線條，將其降維打擊成結構化的 col_0 ~ col_9 原始矩陣。
    """
    print(f"🕵️‍♂️ [Extract - Extractor] 正在啟動 [{prefecture}] 任務的表格抽取...")

    # 透過共用 utils 讀取設定
    try:
        pref_config = config_helper.load_config_by_prefecture(
            config_path="config.yaml",
            prefecture=prefecture
        )
        extract_settings = pref_config.get("extract", {})
    except Exception as e:
        print(f"❌ Extractor 初始化設定失敗: {e}")
        return

    # 定義輸入與輸出路徑
    input_dir = Path(extract_settings.get("download_folder", "./shinsa_tori/downloads"))
    pdf_dir = input_dir / "full"
    
    # 讀取編碼設定
    encoding_choice = (
        "utf-8-sig" if extract_settings.get("excel_compatible", True) else "utf-8"
    )

    if not pdf_dir.exists():
        print(f"❌ 錯誤：找不到原始 PDF 目錄 [{pdf_dir}]，請先執行 Spider。")
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))
    print(f"📂 來源目錄: {pdf_dir}")
    print(f"📂 尋找到 {len(pdf_files)} 個 PDF，開始全自動網格線橫向榨取...")

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
        # 拆解 Spider 留下的帶年份與雜湊的漂亮檔名 (2026_chiba_14fd0e2d31.pdf)
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

            print(f"✅ 成功榨出表格: {pdf_path.name}")

        except Exception as e:
            print(f"⚠️ 檔案 [{pdf_path.name}] 無法提取網格表格，已跳過: {e}")
            continue

        # RAW CSV 初始設定
        raw_table_path = Path(
            extract_settings.get(
                "raw_table_path", 
                f"./shinsa_tori/downloads/{file_year}_{prefecture}_raw.csv"
            )
        )
        raw_table_path.parent.mkdir(parents=True, exist_ok=True)

        # 準備寫入 RAW CSV
        with open(raw_table_path, mode="w", encoding=encoding_choice, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            writer.writerows(raw_pdf_items)

    print("\n==================================================")
    print(f"🎉 成果回報 | 階段 1 (Extract) 之 Extractor 任務成功！")
    print(f"📊 共計從 PDF 抽取並還原了 {total_tables_extracted} 個實體表格。")
    print(f"💾 結構化中繼 Staging 檔已落地 ➔ {raw_table_path.resolve()}")
    print("==================================================")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\n❌ 啟動失敗：執行時必須在後方指定縣市代號！")
        print("💡 正確執行範例： python pdf_extractor.py chiba")
        sys.exit(1)

    target_prefecture = config_helper.validate_and_format_prefecture(sys.argv[1])

    print(f"\n🎯 [工作流啟動] 已成功鎖定標準目標縣市: {target_prefecture}")

    extract_pdf_tables(prefecture=target_prefecture)
