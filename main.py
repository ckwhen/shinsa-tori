import sys

from loguru import logger
from configs.config_helper import validate_and_format_prefecture
from shared.log_helper import setup_global_logger
from pdf_extractor import extract_pdf_tables
from raw_data_transformer import transform_raw_data
from clean_data_loader import load_all_clean_data

PREFECTURES = ["chiba", "fukuoka", "hokkaido"]
LOG_DIR = "logs"

def run_single_prefecture(target_prefecture: str):
    """執行單一縣市的核心流水線"""
    logger.debug(f"[{target_prefecture}] Initiating pdf extraction")
    extract_pdf_tables(prefecture=target_prefecture)

    logger.debug(f"[{target_prefecture}] Initiating raw data transformation and fuzzy matching")
    transform_raw_data(prefecture=target_prefecture)

    logger.debug(f"[{target_prefecture}] Initiating database loading")
    load_all_clean_data()

def run_pipeline():
    # 引數檢查
    if len(sys.argv) < 2:
        sys.stderr.write("Error: Missing target prefecture. Usage: python main.py <prefecture_name> [--debug] or [--all]\n")
        sys.exit(1)

    # 解析除錯參數 (--debug)
    is_debug = "--debug" in sys.argv
    if is_debug:
        sys.argv.remove("--debug")
    screen_level = "DEBUG" if is_debug else "INFO"

    # 解析是否為全縣市模式 (--all)
    is_all_mode = "--all" in sys.argv
    if is_all_mode:
        sys.argv.remove("--all")

    setup_global_logger(log_dir=LOG_DIR, screen_level=screen_level)

    logger.info(f"Pipeline started in {'BATCH' if is_all_mode else 'SINGLE'} mode")

    tasks = PREFECTURES if is_all_mode else []
    if not is_all_mode:
        try:
            raw_input_prefecture = sys.argv[1] 
            target = validate_and_format_prefecture(raw_input_prefecture)
            tasks = [target]
        except Exception as e:
            logger.error(f"Argument parsing failed: {str(e)}")
            sys.exit(1)

    logger.info(f"Loaded {len(tasks)} tasks to execute")

    success_list = []
    failed_list = []

    for index, pref in enumerate(tasks, 1):
        logger.info(f"Progress: {index}/{len(tasks)} | Processing prefecture: {pref}")
        try:
            run_single_prefecture(target_prefecture=pref)
            logger.info(f"Progress: {index}/{len(tasks)} | Prefecture {pref} completed successfully")
            success_list.append(pref)
        except Exception as e:
            logger.exception(f"Progress: {index}/{len(tasks)} | Prefecture {pref} failed during execution")
            failed_list.append(pref)
            
            if not is_all_mode:
                logger.critical("Pipeline execution aborted due to single task failure")
                sys.exit(1)
            logger.warning(f"Pipeline continues, isolated failure for prefecture: {pref}")

    # 最終摘要匯報
    logger.info(f"Pipeline summary | Total: {len(tasks)} | Success: {len(success_list)} | Failed: {len(failed_list)}")
    if failed_list:
        logger.error(f"Failed prefectures: {', '.join(failed_list)}")

if __name__ == "__main__":
    run_pipeline()