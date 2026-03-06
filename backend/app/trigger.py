from __future__ import annotations
import logging
from app.db import get_client

logger = logging.getLogger(__name__)


def process_completed_group_buys() -> list[dict]:
    """
    Find all pending group_buys where current_tokens >= target_tokens,
    set them to 'active', log the purchase intent, and return updated rows.
    """
    client = get_client()

    pending = (
        client.table("group_buys")
        .select("*")
        .eq("status", "pending")
        .execute()
        .data
    )

    triggered = []
    for row in pending:
        if (row.get("current_tokens") or 0) >= row["target_tokens"]:
            updated = (
                client.table("group_buys")
                .update({"status": "active"})
                .eq("id", row["id"])
                .execute()
                .data[0]
            )
            _execute_purchase(updated)
            triggered.append(updated)

    return triggered


def _execute_purchase(group_buy: dict) -> None:
    """
    Placeholder for the actual token purchase job.
    Logs the intent; real payment integration goes here later.
    """
    logger.info(
        "PURCHASE TRIGGERED | group_buy_id=%s name=%s tokens=%s provider=%s",
        group_buy["id"],
        group_buy["name"],
        group_buy["target_tokens"],
        group_buy["provider"],
    )
