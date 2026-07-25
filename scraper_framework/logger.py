"""统一日志配置"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional


class LoggerManager:
    _loggers = {}
    _initialized = False

    @classmethod
    def setup_logging(cls, log_dir: str = "logs"):
        if cls._initialized:
            return
        Path(log_dir).mkdir(exist_ok=True)
        cls._initialized = True

    @classmethod
    def get_logger(cls, name: str, module_type: Optional[str] = None) -> logging.Logger:
        cls.setup_logging()

        if name in cls._loggers:
            return cls._loggers[name]

        if module_type is None:
            if "spider" in name.lower():
                module_type = "spiders"
            else:
                module_type = "general"

        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)

        if logger.handlers:
            cls._loggers[name] = logger
            return logger

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logger.propagate = False

        log_file = Path(f"logs/{module_type}.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=50 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        cls._loggers[name] = logger
        return logger


def get_logger(name: str) -> logging.Logger:
    return LoggerManager.get_logger(name)


def get_spider_logger(name: str) -> logging.Logger:
    return LoggerManager.get_logger(f"spider.{name}", "spiders")
