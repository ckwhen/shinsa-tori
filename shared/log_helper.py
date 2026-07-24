import sys
import os

from pathlib import Path
from loguru import logger

def setup_global_logger(log_dir: str = "logs", screen_level: str = "INFO"):
    """全域唯一初始化日誌的入口"""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    logger.remove()

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}:{line}</cyan> - <level>{message}</level>"
    )

    # 終端機彩色輸出
    logger.add(
        sys.stderr,
        level=screen_level,
        format=console_format
    )

    file_format = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}"

    logger.add(
        os.path.join(log_dir, "pipeline_{time:YYYY-MM-DD}.log"), 
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        level="DEBUG",
        format=file_format,
        encoding="utf-8"
    )