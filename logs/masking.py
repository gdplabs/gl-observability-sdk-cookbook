"""Root logging setup backed by GL Observability."""

import logging
import os

from dotenv import load_dotenv
from gl_observability.logs import LogFormat, LoggingConfig, setup_logging, LogMaskingConfig
from gl_observability import BuiltInMaskingRule
from gllm_core import logging as gllm_core_logging

class NoOpLoggerManager:
    """Stand-in for gllm_core's LoggerManager that delegates to the standard logging hierarchy."""

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Get a logger instance.

        This method returns a logger instance that is a child of the root logger. If name is not provided,
        the root logger will be returned instead.

        Args:
            name (str | None, optional): The name of the child logger. If None, the root logger will be returned.
                Defaults to None.

        Returns:
            logging.Logger: Configured logger instance.
        """
        return logging.getLogger(name) if name else logging.getLogger()

    def set_level(self, level: int) -> None:
        """Set logging level for all loggers in the hierarchy.

        Args:
            level (int): The logging level to set (e.g., logging.INFO, logging.DEBUG).
        """
        logging.getLogger().setLevel(level)


gllm_core_logging.LoggerManager = NoOpLoggerManager

load_dotenv()

def setup_root_logging():
    """Setup root logging configuration."""
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()


    # Must delete the LoggerManager attribute from gllm_core.logging for the masking to work.
    delattr(gllm_core_logging, "LoggerManager")
    try:
        setup_logging(
            config=LoggingConfig(
                log_format=LogFormat(log_format),
                level=log_level,
                masking_config=LogMaskingConfig(
                    rules=(BuiltInMaskingRule.EMAIL,),
                )
            )
        )
    finally:
        gllm_core_logging.LoggerManager = NoOpLoggerManager

setup_root_logging()

logger = logging.getLogger("cookbook")

logger.info("This is an info message")
logger.warning("This message might contain sensitive data in the message, that is: %s", "mail@example.com")
logger.info("This is an info message with extra fields", extra={"user_id": "12345", "session_id": "abcde", "email": "mail_2@example.com"})

def function_with_error():
    try:
        raise ValueError("There is an error when processing email: mail.number.third@example.com")
    except Exception as e:
        logger.exception("An error occurred", exc_info=True)

function_with_error()

