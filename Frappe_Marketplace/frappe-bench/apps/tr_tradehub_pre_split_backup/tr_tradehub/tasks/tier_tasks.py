# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tier Tasks Module

Scheduled background tasks for seller tier management:
- evaluate_seller_tiers: Weekly evaluation of all sellers for tier upgrades/downgrades
- update_tier_statistics: Daily update of tier statistics
- process_tier_notifications: Daily processing of tier-related notifications
"""

import frappe
from frappe import _
from frappe.utils import nowdate, add_days, getdate, now_datetime, cint, flt


def evaluate_seller_tiers():
    """
    Evaluate all active sellers for tier changes.

    Runs weekly to check if sellers:
    - Qualify for tier upgrades
    - No longer qualify for current tier (potential downgrade)
    - Need notification about tier changes

    Handles auto-upgrade/downgrade based on tier settings.
    """
    frappe.logger().info("Running evaluate_seller_tiers task")

    processed_count = 0
    upgraded_count = 0
    downgraded_count = 0
    error_count = 0

    # Get all active seller profiles
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": ["in", ["Active", "Approved"]]},
        fields=["name", "seller_name", "seller_tier", "seller_score", "tenant"]
    )

    for seller in sellers:
        try:
            result = evaluate_single_seller_tier(seller)
            processed_count += 1

            if result.get("action") == "upgraded":
                upgraded_count += 1
            elif result.get("action") == "downgraded":
                downgraded_count += 1

        except Exception as e:
            error_count += 1
            frappe.log_error(
                message=f"Error evaluating tier for seller {seller.name}: {str(e)}",
                title="Seller Tier Evaluation Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed evaluate_seller_tiers task: "
        f"{processed_count} sellers processed, "
        f"{upgraded_count} upgrades, "
        f"{downgraded_count} downgrades, "
        f"{error_count} errors"
    )

    return {
        "processed": processed_count,
        "upgraded": upgraded_count,
        "downgraded": downgraded_count,
        "errors": error_count
    }


def evaluate_single_seller_tier(seller):
    """
    Evaluate tier eligibility for a single seller.

    Args:
        seller: Dict with seller info (name, seller_tier, tenant)

    Returns:
        dict: Result with action taken
    """
    result = {"seller": seller.name, "action": None, "details": None}

    current_tier = seller.seller_tier
    tenant = seller.tenant

    # Get all active tiers, ordered by level descending (highest first)
    filters = {"status": "Active"}
    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]
    else:
        filters["tenant"] = ["is", "not set"]

    tiers = frappe.get_all(
        "Seller Tier",
        filters=filters,
        fields=["name", "tier_level", "tier_name", "auto_upgrade", "auto_downgrade", "downgrade_grace_days"],
        order_by="tier_level desc"
    )

    if not tiers:
        return result

    # Find the highest tier the seller qualifies for
    highest_eligible_tier = None

    for tier in tiers:
        tier_doc = frappe.get_doc("Seller Tier", tier.name)
        is_eligible, _ = tier_doc.check_seller_eligibility(seller.name)

        if is_eligible:
            highest_eligible_tier = tier
            break  # Since tiers are ordered desc, first match is highest

    if not highest_eligible_tier:
        # No eligible tier - use default or lowest tier
        default_tier = frappe.db.get_value(
            "Seller Tier",
            {"is_default": 1, "status": "Active"},
            "name"
        )
        if default_tier:
            highest_eligible_tier = frappe.db.get_value(
                "Seller Tier", default_tier,
                ["name", "tier_level", "tier_name", "auto_upgrade", "auto_downgrade", "downgrade_grace_days"],
                as_dict=True
            )

    if not highest_eligible_tier:
        return result

    # Check if tier change is needed
    if not current_tier:
        # Assign tier for new seller
        frappe.db.set_value("Seller Profile", seller.name, "seller_tier", highest_eligible_tier.name)
        result["action"] = "assigned"
        result["details"] = f"Assigned to {highest_eligible_tier.tier_name}"

        # Send notification
        send_tier_notification(seller.name, "assigned", None, highest_eligible_tier.name)

    elif current_tier != highest_eligible_tier.name:
        current_tier_level = frappe.db.get_value("Seller Tier", current_tier, "tier_level") or 0
        eligible_tier_level = highest_eligible_tier.tier_level

        if eligible_tier_level > current_tier_level:
            # Potential upgrade
            current_tier_doc = frappe.get_doc("Seller Tier", current_tier) if current_tier else None

            if not current_tier_doc or cint(current_tier_doc.auto_upgrade):
                # Perform upgrade
                frappe.db.set_value("Seller Profile", seller.name, "seller_tier", highest_eligible_tier.name)
                result["action"] = "upgraded"
                result["details"] = f"Upgraded from {current_tier} to {highest_eligible_tier.tier_name}"

                # Send notification
                send_tier_notification(seller.name, "upgraded", current_tier, highest_eligible_tier.name)

                # Update tier statistics
                update_tier_counts(current_tier)
                update_tier_counts(highest_eligible_tier.name)

        elif eligible_tier_level < current_tier_level:
            # Potential downgrade - check grace period
            current_tier_doc = frappe.get_doc("Seller Tier", current_tier)

            if cint(current_tier_doc.auto_downgrade):
                # Check grace period
                grace_days = cint(current_tier_doc.downgrade_grace_days) or 30

                # Check if seller has been below threshold for grace period
                # This requires tracking - for now, add warning and schedule check
                grace_key = f"tier_downgrade_warning:{seller.name}"
                warning_date = frappe.cache().get_value(grace_key)

                if not warning_date:
                    # First time below threshold - start grace period
                    frappe.cache().set_value(grace_key, nowdate(), expires_in_sec=grace_days * 24 * 60 * 60)
                    result["action"] = "warning"
                    result["details"] = f"Grace period started - {grace_days} days until potential downgrade"

                    # Send warning notification
                    send_tier_notification(seller.name, "downgrade_warning", current_tier, highest_eligible_tier.name, grace_days)
                else:
                    # Check if grace period has passed
                    warning_start = getdate(warning_date)
                    if (getdate(nowdate()) - warning_start).days >= grace_days:
                        # Grace period passed - perform downgrade
                        frappe.db.set_value("Seller Profile", seller.name, "seller_tier", highest_eligible_tier.name)
                        frappe.cache().delete_value(grace_key)
                        result["action"] = "downgraded"
                        result["details"] = f"Downgraded from {current_tier} to {highest_eligible_tier.tier_name}"

                        # Send notification
                        send_tier_notification(seller.name, "downgraded", current_tier, highest_eligible_tier.name)

                        # Update tier statistics
                        update_tier_counts(current_tier)
                        update_tier_counts(highest_eligible_tier.name)
    else:
        # Clear any downgrade warning if seller now qualifies
        grace_key = f"tier_downgrade_warning:{seller.name}"
        if frappe.cache().get_value(grace_key):
            frappe.cache().delete_value(grace_key)

    return result


def update_tier_counts(tier_name):
    """Update seller counts for a tier."""
    if not tier_name:
        return

    try:
        stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active,
                AVG(seller_score) as avg_score
            FROM `tabSeller Profile`
            WHERE seller_tier = %s
        """, tier_name, as_dict=True)

        if stats:
            frappe.db.set_value(
                "Seller Tier", tier_name,
                {
                    "total_sellers": stats[0].total or 0,
                    "active_sellers": stats[0].active or 0,
                    "avg_seller_performance": round(stats[0].avg_score or 0, 2),
                    "last_stats_update": now_datetime()
                },
                update_modified=False
            )
    except Exception as e:
        frappe.log_error(
            message=f"Error updating tier counts for {tier_name}: {str(e)}",
            title="Tier Stats Update Error"
        )


def send_tier_notification(seller, action, old_tier, new_tier, grace_days=None):
    """
    Send tier change notification to seller.

    Args:
        seller: Seller Profile name
        action: Type of action (assigned, upgraded, downgraded, downgrade_warning)
        old_tier: Previous tier name
        new_tier: New tier name
        grace_days: Days until downgrade (for warnings)
    """
    try:
        seller_doc = frappe.get_doc("Seller Profile", seller)

        if not seller_doc.user:
            return

        old_tier_name = frappe.db.get_value("Seller Tier", old_tier, "tier_name") if old_tier else None
        new_tier_name = frappe.db.get_value("Seller Tier", new_tier, "tier_name") if new_tier else None

        # Prepare notification based on action type
        if action == "assigned":
            subject = _("Welcome to {0} Tier!").format(new_tier_name)
            message = _(
                "Congratulations! You have been assigned to the {0} tier. "
                "Check your seller dashboard to see the benefits available to you."
            ).format(new_tier_name)

        elif action == "upgraded":
            subject = _("Congratulations! You've been upgraded to {0}!").format(new_tier_name)
            message = _(
                "Great news! Based on your excellent performance, you have been upgraded "
                "from {0} to {1}. Enjoy your new benefits!"
            ).format(old_tier_name, new_tier_name)

        elif action == "downgraded":
            subject = _("Tier Status Change: Now at {0}").format(new_tier_name)
            message = _(
                "Your seller tier has been changed from {0} to {1} based on recent performance metrics. "
                "Keep improving your metrics to regain your previous tier status!"
            ).format(old_tier_name, new_tier_name)

        elif action == "downgrade_warning":
            subject = _("Action Required: Risk of Tier Downgrade")
            message = _(
                "Your current performance metrics no longer meet the requirements for {0}. "
                "You have {1} days to improve your metrics before being moved to {2}. "
                "Please check your seller dashboard for details."
            ).format(old_tier_name, grace_days, new_tier_name)

        else:
            return

        # Create notification
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": seller_doc.user,
            "type": "Alert",
            "document_type": "Seller Profile",
            "document_name": seller,
            "subject": subject,
            "email_content": message
        }).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            message=f"Error sending tier notification for {seller}: {str(e)}",
            title="Tier Notification Error"
        )


def update_tier_statistics():
    """
    Update statistics for all active tiers.
    Runs daily to keep tier statistics current.
    """
    frappe.logger().info("Running update_tier_statistics task")

    tiers = frappe.get_all("Seller Tier", filters={"status": "Active"}, pluck="name")

    updated_count = 0
    for tier_name in tiers:
        try:
            update_tier_counts(tier_name)
            updated_count += 1
        except Exception as e:
            frappe.log_error(
                message=f"Error updating statistics for tier {tier_name}: {str(e)}",
                title="Tier Stats Update Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed update_tier_statistics task: {updated_count} tiers updated")

    return updated_count


def process_tier_notifications():
    """
    Process pending tier-related notifications.
    Checks for sellers approaching tier upgrade/downgrade thresholds.
    """
    frappe.logger().info("Running process_tier_notifications task")

    notification_count = 0

    # Get sellers who are close to upgrade
    sellers_near_upgrade = get_sellers_near_upgrade()

    for seller in sellers_near_upgrade:
        try:
            send_upgrade_progress_notification(seller)
            notification_count += 1
        except Exception as e:
            frappe.log_error(
                message=f"Error sending upgrade progress notification for {seller}: {str(e)}",
                title="Tier Notification Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed process_tier_notifications task: {notification_count} notifications sent")

    return notification_count


def get_sellers_near_upgrade():
    """
    Get sellers who are close to qualifying for the next tier.
    Returns sellers within 10% of next tier requirements.
    """
    sellers_near_upgrade = []

    # Get active sellers with a current tier that has a next tier
    sellers = frappe.db.sql("""
        SELECT
            sp.name, sp.seller_name, sp.seller_score, sp.seller_tier,
            st.next_tier, st.tier_name as current_tier_name
        FROM `tabSeller Profile` sp
        JOIN `tabSeller Tier` st ON sp.seller_tier = st.name
        WHERE sp.status IN ('Active', 'Approved')
        AND st.next_tier IS NOT NULL
    """, as_dict=True)

    for seller in sellers:
        next_tier = frappe.get_doc("Seller Tier", seller.next_tier)

        # Check if seller is within 10% of next tier's min score
        if flt(next_tier.min_seller_score) > 0:
            score_gap = flt(next_tier.min_seller_score) - flt(seller.seller_score)
            score_threshold = flt(next_tier.min_seller_score) * 0.1  # 10%

            if 0 < score_gap <= score_threshold:
                sellers_near_upgrade.append({
                    "name": seller.name,
                    "seller_name": seller.seller_name,
                    "current_tier": seller.current_tier_name,
                    "next_tier": next_tier.tier_name,
                    "current_score": seller.seller_score,
                    "required_score": next_tier.min_seller_score,
                    "gap": round(score_gap, 2)
                })

    return sellers_near_upgrade


def send_upgrade_progress_notification(seller_info):
    """
    Send notification about upgrade progress to a seller.

    Args:
        seller_info: Dict with seller upgrade progress info
    """
    try:
        seller_doc = frappe.get_doc("Seller Profile", seller_info["name"])

        if not seller_doc.user:
            return

        subject = _("You're almost there! {0} tier is within reach").format(seller_info["next_tier"])
        message = _(
            "Great progress! You're only {0} points away from qualifying for the {1} tier. "
            "Your current score is {2}, and you need {3} to upgrade. Keep up the excellent work!"
        ).format(
            seller_info["gap"],
            seller_info["next_tier"],
            seller_info["current_score"],
            seller_info["required_score"]
        )

        # Check if we've sent this notification recently (within 7 days)
        cache_key = f"tier_progress_notification:{seller_info['name']}"
        last_sent = frappe.cache().get_value(cache_key)

        if last_sent:
            return  # Don't spam

        # Create notification
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": seller_doc.user,
            "type": "Alert",
            "document_type": "Seller Profile",
            "document_name": seller_info["name"],
            "subject": subject,
            "email_content": message
        }).insert(ignore_permissions=True)

        # Set cache to prevent duplicate notifications
        frappe.cache().set_value(cache_key, nowdate(), expires_in_sec=7 * 24 * 60 * 60)

    except Exception as e:
        frappe.log_error(
            message=f"Error sending upgrade progress notification: {str(e)}",
            title="Tier Notification Error"
        )


# ==================== API Methods ====================

@frappe.whitelist()
def run_tier_evaluation(seller=None):
    """
    Run tier evaluation manually.

    Args:
        seller: Optional specific seller to evaluate

    Returns:
        dict: Evaluation results
    """
    if not frappe.has_permission("Seller Tier", "write"):
        frappe.throw(_("You don't have permission to run tier evaluations"))

    if seller:
        seller_doc = frappe.db.get_value(
            "Seller Profile", seller,
            ["name", "seller_name", "seller_tier", "seller_score", "tenant"],
            as_dict=True
        )
        if not seller_doc:
            frappe.throw(_("Seller not found"))

        result = evaluate_single_seller_tier(seller_doc)
        frappe.msgprint(_(
            "Tier evaluation completed for {0}: {1}"
        ).format(seller_doc.seller_name, result.get("details") or "No change"))

        return result
    else:
        # Run for all sellers
        result = evaluate_seller_tiers()
        frappe.msgprint(_(
            "Tier evaluation completed: {0} processed, {1} upgrades, {2} downgrades"
        ).format(result["processed"], result["upgraded"], result["downgraded"]))

        return result


@frappe.whitelist()
def get_tier_evaluation_status():
    """
    Get the current status of tier evaluations.

    Returns:
        dict: Status summary
    """
    # Get counts by tier
    tier_counts = frappe.db.sql("""
        SELECT
            st.tier_name,
            st.tier_level,
            COUNT(sp.name) as seller_count
        FROM `tabSeller Tier` st
        LEFT JOIN `tabSeller Profile` sp ON sp.seller_tier = st.name AND sp.status IN ('Active', 'Approved')
        WHERE st.status = 'Active'
        GROUP BY st.name
        ORDER BY st.tier_level ASC
    """, as_dict=True)

    # Get sellers with pending downgrade warnings
    # This is tracked in cache, so we count cache keys
    pending_downgrades = 0  # Would need to iterate cache keys

    return {
        "tier_distribution": tier_counts,
        "pending_downgrades": pending_downgrades,
        "last_evaluation": frappe.db.get_value(
            "Scheduled Job Log",
            {"scheduled_job_type": "tr_tradehub.tasks.tier_tasks.evaluate_seller_tiers"},
            "creation",
            order_by="creation desc"
        )
    }
