import sys
import os
import yaml

def load_config(config_path="config.yaml"):
    """
    [全域基礎函數] 
    單純讀取整個 config.yaml，不限制特定縣市。
    支援全域參數（如 database, shared_paths）與 Loader 模組讀取。
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"❌ 找不到設定檔：{config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        # 使用 FullLoader 以支援 YAML 錨點與引用
        config = yaml.load(f, Loader=yaml.FullLoader)
        
    return config if config else {}

def load_config_by_prefecture(config_path="config.yaml", prefecture="chiba"):
    """
    [縣市特化函數] 
    讀取 config.yaml 並專門取得指定縣市（如 chiba, tokyo）的獨立區塊設定。
    適用於 Extractor 與 Transformer 階段。
    """
    # 呼叫基礎函數取得完整的 config 字典
    config = load_config(config_path)

    prefecture_config = config.get(prefecture)

    if not prefecture_config:
        raise KeyError(
            f"❌ 在 {config_path} 中找不到該縣市的設定區塊: {prefecture}"
        )

    return prefecture_config

def validate_and_format_prefecture(name):
    """
    [全域共用防禦函數]
    嚴格驗證縣市引數是否合法，並自動執行去頭尾空格、轉換小寫的標準化流程。
    若驗證失敗，印出紅牌警告並中止 Python 行程。
    """

    if not name or not isinstance(name, str) or name.strip() == "":
        print("\n❌ 啟動失敗：必須指定明確的縣市代號文字（例如 'chiba'）！")
        sys.exit(1)

    clean_name = name.strip().lower()
    
    # 規格進階防禦：檢查 config.yaml 是否存在，且裡面有沒有這個縣市的設定
    try:
        # 借用現有的全域配置函數，確認檔案存在
        config = load_config("config.yaml")
        
        # 檢查 config 的第一層有沒有這個縣市的 Key
        if clean_name not in config:
            print(f"\n❌ 規格錯誤：雖然 config.yaml 存在，但設定檔中找不到 [{clean_name}] 這個縣市的配置區塊！")
            sys.exit(1)
            
    except FileNotFoundError:
        print("\n❌ 災難錯誤：在專案根目錄找不到關鍵的 [config.yaml] 設定檔，請先建立它！")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 設定檔讀取發生未知錯誤: {e}")
        sys.exit(1)

    return clean_name
