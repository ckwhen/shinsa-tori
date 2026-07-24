import sys
import os
import yaml

from loguru import logger

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CURRENT_DIR, "config.yaml")

_GLOBAL_CONFIG = None

def load_config() -> dict:
    """
    全域基礎函數：
    讀取 config.yaml 檔案，支援 YAML 錨點與全域參數共享。
    """
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is not None:
        return _GLOBAL_CONFIG

    logger.info(f"Initializing and loading centralized config file from: {CONFIG_PATH}")

    if not os.path.exists(CONFIG_PATH):
        logger.critical(f"Infrastructure file recovery failed: '{CONFIG_PATH}' target missing.")
        raise FileNotFoundError(f"Critical configuration file missing at: {CONFIG_PATH}")

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _GLOBAL_CONFIG = yaml.safe_load(f) or {}

        logger.info("Global configuration instance cached successfully in memory.")
        return _GLOBAL_CONFIG
    except Exception as e:
        logger.exception("Failed to parse configuration yaml file structure.")
        raise e

def load_config_by_prefecture(name: str) -> dict:
    """
    縣市特化函數：
    讀取指定設定檔，並提取特定縣市（如 chiba, tokyo）的獨立配置區塊。
    """
    config = load_config()
    prefecture_config = config.get(name)

    if not prefecture_config:
        logger.error(f"Configuration block missing: Prefecture section '{name}' not found")
        raise KeyError(f"Target prefecture configuration block not found: {name}")
    
    logger.debug(f"Prefecture configuration block successfully extracted: '{name}'")
    return prefecture_config

def validate_and_format_prefecture(name: str) -> str:
    """
    全域共用防禦函數：
    執行去頭尾空格、轉換小寫的標準化流程，並驗證 config.yaml 與縣市設定區塊存在性。
    """
    if not name or not isinstance(name, str) or name.strip() == "":
        logger.error("Argument validation failed: Input prefecture name is empty or not a string")
        raise ValueError("Prefecture name argument cannot be empty or non-string")

    clean_name = name.strip().lower()

    try:
        config = load_config()

        if clean_name not in config:
            logger.error(f"Configuration profile missing: '{clean_name}' block not found in configs/config.yaml")
            raise KeyError(f"Prefecture profile section '{clean_name}' is undefined in configuration")
            
    except FileNotFoundError:
        logger.critical("Infrastructure error: Critical file 'config.yaml' not found in project root")
        raise e
    except Exception as e:
        logger.exception(f"Configuration read error: Failed to parse config.yaml due to unexpected exception")
        raise e

    logger.debug(f"Prefecture parameter sanitized and verified: '{clean_name}'")
    return clean_name
