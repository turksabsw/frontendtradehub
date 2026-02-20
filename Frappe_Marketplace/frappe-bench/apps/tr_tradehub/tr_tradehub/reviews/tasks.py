# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Reviews & Moderation Scheduled Tasks

Background jobs for review and moderation processing.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_days, add_to_date, getdate


def process_pending_reviews():
    """
    Daily job: Auto-publish reviews that have been pending for too long.

    Reviews pending for >24 hours without issues are auto-approved.
    """
    cutoff = add_to_date(now_datetime(), hours=-24)

    pending_reviews = frappe.get_all(
        "Review",
        filters={
            "status": "Pending Review",
            "moderation_status": "Pending",
            "submitted_at": ["<", cutoff]
        },
        fields=["name"]
    )

    for review in pending_reviews:
        try:
            # Run auto-moderation check first
            from tr_tradehub.reviews.review_manager import _auto_moderate_review
            _auto_moderate_review(review.name)

            # If still pending (no issues found), auto-approve
            review_doc = frappe.get_doc("Review", review.name)
            if review_doc.moderation_status == "Pending":
                from tr_tradehub.reviews.review_manager import publish_review
                publish_review(review.name, moderator="System")

        except Exception as e:
            frappe.log_error(
                f"Error auto-processing review {review.name}: {str(e)}",
                "Review Auto-Processing"
            )


def check_sla_breaches():
    """
    Hourly job: Check for SLA breaches and update status.
    """
    now = now_datetime()

    # Get open cases
    open_cases = frappe.get_all(
        "Moderation Case",
        filters={
            "status": ["not in", ["Resolved", "Closed"]],
            "sla_status": ["not in", ["Breached", "Exempt"]]
        },
        fields=["name", "creation_date", "sla_target_hours", "priority"]
    )

    for case in open_cases:
        try:
            if not case.creation_date or not case.sla_target_hours:
                continue

            hours_elapsed = (now - case.creation_date).total_seconds() / 3600

            # Determine SLA status
            if hours_elapsed > case.sla_target_hours:
                new_status = "Breached"
            elif hours_elapsed > case.sla_target_hours * 0.75:
                new_status = "At Risk"
            else:
                new_status = "On Track"

            frappe.db.set_value(
                "Moderation Case",
                case.name,
                "sla_status",
                new_status,
                update_modified=False
            )

            # Escalate if breached and high priority
            if new_status == "Breached" and case.priority in ["Critical", "High"]:
                _auto_escalate_case(case.name)

        except Exception as e:
            frappe.log_error(
                f"Error checking SLA for case {case.name}: {str(e)}",
                "SLA Check"
            )

    frappe.db.commit()


def send_review_reminders():
    """
    Daily job: Send reminders to buyers who haven't reviewed completed orders.
    """
    # Find orders completed 7-14 days ago without reviews
    min_date = add_days(getdate(), -14)
    max_date = add_days(getdate(), -7)

    orders_without_reviews = frappe.db.sql("""
        SELECT DISTINCT mo.name, mo.buyer, mo.grand_total
        FROM `tabMarketplace Order` mo
        LEFT JOIN `tabReview` r ON r.marketplace_order = mo.name
        WHERE mo.status IN ('Delivered', 'Completed')
        AND DATE(mo.modified) BETWEEN %s AND %s
        AND r.name IS NULL
    """, (min_date, max_date), as_dict=True)

    for order in orders_without_reviews:
        try:
            buyer_user = frappe.db.get_value("Buyer Profile", order.buyer, "user")
            if not buyer_user:
                continue

            # Check if we already sent a reminder
            existing_reminder = frappe.db.exists(
                "Notification Log",
                {
                    "for_user": buyer_user,
                    "document_type": "Marketplace Order",
                    "document_name": order.name,
                    "subject": ["like", "%review%"]
                }
            )

            if existing_reminder:
                continue

            # Send reminder
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Marketplace Order",
                "document_name": order.name,
                "subject": _("Share your experience!"),
                "email_content": _(
                    "How was your order? Your review helps other buyers "
                    "and sellers improve their service. Share your experience!"
                )
            }).insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error sending review reminder for order {order.name}: {str(e)}",
                "Review Reminder"
            )

    frappe.db.commit()


def cleanup_old_cases():
    """
    Weekly job: Archive old closed cases.

    Cases closed for >90 days are archived (status updated).
    """
    cutoff = add_days(now_datetime(), -90)

    old_cases = frappe.get_all(
        "Moderation Case",
        filters={
            "status": ["in", ["Resolved", "Closed"]],
            "review_completed_at": ["<", cutoff]
        },
        pluck="name"
    )

    for case_name in old_cases:
        try:
            frappe.db.set_value(
                "Moderation Case",
                case_name,
                {
                    "status": "Closed",
                    "internal_notes": frappe.db.get_value(
                        "Moderation Case", case_name, "internal_notes"
                    ) + f"\n\n[{now_datetime()}] Auto-archived after 90 days"
                },
                update_modified=False
            )
        except Exception as e:
            frappe.log_error(
                f"Error archiving case {case_name}: {str(e)}",
                "Case Archival"
            )

    frappe.db.commit()


def calculate_seller_scores():
    """
    Daily job: Recalculate seller scores based on reviews.
    """
    # Get all active sellers
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": "Active"},
        pluck="name"
    )

    for seller in sellers:
        try:
            # Get review statistics
            stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total_reviews,
                    AVG(rating) as avg_rating,
                    SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive_reviews,
                    SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) as negative_reviews,
                    AVG(seller_communication_rating) as avg_communication,
                    AVG(shipping_rating) as avg_shipping
                FROM `tabReview`
                WHERE seller = %s
                AND status = 'Published'
                AND published_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            """, (seller,), as_dict=True)[0]

            if not stats.total_reviews:
                continue

            # Calculate positive feedback rate
            positive_rate = (stats.positive_reviews / stats.total_reviews * 100) if stats.total_reviews > 0 else 100

            # Update seller profile
            frappe.db.set_value(
                "Seller Profile",
                seller,
                {
                    "total_reviews": stats.total_reviews,
                    "average_rating": round(stats.avg_rating or 0, 2),
                    "positive_feedback_rate": round(positive_rate, 2)
                },
                update_modified=False
            )

        except Exception as e:
            frappe.log_error(
                f"Error calculating scores for seller {seller}: {str(e)}",
                "Seller Score Calculation"
            )

    frappe.db.commit()


def process_expired_appeals():
    """
    Daily job: Close appeals that have been pending for too long.

    Appeals pending for >30 days are auto-rejected.
    """
    cutoff = add_days(now_datetime(), -30)

    expired_appeals = frappe.get_all(
        "Moderation Case",
        filters={
            "appeal_status": ["in", ["Appeal Submitted", "Under Review"]],
            "appeal_submitted_at": ["<", cutoff]
        },
        fields=["name"]
    )

    for case in expired_appeals:
        try:
            frappe.db.set_value(
                "Moderation Case",
                case.name,
                {
                    "appeal_status": "Rejected",
                    "appeal_decision": "Auto-rejected due to no response within 30 days",
                    "appeal_decided_at": now_datetime(),
                    "appeal_decided_by": "System"
                }
            )

            # Notify appellant
            case_doc = frappe.get_doc("Moderation Case", case.name)
            if case_doc.content_owner:
                from tr_tradehub.reviews.moderation import _get_content_owner_user
                owner_user = _get_content_owner_user(
                    case_doc.content_owner,
                    case_doc.content_owner_type
                )
                if owner_user:
                    frappe.get_doc({
                        "doctype": "Notification Log",
                        "for_user": owner_user,
                        "type": "Alert",
                        "document_type": "Moderation Case",
                        "document_name": case.name,
                        "subject": _("Appeal Closed"),
                        "email_content": _(
                            "Your appeal has been automatically closed "
                            "after 30 days without a decision."
                        )
                    }).insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error processing expired appeal {case.name}: {str(e)}",
                "Appeal Expiration"
            )

    frappe.db.commit()


def _auto_escalate_case(case_name: str):
    """Auto-escalate a case that breached SLA."""
    try:
        from tr_tradehub.reviews.moderation import escalate_case

        case = frappe.get_doc("Moderation Case", case_name)

        # Don't escalate if already escalated
        if case.is_escalated:
            return

        # Determine escalation level based on priority
        if case.priority == "Critical":
            level = "Level 3 - Manager"
        else:
            level = "Level 2 - Senior Moderator"

        escalate_case(
            case_name=case_name,
            escalation_level=level,
            reason=f"Auto-escalated due to SLA breach"
        )

    except Exception as e:
        frappe.log_error(
            f"Error auto-escalating case {case_name}: {str(e)}",
            "Auto Escalation"
        )
