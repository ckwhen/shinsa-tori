import sys
import os
import yaml

from pathlib import Path
from loguru import logger

def setup_global_logger(log_dir: str = "logs", screen_level: str = "INFO"):
    """全域唯一初始化日誌的入口"""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    logger.remove()

    # 終端機彩色輸出
    logger.add(
        sys.stderr,
        level=screen_level
    )

    logger.add(
        os.path.join(log_dir, "pipeline_{time:YYYY-MM-DD}.log"), 
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        level="DEBUG"
    )

def load_config(config_path: str) -> dict:
    """
    全域基礎函數：
    讀取 config.yaml 檔案，支援 YAML 錨點與全域參數共享。
    """
    if not os.path.exists(config_path):
        logger.error(f"Configuration infrastructure missing: Target file not found at '{config_path}'")
        raise FileNotFoundError(f"Critical configuration file missing: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
        
    return config if config else {}

def load_config_by_prefecture(config_path: str, prefecture: str) -> dict:
    """
    縣市特化函數：
    讀取指定設定檔，並提取特定縣市（如 chiba, tokyo）的獨立配置區塊。
    """
    config = load_config(config_path)

    prefecture_config = config.get(prefecture)

    if not prefecture_config:
        logger.error(f"Configuration block missing: Prefecture section '{prefecture}' not found in '{config_path}'")
        raise KeyError(f"Target prefecture configuration block not found: {prefecture}")
    
    logger.debug(f"Prefecture configuration block successfully extracted: '{prefecture}' from '{config_path}'")
    return prefecture_config

def validate_and_format_prefecture(name: str) -> str:
    """
    全域共用防禦函數：
    執行去頭尾空格、轉換小寫的標準化流程，並驗證 config.yaml 與縣市設定區塊存在性。
    """
    if not name or not isinstance(name, str) or name.strip() == "":
        logger.error("Argument validation failed: Input prefecture name is empty or not a string")
        sys.exit(1)

    clean_name = name.strip().lower()

    try:
        config = load_config("config.yaml")

        if clean_name not in config:
            logger.error(f"Configuration profile missing: '{clean_name}' block not found in config.yaml")
            sys.exit(1)
            
    except FileNotFoundError:
        logger.critical("Infrastructure error: Critical file 'config.yaml' not found in project root")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Configuration read error: Failed to parse config.yaml due to unexpected exception")
        sys.exit(1)

    logger.debug(f"Prefecture parameter sanitized and verified: '{clean_name}'")
    return clean_name
