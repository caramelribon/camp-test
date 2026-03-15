"""PersistenceAgent - Save campaign data and crawl logs to DB."""

import logging
from campaign_agent.db import upsert_campaign, insert_crawl_log

logger = logging.getLogger(__name__)


def save_campaign_to_db(
    point_id: int,
    detail_url: str,
    source_list_url: str,
    normalized_data: dict,
) -> dict:
    """Save a campaign record to DB via upsert.

    Returns:
        dict with 'campaign_id' and 'success' keys.
    """
    try:
        campaign_data = {
            "point_id": point_id,
            "detail_url": detail_url,
            "source_list_url": source_list_url,
            "title": normalized_data.get("title") or "",
            "period_text": normalized_data.get("period_text"),
            "reward_rate_text": normalized_data.get("reward_rate_text"),
            "entry_required": normalized_data.get("entry_required"),
            "target_stores": normalized_data.get("target_stores"),
            "is_validated": normalized_data.get("is_validated"),
        }
        campaign_id = upsert_campaign(campaign_data)
        logger.info("Saved campaign: %s (id=%s)", detail_url, campaign_id)
        return {"campaign_id": campaign_id, "success": True}
    except Exception as e:
        logger.error("Failed to save campaign %s: %s", detail_url, e)
        return {"campaign_id": None, "success": False, "error": str(e)}


def save_crawl_log_to_db(
    execution_id: str,
    url: str,
    classification: dict,
    campaign_id: int | None = None,
    error_message: str | None = None,
) -> dict:
    """Save a crawl log entry to DB.

    Returns:
        dict with 'log_id' and 'success' keys.
    """
    try:
        log_data = {
            "execution_id": execution_id,
            "url": url,
            "label": classification.get("label", "uncertain"),
            "detail_score": classification.get("scores", {}).get("campaign_detail"),
            "list_score": classification.get("scores", {}).get("campaign_list"),
            "not_campaign_score": classification.get("scores", {}).get("not_campaign"),
            "is_detail_saveable": classification.get("is_detail_saveable"),
            "used_llm": classification.get("used_llm", False),
            "confidence_type": classification.get("confidence_type"),
            "reason": classification.get("reason"),
            "campaign_id": campaign_id,
            "error_message": error_message,
        }
        log_id = insert_crawl_log(log_data)
        return {"log_id": log_id, "success": True}
    except Exception as e:
        logger.error("Failed to save crawl log for %s: %s", url, e)
        return {"log_id": None, "success": False, "error": str(e)}
