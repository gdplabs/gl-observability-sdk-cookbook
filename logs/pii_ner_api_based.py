import logging
from gl_observability.logs.ner_pii_logger_handler import init_ner_pii_logging_handler
from dotenv import load_dotenv
import os

load_dotenv()

api_url = os.getenv("NER_API_URL")

logger_name = "pii_ner_api_logger"

init_ner_pii_logging_handler(
    logger_name=logger_name,
    api_url=api_url,
    api_field="text",
    pii_ner_process_enabled=True
)

logger = logging.getLogger(logger_name)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

logger.info("This is a test log with PII: john.doe@example.com and 081812345678")
logger.info("Another test log with PII: jane.smith@example.com and 0818876543210")