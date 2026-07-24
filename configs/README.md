# SHINSA TORI 管理設定檔

本資料夾為管理中央系統配置、ETL 管線、以及 Spider 爬蟲運作所需要的參數設定說明

---

## 目錄
- [1. 全域與縣市配置說明](#1-全域與縣市配置說明)
  - [全域共享區塊 (global)](#全域共享區塊-global)
  - [縣市特化區塊](#縣市特化區塊)
- [2. 設定範例](#2-設定範例)

## 1. 全域與縣市配置說明

### 全域共享區塊 (global)
主要提供給 47 個縣市任務進行繼承與對齊的通用參數，內部採用 YAML 錨點機制

| Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `input_folder` | String | `shinsa_tori/downloads` | `spider`與`extractor`的儲存位置 |
| `output_folder` | String | `shinsa_tori/outputs` | `transformer` 清洗後的儲存位置 |

### 縣市特化區塊
每個縣市皆為獨立的頂層任務鍵值（如 `tokyo:`）。各縣市可利用星號 (`*`) 直接繼承 `global` 的路徑設定，並宣告特化的執行邏輯

| Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `federation_name` | String | 無 | 為該縣市的弓道連盟日文名稱 |
| `extract` | Dictionary | 參閱下方 `Extract 子配置說明` | 將 `spider` 下載下來的檔案提取成初步的 `*_raw.csv` |
| `transform` | Dictionary | 參閱下方 `Transform 子配置說明` | 將 `*_raw.csv` 清洗成符合 Database 的資料格式 `*_shinsas.csv` |

---

#### Extract 子配置說明 (`extract:`)
定義 Spiders 在抽取目標網頁時的防禦參數、URL 進入點以及 HTML/PDF 的解析特化規則。

| Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `download_folder` | String | `*base_input` | 目標連盟的審查 HTML/PDF 檔案下載進入點 |

---

#### Transform 子配置說明 (`transform:`)
定義清理管線在將 `*_raw.csv` 轉化為標準化落盤數據時的校準規則與安全熔斷表。

| Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `input_folder`| String | `*base_input` | 繼承自 `global`，指定原始 `*_raw.csv` 檔案的輸入目錄 |
| `output_folder` | String | `*base_output` | 繼承自 `global`，指定清洗後 `*_shinsas.csv` 檔案的輸出目錄 |
| `allow_keywords` | List | `[]` | 白名單防禦：包含列表中的關鍵字（如：審査），會保留該筆資料 |
| `ignore_keywords` | List | `[]` | 黑名單防禦：若包含列表中的過濾關鍵字（如：取消、延期），該筆資料將被剔除 |
| `ffill_columns` | List | `[]` | 前向/向下填充欄位：指定需要執行 `Pandas .ffill()` 的欄位（如日期、地點），用以補齊跨行合併（Rowspan）產生的缺失值 |
| `shinsa_columns_map` | Dictionary | `{}` | 欄位對齊映射表：將網頁解析出的多變欄位名稱（如 "日時", "場所"）重新命名對齊為資料庫標準欄位 |
| `ranks_setup` | Dictionary | `{}` | 段位解析子配置：特殊複雜欄位型態，用於提取、拆分與過濾審查的段位與級位規格，詳細配置見下表 |

#### Transform - ranks_setup 配置說明
專注於解析網頁或 PDF 中結構複雜的「審査段位/級位」字串（例如從 "五段・六段・七段" 中動態提取出獨立的級別清單）。

| Name | Type | Default | Options | Description |
| :--- | :--- | :--- | :--- | :--- |
| `source_column`| String | 無 | 無 | 指定要交由正規表示式（Regex）提取段位資訊的目標欄位名稱（如：ranks_str）。 |
| `parse_type` | String | 無 | `peer_to_peer`: 點對點直接映射。將字串直接比對並轉化為單一或獨立列表。<br>`range`: 區間展開模式。識別起迄符號（如 〜, -），將「初段〜三段」自動向量化展開為 ['初段', '二段', '三段']。<br>`hybrid`: 混合模式。同時支援點對點與區間展開的複合字串（如：「初段・三段〜五段」）。 | 核心解析策略分支，必須指定為 `Options` 3 種模式之一 |
| `text_regexs` | List | `[]` | 無 | 內容為正則表達式字串，用以對審查種別作初步的擷取和過濾 |

## 2. 設定範例

### 全域共享區塊 (global)

```yaml
global:
  input_folder: &base_input "./shinsa_tori/downloads"
  output_folder: &base_output "./shinsa_tori/outputs"
```

### 縣市特化區塊

```yaml
fukuoka:
  federation_name: "福岡県弓道連盟"
  extract:
    download_folder: *base_input

  transform:
    input_folder: *base_input
    output_folder: *base_output
    date_extract_type: "split_columns"
    allow_keywords:
      - "地方審査"
    ignore_keywords:
      - "地方審査練習"
    ffill_columns:
      - "col_0"
    shinsa_columns_map:
      col_0: "month"
      col_1: "day"
      col_3: "name"
      col_4: "location"
    ranks_setup:
      source_column: "name"
      parse_type: "range"
      text_regexs:
        - '[\((]?(?P<ranks_text>[^()（）]*[~～〜\-][^()（）]*)[\))]'
```