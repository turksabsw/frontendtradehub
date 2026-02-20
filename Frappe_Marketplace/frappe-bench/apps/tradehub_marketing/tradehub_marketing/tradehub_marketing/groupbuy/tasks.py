# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy Scheduled Tasks

Deadline checking, expiration, and completion processing.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, add_days, getdate, today


def check_deadlines():
    """
    Hourly job: Check group buy deadlines.

    - Send reminders for expiring group buys
    - Expire unfunded group buys past deadline
    """
    now = now_datetime()

    # Check for group buys expiring in 24 hours
    reminder_start = add_to_date(now, hours=23)
    reminder_end = add_to_date(now, hours=25)

    expiring_soon = frappe.get_all(
        "Group Buy",
        filters={
            "status": "Active",
            "end_date": ["between", [reminder_start, reminder_end]]
        },
        fields=["name", "title", "current_quantity", "target_quantity"]
    )

    for gb in expiring_soon:
        _send_deadline_reminder(gb)


def expire_unfunded():
    """
    Hourly job: Expire group buys that didn't reach target by deadline.
    """
    now = now_datetime()

    expired = frappe.get_all(
        "Group Buy",
        filters={
            "status": "Active",
            "end_date": ["<", now]
        },
        fields=["name", "title", "current_quantity", "target_quantity"]
    )

    for gb in expired:
        try:
            doc = frappe.get_doc("Group Buy", gb.name)

            if doc.current_quantity >= doc.target_quantity:
                # Target was reached, mark as funded
                doc.status = "Funded"
            else:
                # Target not reached, expire
                doc.status = "Expired"
                _notify_expiration(doc)
                _refund_commitments(doc.name)

            doc.save(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(
                f"Error processing expired group buy {gb.name}: {str(e)}",
                "Group Buy Expiration"
            )


def process_completed():
    """
    Daily job: Process completed/funded group buys.

    - Initiate payment collection
    - Create orders for sellers
    """
    funded = frappe.get_all(
        "Group Buy",
        filters={"status": "Funded"},
        fields=["name"]
    )

    for gb in funded:
        try:
            _process_group_buy_completion(gb.name)
        except Exception as e:
            frappe.log_error(
                f"Error processing completion for {gb.name}: {str(e)}",
                "Group Buy Completion"
            )


def send_reminders():
    """
    Daily job: Send reminders to increase participation.

    - Remind buyers who viewed but didn't commit
    - Remind about group buys needing more participants
    """
    # Find active group buys that are 25-75% funded
    active_gbs = frappe.get_all(
        "Group Buy",
        filters={"status": "Active"},
        fields=["name", "title", "current_quantity", "target_quantity", "seller"]
    )

    for gb in active_gbs:
        progress = (gb.current_quantity / gb.target_quantity * 100) if gb.target_quantity > 0 else 0

        if 25 <= progress <= 75:
            # Good momentum but not there yet - remind participants
            _send_progress_update(gb)


def _send_deadline_reminder(gb: dict):
    """Send reminder about expiring group buy."""
    # Get all committed buyers
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": gb.name, "status": "Active"},
        fields=["buyer"]
    )

    for c in commitments:
        buyer_user = frappe.db.get_value("Buyer Profile", c.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy",
                "document_name": gb.name,
                "subject": _("Group Buy Ending Soon!"),
                "email_content": _(
                    "The group buy '{0}' ends in 24 hours. "
                    "Current progress: {1:.0f}% ({2}/{3} units)"
                ).format(
                    gb.title,
                    (gb.current_quantity / gb.target_quantity * 100) if gb.target_quantity else 0,
                    gb.current_quantity,
                    gb.target_quantity
                )
            }).insert(ignore_permissions=True)


def _notify_expiration(gb):
    """Notify participants about group buy expiration."""
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": gb.name, "status": "Active"},
        fields=["buyer"]
    )

    for c in commitments:
        buyer_user = frappe.db.get_value("Buyer Profile", c.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy",
                "document_name": gb.name,
                "subject": _("Group Buy Expired"),
                "email_content": _(
                    "Unfortunately, the group buy '{0}' did not reach its target "
                    "and has expired. Your commitment will be cancelled and any "
                    "held funds will be released."
                ).format(gb.title)
            }).insert(ignore_permissions=True)


def _refund_commitments(group_buy_name: str):
    """
    Cancel all commitments and process refunds for expired group buy.
    """
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name, "status": "Active"},
        fields=["name"]
    )

    for c in commitments:
        frappe.db.set_value(
            "Group Buy Commitment",
            c.name,
            {
                "status": "Refunded",
                "refunded_at": now_datetime()
            }
        )

    frappe.db.commit()


def _process_group_buy_completion(group_buy_name: str):
    """
    Process a completed group buy - collect payments and create orders.
    """
    from tradehub_marketing.tradehub_marketing.groupbuy.pricing import check_profitability

    gb = frappe.get_doc("Group Buy", group_buy_name)

    # Verify profitability
    profitability = check_profitability(group_buy_name)
    if not profitability["is_profitable"]:
        frappe.log_error(
            f"Group buy {group_buy_name} is not profitable. Manual review required.",
            "Group Buy Completion"
        )
        return

    # Get all active commitments
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name, "status": "Active"},
        fields=["name", "buyer", "quantity", "unit_price", "total_amount"]
    )

    # Create payment intents for each commitment
    for c in commitments:
        try:
            # Create payment record
            payment = frappe.get_doc({
                "doctype": "Group Buy Payment",
                "group_buy": group_buy_name,
                "commitment": c.name,
                "buyer": c.buyer,
                "amount": c.total_amount,
                "status": "Pending"
            })
            payment.insert(ignore_permissions=True)

            # Update commitment status
            frappe.db.set_value(
                "Group Buy Commitment",
                c.name,
                "status",
                "Payment Pending"
            )

            # Send payment notification
            _send_payment_notification(c.buyer, payment.name, c.total_amount)

        except Exception as e:
            frappe.log_error(
                f"Error creating payment for commitment {c.name}: {str(e)}",
                "Group Buy Payment"
            )

    # Update group buy status
    gb.status = "Completed"
    gb.save(ignore_permissions=True)

    frappe.db.commit()


def _send_payment_notification(buyer: str, payment_name: str, amount: float):
    """Send payment collection notification to buyer."""
    buyer_user = frappe.db.get_value("Buyer Profile", buyer, "user")
    if buyer_user:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": buyer_user,
            "type": "Alert",
            "document_type": "Group Buy Payment",
            "document_name": payment_name,
            "subject": _("Payment Required for Group Buy"),
            "email_content": _(
                "Your group buy has been confirmed! "
                "Please complete payment of {0} to finalize your order."
            ).format(amount)
        }).insert(ignore_permissions=True)


def _send_progress_update(gb: dict):
    """Send progress update to encourage more participation."""
    progress = (gb.current_quantity / gb.target_quantity * 100) if gb.target_quantity > 0 else 0
    remaining = gb.target_quantity - gb.current_quantity

    # Notify seller
    seller_user = frappe.db.get_value("Seller Profile", gb.seller, "user")
    if seller_user:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": seller_user,
            "type": "Alert",
            "document_type": "Group Buy",
            "document_name": gb.name,
            "subject": _("Group Buy Progress Update"),
            "email_content": _(
                "Your group buy '{0}' is {1:.0f}% funded! "
                "Only {2} more units needed to reach the target."
            ).format(gb.title, progress, remaining)
        }).insert(ignore_permissions=True)
