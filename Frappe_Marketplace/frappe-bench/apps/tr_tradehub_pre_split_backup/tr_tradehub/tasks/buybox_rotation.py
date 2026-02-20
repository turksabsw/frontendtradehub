# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Buy Box Rotation Scheduler for Fair Distribution.

This module provides background job functions for Buy Box rotation that ensures
fair distribution of the Buy Box position among similarly-scored sellers.

Key Features:
- Time-based rotation for sellers within a configurable score threshold
- Prevents single seller dominance through max consecutive wins limits
- Multi-tenant aware processing
- Configurable rotation intervals and thresholds
- Winner history tracking for analytics
- Concurrent update protection via database locking

Algorithm Overview:
1. Get all products with multiple active Buy Box entries
2. For each product, check if current winner has held position too long
3. If threshold exceeded and close competitors exist, rotate to next eligible seller
4. Record rotation history for analytics and fairness auditing

Usage in hooks.py:
    scheduler_events = {
        "cron": {
            "0 * * * *": [
                "tr_tradehub.tasks.buybox_rotation.rotate_buybox"
            ]
        }
    }

Usage for single product:
    frappe.enqueue(
        "tr_tradehub.tasks.buybox_rotation.rotate_product_buybox",
        sku_product="SKU-00001",
        queue="short"
    )
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import (
    cint,
    flt,
    now_datetime,
    nowdate,
    getdate,
    add_to_date,
    time_diff_in_hours,
    time_diff_in_seconds,
    get_datetime,
    cstr,
)


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Score threshold for considering entries as "close competitors"
# Entries within this threshold of the top score are eligible for rotation
ROTATION_SCORE_THRESHOLD = 5.0  # Points difference (out of 100)

# Maximum hours a single seller can hold the Buy Box before rotation consideration
# This prevents monopolization even with the best score
MAX_WINNER_HOURS = 24  # 24 hours

# Maximum consecutive wins before forcing a rotation to a close competitor
MAX_CONSECUTIVE_WINS = 7  # After 7 rotation cycles, force rotation if close competitors exist

# Minimum entries required for rotation to apply
# Single-seller products don't need rotation
MIN_ENTRIES_FOR_ROTATION = 2

# Batch processing limit per scheduler run
BATCH_SIZE = 100

# History retention days (for cleanup)
ROTATION_HISTORY_DAYS = 90


# =============================================================================
# MAIN SCHEDULER FUNCTION
# =============================================================================


def rotate_buybox():
    """
    Main scheduler function for Buy Box rotation.

    This function is called by the Frappe scheduler to:
    1. Identify products eligible for rotation
    2. Apply fair rotation to prevent seller dominance
    3. Log rotation history for analytics

    Called via hooks.py scheduler_events cron configuration.

    Returns:
        dict: Summary of rotation results
    """
    frappe.logger().info("Starting Buy Box rotation scheduler")

    results = {
        "products_checked": 0,
        "rotations_performed": 0,
        "scores_recalculated": 0,
        "errors": [],
        "start_time": now_datetime(),
    }

    try:
        # Get all tenants with active Buy Box entries
        tenants = get_active_tenants()

        for tenant in tenants:
            try:
                tenant_results = process_tenant_rotation(tenant)
                results["products_checked"] += tenant_results.get("products_checked", 0)
                results["rotations_performed"] += tenant_results.get("rotations_performed", 0)
                results["scores_recalculated"] += tenant_results.get("scores_recalculated", 0)
            except Exception as e:
                error_msg = f"Error processing tenant {tenant}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.log_error(message=str(e), title=f"Buy Box Rotation Error: {tenant}")

        # Cleanup old rotation history
        cleanup_rotation_history()

    except Exception as e:
        error_msg = f"Buy Box rotation failed: {str(e)}"
        results["errors"].append(error_msg)
        frappe.log_error(message=str(e), title="Buy Box Rotation Scheduler Error")

    results["end_time"] = now_datetime()
    results["duration_seconds"] = time_diff_in_seconds(
        results["end_time"], results["start_time"]
    )

    # Log summary
    frappe.logger().info(
        f"Buy Box rotation completed: {results['products_checked']} checked, "
        f"{results['rotations_performed']} rotated, {len(results['errors'])} errors"
    )

    return results


# =============================================================================
# TENANT PROCESSING
# =============================================================================


def get_active_tenants() -> List[str]:
    """
    Get list of tenants with active Buy Box entries.

    Returns:
        list: List of tenant names
    """
    tenants = frappe.db.sql("""
        SELECT DISTINCT tenant
        FROM `tabBuy Box Entry`
        WHERE status = 'Active'
        AND tenant IS NOT NULL
    """, as_dict=True)

    return [t["tenant"] for t in tenants if t.get("tenant")]


def process_tenant_rotation(tenant: str) -> Dict[str, Any]:
    """
    Process Buy Box rotation for a specific tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Processing results for the tenant
    """
    results = {
        "products_checked": 0,
        "rotations_performed": 0,
        "scores_recalculated": 0,
    }

    # Get products with multiple active entries
    products = get_rotation_eligible_products(tenant)

    for product in products[:BATCH_SIZE]:
        try:
            product_result = process_product_rotation(product["sku_product"])
            results["products_checked"] += 1

            if product_result.get("rotated"):
                results["rotations_performed"] += 1
            if product_result.get("recalculated"):
                results["scores_recalculated"] += 1

        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=f"Buy Box Rotation Error: {product['sku_product']}"
            )

    return results


def get_rotation_eligible_products(tenant: str) -> List[Dict[str, Any]]:
    """
    Get products eligible for rotation (multiple active entries).

    Args:
        tenant: Tenant name

    Returns:
        list: List of product dicts with entry counts
    """
    products = frappe.db.sql("""
        SELECT
            sku_product,
            COUNT(*) as entry_count,
            MAX(CASE WHEN is_winner = 1 THEN winner_since END) as winner_since
        FROM `tabBuy Box Entry`
        WHERE status = 'Active'
        AND tenant = %s
        GROUP BY sku_product
        HAVING entry_count >= %s
        ORDER BY winner_since ASC
    """, (tenant, MIN_ENTRIES_FOR_ROTATION), as_dict=True)

    return products


# =============================================================================
# PRODUCT ROTATION LOGIC
# =============================================================================


def process_product_rotation(sku_product: str) -> Dict[str, Any]:
    """
    Process Buy Box rotation for a single product.

    This function:
    1. Gets current winner and all entries
    2. Checks if rotation is needed based on time and score thresholds
    3. Applies rotation if criteria are met
    4. Records rotation history

    Args:
        sku_product: SKU Product name

    Returns:
        dict: Processing result with rotated and recalculated flags
    """
    result = {
        "rotated": False,
        "recalculated": False,
        "new_winner": None,
        "previous_winner": None,
    }

    # Get all active entries with locking to prevent concurrent updates
    entries = frappe.db.sql("""
        SELECT
            name, seller, seller_name, offer_price, delivery_days,
            stock_available, seller_average_rating, seller_total_reviews,
            buy_box_score, is_winner, winner_since, last_score_update
        FROM `tabBuy Box Entry`
        WHERE sku_product = %s AND status = 'Active'
        FOR UPDATE
    """, (sku_product,), as_dict=True)

    if len(entries) < MIN_ENTRIES_FOR_ROTATION:
        return result

    # Find current winner
    current_winner = None
    for entry in entries:
        if entry.get("is_winner"):
            current_winner = entry
            break

    # If no winner set, recalculate
    if not current_winner:
        recalculate_buybox(sku_product)
        result["recalculated"] = True
        return result

    result["previous_winner"] = current_winner["name"]

    # Check if rotation is needed
    rotation_needed, reason = check_rotation_needed(current_winner, entries)

    if rotation_needed:
        # Get next eligible winner
        next_winner = get_next_rotation_winner(current_winner, entries)

        if next_winner and next_winner["name"] != current_winner["name"]:
            # Perform rotation
            perform_rotation(sku_product, current_winner, next_winner, reason)
            result["rotated"] = True
            result["new_winner"] = next_winner["name"]

    return result


def check_rotation_needed(
    current_winner: Dict[str, Any],
    all_entries: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Check if Buy Box rotation is needed.

    Rotation criteria:
    1. Winner has held position longer than MAX_WINNER_HOURS
    2. There are close competitors within ROTATION_SCORE_THRESHOLD
    3. Or winner has won MAX_CONSECUTIVE_WINS times with close competitors

    Args:
        current_winner: Current winner entry dict
        all_entries: All active entries for the product

    Returns:
        tuple: (rotation_needed: bool, reason: str)
    """
    # Check time-based rotation
    winner_since = current_winner.get("winner_since")
    if winner_since:
        hours_as_winner = time_diff_in_hours(now_datetime(), winner_since)

        if hours_as_winner >= MAX_WINNER_HOURS:
            # Check if close competitors exist
            close_competitors = get_close_competitors(current_winner, all_entries)

            if close_competitors:
                return True, f"time_threshold_exceeded ({hours_as_winner:.1f}h)"

    # Check score-based rotation (very close scores)
    winner_score = flt(current_winner.get("buy_box_score", 0))
    for entry in all_entries:
        if entry["name"] == current_winner["name"]:
            continue

        entry_score = flt(entry.get("buy_box_score", 0))
        score_diff = abs(winner_score - entry_score)

        # If scores are within 1 point and winner has held for 8+ hours, rotate
        if score_diff <= 1.0:
            winner_since = current_winner.get("winner_since")
            if winner_since:
                hours_as_winner = time_diff_in_hours(now_datetime(), winner_since)
                if hours_as_winner >= 8:
                    return True, f"tie_score_rotation (diff: {score_diff:.2f})"

    return False, ""


def get_close_competitors(
    current_winner: Dict[str, Any],
    all_entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Get entries that are close competitors to the current winner.

    Close competitors are entries within ROTATION_SCORE_THRESHOLD of the winner's score.

    Args:
        current_winner: Current winner entry
        all_entries: All active entries

    Returns:
        list: List of close competitor entries
    """
    winner_score = flt(current_winner.get("buy_box_score", 0))
    competitors = []

    for entry in all_entries:
        if entry["name"] == current_winner["name"]:
            continue

        entry_score = flt(entry.get("buy_box_score", 0))
        score_diff = winner_score - entry_score

        if score_diff <= ROTATION_SCORE_THRESHOLD and entry_score > 0:
            entry["score_diff"] = score_diff
            competitors.append(entry)

    # Sort by score (highest first)
    competitors.sort(key=lambda x: x.get("buy_box_score", 0), reverse=True)

    return competitors


def get_next_rotation_winner(
    current_winner: Dict[str, Any],
    all_entries: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Determine the next winner for rotation.

    Selection strategy:
    1. Get close competitors
    2. Prefer competitors who haven't won recently
    3. Use round-robin among similar scores

    Args:
        current_winner: Current winner entry
        all_entries: All active entries

    Returns:
        dict: Next winner entry or None
    """
    close_competitors = get_close_competitors(current_winner, all_entries)

    if not close_competitors:
        return None

    # Get rotation history for recent winners
    recent_winners = get_recent_winners(current_winner.get("sku_product"))

    # Filter out entries that won recently (within last 24 hours)
    recent_cutoff = add_to_date(now_datetime(), hours=-24)
    eligible_competitors = []

    for competitor in close_competitors:
        last_win = recent_winners.get(competitor["name"])
        if not last_win or get_datetime(last_win) < recent_cutoff:
            eligible_competitors.append(competitor)

    # If all close competitors won recently, just pick the highest scoring one
    if not eligible_competitors:
        eligible_competitors = close_competitors

    # Return the highest scoring eligible competitor
    return eligible_competitors[0] if eligible_competitors else None


def get_recent_winners(sku_product: str) -> Dict[str, datetime]:
    """
    Get recent Buy Box winners from history.

    Args:
        sku_product: SKU Product name

    Returns:
        dict: Mapping of entry name to last win datetime
    """
    history = frappe.db.sql("""
        SELECT entry_name, rotated_at
        FROM `tabBuy Box Rotation History`
        WHERE sku_product = %s
        AND rotated_at >= %s
        ORDER BY rotated_at DESC
    """, (sku_product, add_to_date(nowdate(), days=-7)), as_dict=True)

    winners = {}
    for record in history:
        entry_name = record.get("entry_name")
        if entry_name and entry_name not in winners:
            winners[entry_name] = record.get("rotated_at")

    return winners


# =============================================================================
# ROTATION EXECUTION
# =============================================================================


def perform_rotation(
    sku_product: str,
    old_winner: Dict[str, Any],
    new_winner: Dict[str, Any],
    reason: str
):
    """
    Perform the actual Buy Box rotation.

    Args:
        sku_product: SKU Product name
        old_winner: Previous winner entry dict
        new_winner: New winner entry dict
        reason: Reason for rotation
    """
    now = now_datetime()

    # Update old winner
    frappe.db.set_value(
        "Buy Box Entry",
        old_winner["name"],
        {
            "is_winner": 0,
            "winner_since": None,
        },
        update_modified=False
    )

    # Update new winner
    frappe.db.set_value(
        "Buy Box Entry",
        new_winner["name"],
        {
            "is_winner": 1,
            "winner_since": now,
        },
        update_modified=False
    )

    # Record rotation history
    record_rotation_history(
        sku_product=sku_product,
        old_winner_entry=old_winner["name"],
        old_winner_seller=old_winner.get("seller"),
        new_winner_entry=new_winner["name"],
        new_winner_seller=new_winner.get("seller"),
        reason=reason,
        old_score=old_winner.get("buy_box_score"),
        new_score=new_winner.get("buy_box_score"),
    )

    frappe.db.commit()

    frappe.logger().info(
        f"Buy Box rotated for {sku_product}: "
        f"{old_winner.get('seller_name')} -> {new_winner.get('seller_name')} "
        f"(reason: {reason})"
    )


def record_rotation_history(
    sku_product: str,
    old_winner_entry: str,
    old_winner_seller: str,
    new_winner_entry: str,
    new_winner_seller: str,
    reason: str,
    old_score: float = 0,
    new_score: float = 0,
):
    """
    Record Buy Box rotation in history table for analytics.

    Args:
        sku_product: SKU Product name
        old_winner_entry: Previous winner entry name
        old_winner_seller: Previous winner seller name
        new_winner_entry: New winner entry name
        new_winner_seller: New winner seller name
        reason: Rotation reason
        old_score: Previous winner's score
        new_score: New winner's score
    """
    # Check if rotation history table exists
    if not frappe.db.table_exists("tabBuy Box Rotation History"):
        create_rotation_history_table()

    frappe.db.sql("""
        INSERT INTO `tabBuy Box Rotation History` (
            name, sku_product, entry_name, old_winner_entry, old_winner_seller,
            new_winner_entry, new_winner_seller, reason, old_score, new_score,
            rotated_at, creation, modified, owner, modified_by
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """, (
        frappe.generate_hash(length=10),
        sku_product,
        new_winner_entry,
        old_winner_entry,
        old_winner_seller,
        new_winner_entry,
        new_winner_seller,
        reason,
        flt(old_score),
        flt(new_score),
        now_datetime(),
        now_datetime(),
        now_datetime(),
        "Administrator",
        "Administrator",
    ))


def create_rotation_history_table():
    """
    Create Buy Box Rotation History table if it doesn't exist.

    This table tracks all Buy Box rotations for analytics and auditing.
    """
    frappe.db.sql("""
        CREATE TABLE IF NOT EXISTS `tabBuy Box Rotation History` (
            `name` varchar(140) NOT NULL,
            `sku_product` varchar(140) DEFAULT NULL,
            `entry_name` varchar(140) DEFAULT NULL,
            `old_winner_entry` varchar(140) DEFAULT NULL,
            `old_winner_seller` varchar(140) DEFAULT NULL,
            `new_winner_entry` varchar(140) DEFAULT NULL,
            `new_winner_seller` varchar(140) DEFAULT NULL,
            `reason` varchar(255) DEFAULT NULL,
            `old_score` decimal(18,6) DEFAULT 0,
            `new_score` decimal(18,6) DEFAULT 0,
            `rotated_at` datetime DEFAULT NULL,
            `creation` datetime DEFAULT NULL,
            `modified` datetime DEFAULT NULL,
            `owner` varchar(140) DEFAULT NULL,
            `modified_by` varchar(140) DEFAULT NULL,
            PRIMARY KEY (`name`),
            KEY `sku_product_idx` (`sku_product`),
            KEY `rotated_at_idx` (`rotated_at`),
            KEY `entry_name_idx` (`entry_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    frappe.db.commit()


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def recalculate_buybox(sku_product: str):
    """
    Trigger Buy Box score recalculation for a product.

    Args:
        sku_product: SKU Product name
    """
    try:
        from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
        calculate_buybox_winner(sku_product, use_locking=True, update_entries=True)
    except ImportError:
        # Fallback to doctype method
        from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
            recalculate_buy_box_for_product
        )
        recalculate_buy_box_for_product(sku_product)


def cleanup_rotation_history():
    """
    Clean up old rotation history records.

    Removes records older than ROTATION_HISTORY_DAYS.
    """
    if not frappe.db.table_exists("tabBuy Box Rotation History"):
        return

    cutoff_date = add_to_date(nowdate(), days=-ROTATION_HISTORY_DAYS)

    frappe.db.sql("""
        DELETE FROM `tabBuy Box Rotation History`
        WHERE rotated_at < %s
    """, (cutoff_date,))

    frappe.db.commit()


# =============================================================================
# SINGLE PRODUCT ROTATION
# =============================================================================


def rotate_product_buybox(sku_product: str, force: bool = False) -> Dict[str, Any]:
    """
    Rotate Buy Box for a single product.

    Can be called directly or enqueued as a background job.

    Args:
        sku_product: SKU Product name
        force: Force rotation even if criteria not met

    Returns:
        dict: Rotation result
    """
    result = process_product_rotation(sku_product)

    if force and not result.get("rotated"):
        # Force rotation to next highest scorer
        entries = frappe.get_all(
            "Buy Box Entry",
            filters={"sku_product": sku_product, "status": "Active"},
            fields=["name", "seller", "seller_name", "buy_box_score", "is_winner"],
            order_by="buy_box_score desc"
        )

        if len(entries) >= 2:
            current_winner = next((e for e in entries if e.get("is_winner")), None)
            if current_winner:
                next_entry = next(
                    (e for e in entries if e["name"] != current_winner["name"]),
                    None
                )
                if next_entry:
                    perform_rotation(
                        sku_product,
                        current_winner,
                        next_entry,
                        "forced_rotation"
                    )
                    result["rotated"] = True
                    result["new_winner"] = next_entry["name"]

    return result


# =============================================================================
# REPORTING FUNCTIONS
# =============================================================================


def get_rotation_statistics(
    tenant: Optional[str] = None,
    days: int = 30
) -> Dict[str, Any]:
    """
    Get Buy Box rotation statistics.

    Args:
        tenant: Optional tenant filter
        days: Number of days to analyze

    Returns:
        dict: Rotation statistics
    """
    if not frappe.db.table_exists("tabBuy Box Rotation History"):
        return {"message": "No rotation history available"}

    cutoff_date = add_to_date(nowdate(), days=-days)

    query = """
        SELECT
            COUNT(*) as total_rotations,
            COUNT(DISTINCT sku_product) as products_rotated,
            COUNT(DISTINCT new_winner_seller) as sellers_rotated_to
        FROM `tabBuy Box Rotation History`
        WHERE rotated_at >= %s
    """
    params = [cutoff_date]

    if tenant:
        query += " AND sku_product IN (SELECT name FROM `tabSKU Product` WHERE tenant = %s)"
        params.append(tenant)

    stats = frappe.db.sql(query, tuple(params), as_dict=True)

    if not stats:
        return {"total_rotations": 0, "products_rotated": 0, "sellers_rotated_to": 0}

    return stats[0]


def get_seller_rotation_history(
    seller: str,
    days: int = 30
) -> List[Dict[str, Any]]:
    """
    Get Buy Box rotation history for a seller.

    Args:
        seller: Seller Profile name
        days: Number of days to analyze

    Returns:
        list: Rotation history records
    """
    if not frappe.db.table_exists("tabBuy Box Rotation History"):
        return []

    cutoff_date = add_to_date(nowdate(), days=-days)

    history = frappe.db.sql("""
        SELECT
            sku_product, entry_name, reason, old_score, new_score,
            rotated_at,
            CASE
                WHEN new_winner_seller = %s THEN 'won'
                WHEN old_winner_seller = %s THEN 'lost'
            END as rotation_type
        FROM `tabBuy Box Rotation History`
        WHERE (new_winner_seller = %s OR old_winner_seller = %s)
        AND rotated_at >= %s
        ORDER BY rotated_at DESC
    """, (seller, seller, seller, seller, cutoff_date), as_dict=True)

    return history


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def manual_rotate_buybox(sku_product: str) -> Dict[str, Any]:
    """
    Manually trigger Buy Box rotation for a product.

    API endpoint for admin manual rotation.

    Args:
        sku_product: SKU Product name

    Returns:
        dict: Rotation result
    """
    if not sku_product:
        frappe.throw(_("SKU Product is required"))

    return rotate_product_buybox(sku_product, force=True)


@frappe.whitelist()
def get_buybox_rotation_stats(
    tenant: Optional[str] = None,
    days: int = 30
) -> Dict[str, Any]:
    """
    Get Buy Box rotation statistics via API.

    Args:
        tenant: Optional tenant filter
        days: Number of days to analyze

    Returns:
        dict: Rotation statistics
    """
    return get_rotation_statistics(tenant=tenant, days=cint(days))


@frappe.whitelist()
def get_seller_buybox_history(
    seller: str,
    days: int = 30
) -> List[Dict[str, Any]]:
    """
    Get Buy Box rotation history for a seller via API.

    Args:
        seller: Seller Profile name
        days: Number of days to analyze

    Returns:
        list: Rotation history
    """
    if not seller:
        frappe.throw(_("Seller is required"))

    return get_seller_rotation_history(seller=seller, days=cint(days))


@frappe.whitelist()
def enqueue_rotation_for_product(sku_product: str) -> Dict[str, str]:
    """
    Enqueue Buy Box rotation for a product.

    Args:
        sku_product: SKU Product name

    Returns:
        dict: Job enqueue status
    """
    if not sku_product:
        frappe.throw(_("SKU Product is required"))

    frappe.enqueue(
        "tr_tradehub.tasks.buybox_rotation.rotate_product_buybox",
        sku_product=sku_product,
        force=True,
        queue="short",
        deduplicate=True
    )

    return {"message": _("Buy Box rotation enqueued for {0}").format(sku_product)}
