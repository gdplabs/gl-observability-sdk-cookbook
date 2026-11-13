import logging
import os
from gl_observability.logs import LogFormat, LoggingConfig, setup_logging, ContextFieldsFilter
from dotenv import load_dotenv

load_dotenv()

LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def project_name() -> str:
    return "cookbook"

setup_logging(LoggingConfig(
    log_format=LogFormat(LOG_FORMAT),
    level=LOG_LEVEL,
    filters=[ContextFieldsFilter({
        "project_name": project_name,
    })],
))

logger = logging.getLogger("cookbook")

logger.info("This is an info message")
logger.warning("This is a warning message", extra={"user_id": "12345", "session_id": "abcde"})

def function_with_error():
    try:
        1 / 0
    except Exception as e:
        logger.exception("An error occurred", exc_info=True)

function_with_error()

