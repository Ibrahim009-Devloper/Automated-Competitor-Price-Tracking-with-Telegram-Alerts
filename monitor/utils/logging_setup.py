"""Logging configuration with console output, rotating file handler, and secret masking."""

import logging
from logging.handlers import RotatingFileHandler
import os
import re
from typing import Optional


class SecretMaskingFilter(logging.Filter):
    """Logging filter that redacts database credentials and Telegram tokens from log outputs.

    Ensures that secrets and credentials never appear in console streams or rotated log files.
    """

    # 1. Database URLs containing passwords (e.g. postgresql://user:password@host)
    DB_URL_PATTERN = re.compile(
        r'((?:postgres|postgresql|mysql|sqlite)://[^:/@\s]+:)([^@\s]+)(@)',
        re.IGNORECASE,
    )

    # 2. Telegram Bot tokens (e.g. 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_1234567)
    TELEGRAM_TOKEN_PATTERN = re.compile(r'\b\d{8,12}:[A-Za-z0-9_-]{30,45}\b')

    # 3. Explicit password and secret query parameters
    PASSWORD_PARAM_PATTERN = re.compile(
        r'((?:password|passwd|pwd|secret)=)[^&\s]+',
        re.IGNORECASE,
    )

    @classmethod
    def mask_text(cls, text: str) -> str:
        """Sanitize text by replacing sensitive substrings with asterisks."""
        if not text:
            return text

        # Mask database URL passwords
        masked = cls.DB_URL_PATTERN.sub(r'\1*****\3', text)

        # Mask Telegram bot tokens
        masked = cls.TELEGRAM_TOKEN_PATTERN.sub(r'*****:*****', masked)

        # Mask key-value password assignments
        masked = cls.PASSWORD_PARAM_PATTERN.sub(r'\1*****', masked)

        # Mask specific environment variable values if set
        for env_var in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN"):
            val = os.getenv(env_var)
            if val and len(val) >= 5:
                # If exact raw URL is present and was not masked by regex above
                masked = masked.replace(val, "*****")
                # Also check if password within DATABASE_URL can be extracted and masked
                if env_var == "DATABASE_URL":
                    try:
                        from monitor.storage import mask_database_url
                        safe_url = mask_database_url(val)
                        if safe_url != val:
                            masked = masked.replace(val, safe_url)
                    except Exception:
                        pass

        return masked

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record in-place by masking message and formatted arguments."""
        if isinstance(record.msg, str):
            record.msg = self.mask_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self.mask_text(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.mask_text(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )

        return True


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_filename: str = "monitor.log",
) -> logging.Logger:
    """Configure root logger with console and rotating file outputs with secret masking.

    Rotates files when they reach 1 MB, keeping up to 5 backups.

    Args:
        log_level: Logging level string ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        log_dir: Directory to save log files (default: 'logs').
        log_filename: Name of the log file (default: 'monitor.log').

    Returns:
        The configured root logger.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if root_logger.handlers:
        return root_logger

    masking_filter = SecretMaskingFilter()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(masking_filter)
    root_logger.addHandler(console_handler)

    # 2. Rotating file handler (1 MB = 1,000,000 bytes, max 5 files)
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_filepath = os.path.join(log_dir, log_filename)
        file_handler = RotatingFileHandler(
            filename=log_filepath,
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(masking_filter)
        root_logger.addHandler(file_handler)
    except OSError as err:
        root_logger.warning("Could not set up file logging in '%s': %s", log_dir, err)

    return root_logger
