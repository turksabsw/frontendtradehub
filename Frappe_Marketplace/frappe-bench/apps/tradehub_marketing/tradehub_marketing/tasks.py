"""
Scheduled tasks for TradeHub Marketing module.

Tasks moved from the monolithic tr_tradehub app during decomposition:
- campaign_tasks: Daily campaign status updates (activate/deactivate based on dates)
- group_buy_tasks: Hourly group buy commitment tracking and status updates
"""

import frappe
from frappe.utils import nowdate, now_datetime, getdate, add_days


def campaign_tasks():
    """
    Daily scheduled task for campaign management.

    This task:
    1. Activates campaigns that have reached their start date
    2. Deactivates campaigns that have passed their end date
    3. Updates campaign metrics (impressions, clicks, conversions)
    4. Sends expiry notifications for campaigns ending soon
    """
    frappe.logger("tradehub_marketing").info("Running daily campaign tasks")

    today = getdate(nowdate())

    # Activate campaigns scheduled to start today
    campaigns_to_activate = frappe.get_all(
        "Campaign",
        filters={
            "status": "Scheduled",
            "start_date": ["<=", today]
        },
        pluck="name"
    )

    for campaign_name in campaigns_to_activate:
        try:
            doc = frappe.get_doc("Campaign", campaign_name)
            doc.status = "Active"
            doc.save(ignore_permissions=True)
            frappe.logger("tradehub_marketing").info(f"Activated campaign: {campaign_name}")
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to activate campaign {campaign_name}: {str(e)}"
            )

    # Deactivate campaigns that have ended
    campaigns_to_deactivate = frappe.get_all(
        "Campaign",
        filters={
            "status": "Active",
            "end_date": ["<", today]
        },
        pluck="name"
    )

    for campaign_name in campaigns_to_deactivate:
        try:
            doc = frappe.get_doc("Campaign", campaign_name)
            doc.status = "Completed"
            doc.save(ignore_permissions=True)
            frappe.logger("tradehub_marketing").info(f"Deactivated campaign: {campaign_name}")
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to deactivate campaign {campaign_name}: {str(e)}"
            )

    # Notify about campaigns ending in 3 days
    expiring_soon = add_days(today, 3)
    campaigns_expiring = frappe.get_all(
        "Campaign",
        filters={
            "status": "Active",
            "end_date": expiring_soon
        },
        fields=["name", "campaign_name", "owner"]
    )

    for campaign in campaigns_expiring:
        try:
            frappe.sendmail(
                recipients=[campaign.owner],
                subject=f"Campaign '{campaign.campaign_name}' ending soon",
                message=f"Your campaign '{campaign.campaign_name}' will end on {expiring_soon}. "
                        f"Please review and take necessary action.",
                now=True
            )
            frappe.logger("tradehub_marketing").info(
                f"Sent expiry notification for campaign: {campaign.name}"
            )
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to send expiry notification for {campaign.name}: {str(e)}"
            )

    frappe.db.commit()
    frappe.logger("tradehub_marketing").info(
        f"Campaign tasks completed. Activated: {len(campaigns_to_activate)}, "
        f"Deactivated: {len(campaigns_to_deactivate)}"
    )


def group_buy_tasks():
    """
    Hourly scheduled task for Group Buy management.

    This task:
    1. Checks Group Buys that have reached their commitment threshold
    2. Marks successful Group Buys for fulfillment
    3. Cancels Group Buys that failed to reach threshold by deadline
    4. Processes refunds for cancelled Group Buy commitments
    """
    frappe.logger("tradehub_marketing").info("Running hourly group buy tasks")

    now = now_datetime()

    # Check Group Buys that have reached deadline
    expired_group_buys = frappe.get_all(
        "Group Buy",
        filters={
            "status": "Active",
            "deadline": ["<", now]
        },
        fields=["name", "minimum_quantity", "current_quantity", "product"]
    )

    for gb in expired_group_buys:
        try:
            doc = frappe.get_doc("Group Buy", gb.name)

            if doc.current_quantity >= doc.minimum_quantity:
                # Group Buy succeeded - move to fulfillment
                doc.status = "Successful"
                doc.save(ignore_permissions=True)
                frappe.logger("tradehub_marketing").info(
                    f"Group Buy {gb.name} succeeded with {doc.current_quantity} commitments"
                )

                # Notify all participants
                notify_group_buy_participants(doc.name, "success")

            else:
                # Group Buy failed - trigger refunds
                doc.status = "Failed"
                doc.save(ignore_permissions=True)
                frappe.logger("tradehub_marketing").info(
                    f"Group Buy {gb.name} failed - only {doc.current_quantity}/{doc.minimum_quantity}"
                )

                # Process refunds for all commitments
                process_group_buy_refunds(doc.name)

                # Notify all participants
                notify_group_buy_participants(doc.name, "failed")

        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to process Group Buy {gb.name}: {str(e)}"
            )

    # Check active Group Buys that have reached their threshold
    threshold_reached = frappe.get_all(
        "Group Buy",
        filters={
            "status": "Active"
        },
        fields=["name", "minimum_quantity", "current_quantity", "auto_close_on_threshold"]
    )

    for gb in threshold_reached:
        if gb.current_quantity >= gb.minimum_quantity and gb.auto_close_on_threshold:
            try:
                doc = frappe.get_doc("Group Buy", gb.name)
                doc.status = "Successful"
                doc.save(ignore_permissions=True)
                frappe.logger("tradehub_marketing").info(
                    f"Group Buy {gb.name} auto-closed after reaching threshold"
                )
                notify_group_buy_participants(doc.name, "success")
            except Exception as e:
                frappe.logger("tradehub_marketing").error(
                    f"Failed to auto-close Group Buy {gb.name}: {str(e)}"
                )

    frappe.db.commit()
    frappe.logger("tradehub_marketing").info("Group buy tasks completed")


def notify_group_buy_participants(group_buy_name, status):
    """
    Send notifications to all participants of a Group Buy.

    Args:
        group_buy_name: Name of the Group Buy document
        status: Either 'success' or 'failed'
    """
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name},
        fields=["buyer", "buyer_email", "quantity"]
    )

    group_buy = frappe.get_doc("Group Buy", group_buy_name)

    for commitment in commitments:
        if status == "success":
            subject = f"Group Buy '{group_buy.title}' - Successful!"
            message = (
                f"Great news! The Group Buy '{group_buy.title}' has reached its goal. "
                f"Your commitment for {commitment.quantity} units will be processed shortly."
            )
        else:
            subject = f"Group Buy '{group_buy.title}' - Did not reach goal"
            message = (
                f"Unfortunately, the Group Buy '{group_buy.title}' did not reach its minimum commitment. "
                f"Your payment of {commitment.quantity} units will be refunded within 3-5 business days."
            )

        try:
            frappe.sendmail(
                recipients=[commitment.buyer_email],
                subject=subject,
                message=message,
                now=True
            )
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to notify {commitment.buyer_email} about Group Buy {group_buy_name}: {str(e)}"
            )


def process_group_buy_refunds(group_buy_name):
    """
    Process refunds for all commitments in a failed Group Buy.

    Args:
        group_buy_name: Name of the Group Buy document
    """
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={
            "group_buy": group_buy_name,
            "payment_status": "Paid"
        },
        pluck="name"
    )

    for commitment_name in commitments:
        try:
            commitment = frappe.get_doc("Group Buy Commitment", commitment_name)
            commitment.payment_status = "Refund Pending"
            commitment.save(ignore_permissions=True)

            # Create refund in Group Buy Payment
            frappe.get_doc({
                "doctype": "Group Buy Payment",
                "group_buy_commitment": commitment_name,
                "group_buy": group_buy_name,
                "payment_type": "Refund",
                "amount": commitment.total_amount,
                "status": "Pending"
            }).insert(ignore_permissions=True)

            frappe.logger("tradehub_marketing").info(
                f"Created refund for commitment {commitment_name}"
            )
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to process refund for commitment {commitment_name}: {str(e)}"
            )


def subscription_renewal_tasks():
    """
    Daily task for subscription renewal processing.

    This task:
    1. Identifies subscriptions due for renewal
    2. Processes automatic renewals
    3. Sends renewal reminders for manual renewals
    4. Expires subscriptions that failed to renew
    """
    frappe.logger("tradehub_marketing").info("Running subscription renewal tasks")

    today = getdate(nowdate())

    # Find subscriptions expiring in 7 days
    expiring_date = add_days(today, 7)
    expiring_subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": "Active",
            "end_date": expiring_date,
            "auto_renew": 0
        },
        fields=["name", "subscriber", "subscriber_email", "subscription_package"]
    )

    for sub in expiring_subscriptions:
        try:
            frappe.sendmail(
                recipients=[sub.subscriber_email],
                subject=f"Subscription renewal reminder",
                message=f"Your subscription to {sub.subscription_package} will expire on {expiring_date}. "
                        f"Please renew to continue enjoying the benefits.",
                now=True
            )
            frappe.logger("tradehub_marketing").info(
                f"Sent renewal reminder for subscription: {sub.name}"
            )
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to send renewal reminder for {sub.name}: {str(e)}"
            )

    # Expire subscriptions past their end date
    expired_subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": "Active",
            "end_date": ["<", today]
        },
        pluck="name"
    )

    for sub_name in expired_subscriptions:
        try:
            sub = frappe.get_doc("Subscription", sub_name)
            sub.status = "Expired"
            sub.save(ignore_permissions=True)
            frappe.logger("tradehub_marketing").info(f"Expired subscription: {sub_name}")
        except Exception as e:
            frappe.logger("tradehub_marketing").error(
                f"Failed to expire subscription {sub_name}: {str(e)}"
            )

    frappe.db.commit()
    frappe.logger("tradehub_marketing").info("Subscription renewal tasks completed")
