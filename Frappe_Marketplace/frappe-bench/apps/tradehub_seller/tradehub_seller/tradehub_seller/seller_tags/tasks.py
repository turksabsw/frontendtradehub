# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tags Scheduled Tasks

Scheduler jobs for metrics refresh and rule evaluation.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


def refresh_seller_metrics():
    """
    Hourly job: Refresh seller metrics materialized view.

    Runs for all active sellers to keep metrics up-to-date.
    """
    from tradehub_seller.tradehub_seller.seller_tags.seller_metrics import refresh_all_seller_metrics

    frappe.logger().info("Starting seller metrics refresh...")

    try:
        count = refresh_all_seller_metrics()
        frappe.logger().info(f"Refreshed metrics for {count} sellers")
    except Exception as e:
        frappe.log_error(
            f"Error in seller metrics refresh: {str(e)}",
            "Seller Metrics Task"
        )


def evaluate_all_rules():
    """
    Daily job: Evaluate all seller tag rules.

    Processes each active seller against all enabled rules
    and updates tag assignments accordingly.
    """
    from tradehub_seller.tradehub_seller.seller_tags.rule_engine import RuleEngine

    frappe.logger().info("Starting seller tag rule evaluation...")

    engine = RuleEngine()

    # Get all active sellers
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": ["in", ["Active", "Verified"]]},
        fields=["name"]
    )

    processed = 0
    errors = 0

    for seller in sellers:
        try:
            # Get qualified tags for this seller
            qualified_tags = engine.evaluate_all_rules_for_seller(seller.name)

            # Apply qualified tag assignments
            for tag in qualified_tags:
                engine.apply_tag_assignment(seller.name, tag, source="Rule")

            # Remove tags seller no longer qualifies for
            engine.remove_unqualified_tags(seller.name, qualified_tags)

            processed += 1

        except Exception as e:
            errors += 1
            frappe.log_error(
                f"Error evaluating rules for seller {seller.name}: {str(e)}",
                "Rule Evaluation Task"
            )

    frappe.db.commit()

    frappe.logger().info(
        f"Rule evaluation complete. Processed: {processed}, Errors: {errors}"
    )


def cleanup_old_metrics():
    """
    Weekly job: Clean up old metrics records.

    Keeps only the last 30 days of metrics history.
    """
    from frappe.utils import add_days, today

    cutoff_date = add_days(today(), -30)

    frappe.logger().info(f"Cleaning up metrics older than {cutoff_date}")

    try:
        # Delete old metrics records
        deleted = frappe.db.sql("""
            DELETE FROM `tabSeller Metrics`
            WHERE calculation_date < %s
        """, cutoff_date)

        frappe.db.commit()
        frappe.logger().info("Old metrics cleanup complete")

    except Exception as e:
        frappe.log_error(
            f"Error in metrics cleanup: {str(e)}",
            "Metrics Cleanup Task"
        )


def evaluate_single_seller_rules(seller_id: str):
    """
    Evaluate rules for a single seller (for immediate updates).

    Args:
        seller_id: Seller Profile name
    """
    from tradehub_seller.tradehub_seller.seller_tags.rule_engine import RuleEngine
    from tradehub_seller.tradehub_seller.seller_tags.seller_metrics import refresh_seller_metrics

    # First refresh metrics
    refresh_seller_metrics(seller_id)

    # Then evaluate rules
    engine = RuleEngine()
    qualified_tags = engine.evaluate_all_rules_for_seller(seller_id)

    for tag in qualified_tags:
        engine.apply_tag_assignment(seller_id, tag, source="Rule")

    engine.remove_unqualified_tags(seller_id, qualified_tags)

    frappe.db.commit()
