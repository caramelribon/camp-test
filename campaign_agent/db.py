import hashlib
import json
import logging
import mysql.connector
from campaign_agent.config import DB_CONFIG

logger = logging.getLogger(__name__)


def _get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def get_payment_methods(service_name: str | None = None) -> list[dict]:
    conn = _get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if service_name:
            cursor.execute(
                "SELECT id, type, name, point_id, campaign_list_url FROM payment_methods WHERE name = %s AND campaign_list_url IS NOT NULL",
                (service_name,),
            )
        else:
            cursor.execute(
                "SELECT id, type, name, point_id, campaign_list_url FROM payment_methods WHERE campaign_list_url IS NOT NULL"
            )
        return cursor.fetchall()
    finally:
        conn.close()


def get_existing_campaign_urls(point_id: int) -> list[str]:
    """Return all detail_urls for the given point_id."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT detail_url FROM campaigns WHERE point_id = %s",
            (point_id,),
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _compute_content_hash(title, period_text, reward_rate_text, entry_required, target_stores=None):
    content = f"{title}|{period_text}|{reward_rate_text}|{entry_required}|{target_stores}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def upsert_campaign(data: dict) -> int | None:
    """Upsert a campaign record. Skips update if content_hash is unchanged.

    Returns the campaign id, or None if skipped.
    """
    content_hash = _compute_content_hash(
        data.get("title", ""),
        data.get("period_text"),
        data.get("reward_rate_text"),
        data.get("entry_required"),
        data.get("target_stores"),
    )

    conn = _get_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        # Check existing record
        cursor.execute(
            "SELECT id, content_hash, is_show FROM campaigns WHERE detail_url = %s",
            (data["detail_url"],),
        )
        existing = cursor.fetchone()

        if existing and existing["content_hash"] == content_hash:
            # Even if content is unchanged, ensure is_show=TRUE (restore hidden campaigns)
            if not existing.get("is_show"):
                cursor.execute(
                    "UPDATE campaigns SET is_show = TRUE WHERE id = %s",
                    (existing["id"],),
                )
                conn.commit()
                logger.info("Restored (is_show=TRUE): %s", data["detail_url"])
            else:
                logger.info("Skipped (unchanged): %s", data["detail_url"])
            return existing["id"]

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO campaigns
                (point_id, title, period_text, reward_rate_text,
                 entry_required, target_stores, detail_url, source_list_url,
                 is_show, is_validated, content_hash)
            VALUES
                (%(point_id)s, %(title)s, %(period_text)s, %(reward_rate_text)s,
                 %(entry_required)s, %(target_stores)s, %(detail_url)s, %(source_list_url)s,
                 TRUE, %(is_validated)s, %(content_hash)s)
            ON DUPLICATE KEY UPDATE
                point_id = VALUES(point_id),
                title = VALUES(title),
                period_text = VALUES(period_text),
                reward_rate_text = VALUES(reward_rate_text),
                entry_required = VALUES(entry_required),
                target_stores = VALUES(target_stores),
                source_list_url = VALUES(source_list_url),
                is_show = TRUE,
                is_validated = VALUES(is_validated),
                content_hash = VALUES(content_hash)
            """,
            {
                "point_id": data["point_id"],
                "title": data.get("title", ""),
                "period_text": data.get("period_text"),
                "reward_rate_text": data.get("reward_rate_text"),
                "entry_required": data.get("entry_required"),
                "target_stores": data.get("target_stores"),
                "detail_url": data["detail_url"],
                "source_list_url": data.get("source_list_url"),
                "is_validated": data.get("is_validated"),
                "content_hash": content_hash,
            },
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def hide_unseen_campaigns(point_id: int, seen_urls: set[str]) -> int:
    """Set is_show=FALSE for campaigns not in seen_urls. Returns count of hidden campaigns."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        if seen_urls:
            placeholders = ", ".join(["%s"] * len(seen_urls))
            cursor.execute(
                f"UPDATE campaigns SET is_show = FALSE "
                f"WHERE point_id = %s AND is_show = TRUE AND detail_url NOT IN ({placeholders})",
                [point_id] + list(seen_urls),
            )
        else:
            # No URLs seen — hide all campaigns for this point
            cursor.execute(
                "UPDATE campaigns SET is_show = FALSE WHERE point_id = %s AND is_show = TRUE",
                (point_id,),
            )
        conn.commit()
        hidden_count = cursor.rowcount
        if hidden_count > 0:
            logger.info("Hidden %d campaigns for point_id=%s", hidden_count, point_id)
        return hidden_count
    finally:
        conn.close()


def insert_crawl_log(log_data: dict) -> int:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO crawl_logs
                (execution_id, url, label, detail_score, list_score,
                 not_campaign_score, is_detail_saveable, used_llm,
                 confidence_type, reason, campaign_id, error_message)
            VALUES
                (%(execution_id)s, %(url)s, %(label)s, %(detail_score)s,
                 %(list_score)s, %(not_campaign_score)s, %(is_detail_saveable)s,
                 %(used_llm)s, %(confidence_type)s, %(reason)s,
                 %(campaign_id)s, %(error_message)s)
            """,
            {
                "execution_id": log_data["execution_id"],
                "url": log_data["url"],
                "label": log_data["label"],
                "detail_score": log_data.get("detail_score"),
                "list_score": log_data.get("list_score"),
                "not_campaign_score": log_data.get("not_campaign_score"),
                "is_detail_saveable": log_data.get("is_detail_saveable"),
                "used_llm": log_data.get("used_llm", False),
                "confidence_type": log_data.get("confidence_type"),
                "reason": log_data.get("reason"),
                "campaign_id": log_data.get("campaign_id"),
                "error_message": log_data.get("error_message"),
            },
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def create_execution_run(
    execution_id: str, service_name: str, seed_urls: list[str]
) -> None:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO execution_runs (id, service_name, seed_urls)
            VALUES (%s, %s, %s)
            """,
            (execution_id, service_name, json.dumps(seed_urls, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_campaigns(service_name: str | None = None) -> list[dict]:
    """Fetch campaigns from DB, optionally filtered by service_name."""
    conn = _get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if service_name:
            cursor.execute(
                """
                SELECT c.id, c.point_id, c.title, c.period_text,
                       c.reward_rate_text, c.entry_required,
                       c.target_stores, c.detail_url, c.source_list_url,
                       c.is_show, pm.name AS service_name
                FROM campaigns c
                LEFT JOIN payment_methods pm ON c.point_id = pm.point_id
                WHERE pm.name = %s
                  AND c.reward_rate_text IS NOT NULL
                  AND c.is_show = TRUE
                ORDER BY c.id
                """,
                (service_name,),
            )
        else:
            cursor.execute(
                """
                SELECT c.id, c.point_id, c.title, c.period_text,
                       c.reward_rate_text, c.entry_required,
                       c.target_stores, c.detail_url, c.source_list_url,
                       c.is_show, pm.name AS service_name
                FROM campaigns c
                LEFT JOIN payment_methods pm ON c.point_id = pm.point_id
                WHERE c.reward_rate_text IS NOT NULL
                  AND c.is_show = TRUE
                ORDER BY c.id
                """
            )
        return cursor.fetchall()
    finally:
        conn.close()


def update_execution_run(execution_id: str, **kwargs) -> None:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        set_clauses = []
        params = []
        for key in ("status", "total_urls", "processed_urls", "saved_campaigns", "errors"):
            if key in kwargs:
                set_clauses.append(f"{key} = %s")
                params.append(kwargs[key])
        if "status" in kwargs and kwargs["status"] in ("completed", "failed"):
            set_clauses.append("finished_at = NOW()")
        if set_clauses:
            params.append(execution_id)
            cursor.execute(
                f"UPDATE execution_runs SET {', '.join(set_clauses)} WHERE id = %s",
                params,
            )
            conn.commit()
    finally:
        conn.close()
