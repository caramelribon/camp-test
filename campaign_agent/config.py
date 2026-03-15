import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "database": os.getenv("MYSQL_DATABASE", "campaign_db"),
    "user": os.getenv("MYSQL_USER", "campaign_user"),
    "password": os.getenv("MYSQL_PASSWORD", "campaign_pass"),
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
}

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")
VALIDATOR_MODEL_ID = os.getenv("VALIDATOR_MODEL_ID", "gemini-2.5-flash-lite")

# Retry settings
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "1.0"))
