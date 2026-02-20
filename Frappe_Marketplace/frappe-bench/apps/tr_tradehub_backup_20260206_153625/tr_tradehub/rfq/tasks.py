# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ Scheduled Tasks

Deadline checking and notification tasks.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, add_days, getdate, today


def check_deadlines():
    """
    Hourly job: Check RFQ deadlines and update statuses.

    - Close RFQs that have passed their deadline
    - Move RFQs from Published to Quoting when quotes are received
    """
    frappe.logger().info("Checking RFQ deadlines...")

    now = now_datetime()

    # Find RFQs past deadline that are still in quoting status
    expired_rfqs = frappe.get_all(
        "RFQ",
        filters={
            "status": ["in", ["Published", "Quoting"]],
            "deadline": ["<", now]
        },
        fields=["name", "status"]
    )

    for rfq in expired_rfqs:
        try:
            doc = frappe.get_doc("RFQ", rfq.name)

            # Check if any quotes were received
            quote_count = frappe.db.count("RFQ Quote", {"rfq": rfq.name})

            if quote_count > 0:
                # Move to Negotiation if there are quotes
                doc.status = "Negotiation"
                doc.add_comment("Info", _("Deadline reached. Moving to negotiation phase."))
            else:
                # Close if no quotes
                doc.status = "Closed"
                doc.add_comment("Info", _("Deadline reached with no quotes. RFQ closed."))

            doc.save(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(
                f"Error processing RFQ deadline for {rfq.name}: {str(e)}",
                "RFQ Deadline Task"
            )


def send_deadline_reminders():
    """
    Hourly job: Send reminders for approaching deadlines.

    Sends reminders at:
    - 24 hours before deadline
    - 4 hours before deadline
    """
    now = now_datetime()

    # 24 hours reminder
    reminder_24h_start = add_to_date(now, hours=23)
    reminder_24h_end = add_to_date(now, hours=25)

    rfqs_24h = frappe.get_all(
        "RFQ",
        filters={
            "status": ["in", ["Published", "Quoting"]],
            "deadline": ["between", [reminder_24h_start, reminder_24h_end]]
        },
        fields=["name", "title", "buyer", "deadline"]
    )

    for rfq in rfqs_24h:
        _send_deadline_reminder(rfq, hours_remaining=24)

    # 4 hours reminder
    reminder_4h_start = add_to_date(now, hours=3)
    reminder_4h_end = add_to_date(now, hours=5)

    rfqs_4h = frappe.get_all(
        "RFQ",
        filters={
            "status": ["in", ["Published", "Quoting"]],
            "deadline": ["between", [reminder_4h_start, reminder_4h_end]]
        },
        fields=["name", "title", "buyer", "deadline"]
    )

    for rfq in rfqs_4h:
        _send_deadline_reminder(rfq, hours_remaining=4)


def _send_deadline_reminder(rfq: dict, hours_remaining: int):
    """
    Send deadline reminder notification.

    Args:
        rfq: RFQ document dict
        hours_remaining: Hours until deadline
    """
    try:
        # Get sellers who have been invited but haven't quoted
        invited_sellers = _get_invited_sellers_without_quote(rfq["name"])

        for seller in invited_sellers:
            # Send notification to seller
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": _get_seller_user(seller),
                "type": "Alert",
                "document_type": "RFQ",
                "document_name": rfq["name"],
                "subject": _("RFQ Deadline Reminder: {0}").format(rfq["title"]),
                "email_content": _(
                    "The RFQ '{0}' deadline is in {1} hours. "
                    "Submit your quote before it expires."
                ).format(rfq["title"], hours_remaining)
            }).insert(ignore_permissions=True)

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Error sending deadline reminder for {rfq['name']}: {str(e)}",
            "RFQ Reminder Task"
        )


def _get_invited_sellers_without_quote(rfq_name: str) -> list:
    """Get sellers invited to RFQ who haven't submitted a quote."""
    rfq = frappe.get_doc("RFQ", rfq_name)

    # Get sellers who have quoted
    quoted_sellers = frappe.get_all(
        "RFQ Quote",
        filters={"rfq": rfq_name},
        pluck="seller"
    )

    invited_sellers = []

    # Check target type
    if rfq.target_type == "Public":
        # For public RFQs, we can't track all potential sellers
        return []

    elif rfq.target_type == "Selected":
        # Get from target_sellers child table
        for row in rfq.get("target_sellers", []):
            if row.seller not in quoted_sellers:
                invited_sellers.append(row.seller)

    elif rfq.target_type == "Category":
        # Get sellers in target categories
        for row in rfq.get("target_categories", []):
            category_sellers = frappe.get_all(
                "Seller Profile",
                filters={
                    "status": "Active",
                    "primary_category": row.category
                },
                pluck="name"
            )
            for seller in category_sellers:
                if seller not in quoted_sellers and seller not in invited_sellers:
                    invited_sellers.append(seller)

    return invited_sellers


def _get_seller_user(seller: str) -> str:
    """Get the user associated with a seller profile."""
    return frappe.db.get_value("Seller Profile", seller, "user") or "Administrator"


def cleanup_draft_rfqs():
    """
    Weekly job: Clean up old draft RFQs.

    Deletes draft RFQs older than 30 days.
    """
    cutoff_date = add_days(today(), -30)

    old_drafts = frappe.get_all(
        "RFQ",
        filters={
            "status": "Draft",
            "creation": ["<", cutoff_date]
        }
    )

    for rfq in old_drafts:
        try:
            frappe.delete_doc("RFQ", rfq.name, ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                f"Error deleting old draft RFQ {rfq.name}: {str(e)}",
                "RFQ Cleanup Task"
            )

    frappe.db.commit()
    frappe.logger().info(f"Cleaned up {len(old_drafts)} old draft RFQs")
