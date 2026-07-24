import sys
import os

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