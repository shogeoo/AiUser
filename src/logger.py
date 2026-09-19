"""Console and file logging setup with per-level colors."""

import logging
import os
from datetime import datetime


class ColorFormatter(logging.Formatter):
    """Formatter that wraps each log line in ANSI color based on its level."""

    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    BASE_FORMAT = "[%(levelname)s %(asctime)s] %(name)s: %(message)s"

    def __init__(self, datefmt="%Y-%m-%d %H:%M:%S"):
        super().__init__()
        self.datefmt = datefmt
        self.FORMATS = {
            logging.INFO: self.GREEN + self.BASE_FORMAT + self.RESET,
            logging.WARNING: self.YELLOW + self.BASE_FORMAT + self.RESET,
            logging.ERROR: self.RED + self.BASE_FORMAT + self.RESET,
            logging.CRITICAL: self.BOLD_RED + self.BASE_FORMAT + self.RESET,
        }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.BASE_FORMAT)
        formatter = logging.Formatter(log_fmt, datefmt=self.datefmt)
        return formatter.format(record)


def configure_logging():
    """Configure the root logger with console, session and dated file handlers."""
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColorFormatter())
    root_logger.addHandler(console_handler)

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    file_formatter = logging.Formatter("[%(levelname)s %(asctime)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    latest_log_path = os.path.join(log_dir, "latest.log")
    session_handler = logging.FileHandler(latest_log_path, mode="w", encoding="utf-8")
    session_handler.setFormatter(file_formatter)
    root_logger.addHandler(session_handler)

    daily_log_path = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
    daily_handler = logging.FileHandler(daily_log_path, mode="a", encoding="utf-8")
    daily_handler.setFormatter(file_formatter)
    root_logger.addHandler(daily_handler)

    root_logger.info("Logging configured. Session started.")


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)
