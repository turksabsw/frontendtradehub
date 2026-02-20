# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Subscription Tasks Module

Scheduled background tasks for subscription management:
- check_expiring_subscriptions: Daily check for subscriptions about to expire
- process_grace_periods: Daily processing of grace period transitions
- suspend_overdue_subscriptions: Daily suspension of expired grace periods
- send_renewal_reminders: Daily renewal reminder notifications
- reset_daily_limits: Daily reset of API call counters
- reset_monthly_limits: Monthly reset of order counters
"""

import frappe
from frappe import _
from frappe.utils import nowdate, add_days, getdate, now_datetime, date_diff


def check_expiring_subscriptions():
    """
    Check for subscriptions that are about to expire and send reminders.
    Runs daily to identify subscriptions expiring within 7 days.
    """
    frappe.logger().info("Running check_expiring_subscriptions task")

    today = getdate(nowdate())
    warning_days = [7, 3, 1]  # Send warnings 7, 3, and 1 day(s) before expiry

    for days in warning_days:
        expiry_date = add_days(today, days)

        # Find subscriptions expiring on this date that haven't had renewal reminder sent
        subscriptions = frappe.get_all(
            "Subscription",
            filters={
                "status": ["in", ["Active", "Trial"]],
                "end_date": expiry_date,
                "auto_renew": 0,  # Only non-auto-renew subscriptions
                "renewal_reminder_sent": 0
            },
            fields=["name", "seller_profile", "buyer_profile", "organization",
                    "subscriber_type", "package_name", "end_date"]
        )

        for sub in subscriptions:
            try:
                send_expiry_warning(sub, days)

                # Mark as reminder sent if this is the first (7-day) warning
                if days == 7:
                    frappe.db.set_value(
                        "Subscription", sub.name,
                        {
                            "renewal_reminder_sent": 1,
                            "renewal_reminder_date": today
                        },
                        update_modified=False
                    )
            except Exception as e:
                frappe.log_error(
                    message=f"Error sending expiry warning for {sub.name}: {str(e)}",
                    title="Subscription Expiry Warning Error"
                )

    frappe.db.commit()
    frappe.logger().info(f"Completed check_expiring_subscriptions task")


def process_grace_periods():
    """
    Process subscriptions that need to enter grace period.
    Runs daily to transition expired subscriptions to grace period status.
    """
    frappe.logger().info("Running process_grace_periods task")

    today = getdate(nowdate())
    processed_count = 0

    # Find subscriptions that have expired (end_date < today) and are still active
    expired_subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": ["in", ["Active", "Pending Payment"]],
            "end_date": ["<", today],
            "auto_renew": 0  # Only handle non-auto-renew subscriptions here
        },
        fields=["name", "seller_profile", "buyer_profile", "organization",
                "subscriber_type", "package_name", "end_date", "grace_period_days"]
    )

    for sub_data in expired_subscriptions:
        try:
            subscription = frappe.get_doc("Subscription", sub_data.name)

            # Start grace period
            grace_days = subscription.grace_period_days or 7
            subscription.status = "Grace Period"
            subscription.in_grace_period = 1
            subscription.grace_period_start_date = today
            subscription.grace_period_end_date = add_days(today, grace_days)
            subscription.save(ignore_permissions=True)

            # Send grace period notification
            send_grace_period_notification(subscription)

            processed_count += 1

            frappe.logger().info(
                f"Subscription {sub_data.name} entered grace period until {subscription.grace_period_end_date}"
            )

        except Exception as e:
            frappe.log_error(
                message=f"Error processing grace period for {sub_data.name}: {str(e)}",
                title="Grace Period Processing Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed process_grace_periods task: {processed_count} subscriptions processed")

    return processed_count


def suspend_overdue_subscriptions():
    """
    Suspend subscriptions whose grace period has expired.
    Runs daily to identify and suspend overdue subscriptions, disabling their API access.
    """
    frappe.logger().info("Running suspend_overdue_subscriptions task")

    today = getdate(nowdate())
    suspended_count = 0

    # Find subscriptions in grace period that have expired
    overdue_subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": "Grace Period",
            "grace_period_end_date": ["<", today]
        },
        fields=["name", "seller_profile", "buyer_profile", "organization",
                "subscriber_type", "package_name", "outstanding_amount"]
    )

    for sub_data in overdue_subscriptions:
        try:
            subscription = frappe.get_doc("Subscription", sub_data.name)

            # Suspend the subscription
            subscription.status = "Suspended"
            subscription.is_suspended = 1
            subscription.is_active = 0
            subscription.api_access_enabled = 0  # Critical: Disable API access
            subscription.in_grace_period = 0
            subscription.suspended_at = now_datetime()
            subscription.suspended_reason = _("Grace period expired without payment")
            subscription.suspension_type = "Payment Overdue"
            subscription.save(ignore_permissions=True)

            # Disable API access for the subscriber
            disable_subscriber_api_access(subscription)

            # Send suspension notification
            send_suspension_notification(subscription)

            suspended_count += 1

            frappe.logger().info(
                f"Subscription {sub_data.name} suspended - grace period expired"
            )

        except Exception as e:
            frappe.log_error(
                message=f"Error suspending subscription {sub_data.name}: {str(e)}",
                title="Subscription Suspension Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed suspend_overdue_subscriptions task: {suspended_count} subscriptions suspended")

    return suspended_count


def send_grace_period_warnings():
    """
    Send warnings to subscriptions in grace period before suspension.
    Runs daily to send 3-day and 1-day warnings before suspension.
    """
    frappe.logger().info("Running send_grace_period_warnings task")

    today = getdate(nowdate())
    warning_days = [3, 1]  # Send warnings 3 days and 1 day before suspension
    warnings_sent = 0

    for days in warning_days:
        warning_date = add_days(today, days)

        # Find subscriptions in grace period ending on the warning date
        subscriptions = frappe.get_all(
            "Subscription",
            filters={
                "status": "Grace Period",
                "grace_period_end_date": warning_date,
                "suspension_warning_sent": 0 if days == 3 else 1  # First warning at 3 days
            },
            fields=["name", "seller_profile", "buyer_profile", "organization",
                    "subscriber_type", "package_name", "grace_period_end_date",
                    "outstanding_amount"]
        )

        for sub in subscriptions:
            try:
                send_suspension_warning(sub, days)

                # Mark warning as sent
                if days == 3:
                    frappe.db.set_value(
                        "Subscription", sub.name,
                        "grace_period_warning_sent", 1,
                        update_modified=False
                    )
                elif days == 1:
                    frappe.db.set_value(
                        "Subscription", sub.name,
                        "suspension_warning_sent", 1,
                        update_modified=False
                    )

                warnings_sent += 1

            except Exception as e:
                frappe.log_error(
                    message=f"Error sending grace period warning for {sub.name}: {str(e)}",
                    title="Grace Period Warning Error"
                )

    frappe.db.commit()
    frappe.logger().info(f"Completed send_grace_period_warnings task: {warnings_sent} warnings sent")

    return warnings_sent


def process_auto_renewals():
    """
    Process auto-renewal for subscriptions.
    Runs daily to attempt automatic renewal of subscriptions with auto_renew enabled.
    """
    frappe.logger().info("Running process_auto_renewals task")

    today = getdate(nowdate())
    processed_count = 0

    # Find subscriptions due for renewal
    subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": ["in", ["Active", "Trial"]],
            "auto_renew": 1,
            "end_date": ["<=", today],
            "failed_renewal_attempts": ["<", 3]  # Max 3 attempts
        },
        fields=["name", "seller_profile", "buyer_profile", "organization",
                "subscriber_type", "subscription_package", "current_price"]
    )

    for sub_data in subscriptions:
        try:
            subscription = frappe.get_doc("Subscription", sub_data.name)

            # Attempt to process payment (placeholder - integrate with payment gateway)
            payment_successful = attempt_subscription_payment(subscription)

            if payment_successful:
                # Renew the subscription
                subscription.renew(payment_received=True)
                frappe.logger().info(f"Subscription {sub_data.name} renewed successfully")
            else:
                # Payment failed - increment failure count
                subscription.failed_renewal_attempts = (subscription.failed_renewal_attempts or 0) + 1
                subscription.last_renewal_attempt = now_datetime()
                subscription.renewal_failure_reason = _("Payment processing failed")

                if subscription.failed_renewal_attempts >= 3:
                    # Max attempts reached - move to pending payment
                    subscription.status = "Pending Payment"
                    subscription.auto_renew = 0
                    send_payment_failure_notification(subscription)

                subscription.save(ignore_permissions=True)

            processed_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error processing auto-renewal for {sub_data.name}: {str(e)}",
                title="Auto-Renewal Processing Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed process_auto_renewals task: {processed_count} subscriptions processed")

    return processed_count


def reset_daily_api_limits():
    """
    Reset daily API call counters for all subscriptions.
    Runs daily at midnight to reset the current_day_api_calls counter.
    """
    frappe.logger().info("Running reset_daily_api_limits task")

    # Reset all daily API call counters
    frappe.db.sql("""
        UPDATE `tabSubscription`
        SET current_day_api_calls = 0
        WHERE current_day_api_calls > 0
    """)

    frappe.db.commit()
    frappe.logger().info("Completed reset_daily_api_limits task")


def reset_monthly_order_limits():
    """
    Reset monthly order counters for all subscriptions.
    Runs on the 1st of each month to reset the current_month_orders counter.
    """
    frappe.logger().info("Running reset_monthly_order_limits task")

    # Reset all monthly order counters
    frappe.db.sql("""
        UPDATE `tabSubscription`
        SET current_month_orders = 0
        WHERE current_month_orders > 0
    """)

    frappe.db.commit()
    frappe.logger().info("Completed reset_monthly_order_limits task")


def check_trial_expirations():
    """
    Check for expiring trial subscriptions and notify users.
    Runs daily to identify trials ending soon and prompt conversion.
    """
    frappe.logger().info("Running check_trial_expirations task")

    today = getdate(nowdate())
    processed_count = 0

    # Find trials expiring in the next 3 days
    for days in [3, 1]:
        expiry_date = add_days(today, days)

        trials = frappe.get_all(
            "Subscription",
            filters={
                "status": "Trial",
                "trial_end_date": expiry_date
            },
            fields=["name", "seller_profile", "buyer_profile", "organization",
                    "subscriber_type", "package_name", "trial_end_date"]
        )

        for trial in trials:
            try:
                send_trial_expiry_notification(trial, days)
                processed_count += 1
            except Exception as e:
                frappe.log_error(
                    message=f"Error sending trial expiry notification for {trial.name}: {str(e)}",
                    title="Trial Expiry Notification Error"
                )

    # Convert expired trials to pending payment or expired
    expired_trials = frappe.get_all(
        "Subscription",
        filters={
            "status": "Trial",
            "trial_end_date": ["<", today]
        },
        fields=["name", "auto_renew", "subscription_package"]
    )

    for trial in expired_trials:
        try:
            subscription = frappe.get_doc("Subscription", trial.name)

            if trial.auto_renew:
                # Auto-renew: attempt payment
                subscription.status = "Pending Payment"
            else:
                # No auto-renew: expire the trial
                subscription.status = "Expired"
                subscription.is_active = 0
                subscription.api_access_enabled = 0

            subscription.save(ignore_permissions=True)
            processed_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error processing expired trial {trial.name}: {str(e)}",
                title="Trial Expiry Processing Error"
            )

    frappe.db.commit()
    frappe.logger().info(f"Completed check_trial_expirations task: {processed_count} trials processed")

    return processed_count


# ==================== Helper Functions ====================

def disable_subscriber_api_access(subscription):
    """
    Disable API access for the subscriber associated with the subscription.
    Updates related Premium Seller/Buyer records.
    """
    try:
        if subscription.subscriber_type == "Seller" and subscription.seller_profile:
            # Update Premium Seller if exists
            premium_seller = frappe.db.get_value(
                "Premium Seller",
                {"seller_profile": subscription.seller_profile},
                "name"
            )
            if premium_seller:
                frappe.db.set_value(
                    "Premium Seller", premium_seller,
                    {
                        "subscription_status": "Suspended",
                        "api_access": 0
                    },
                    update_modified=False
                )

        elif subscription.subscriber_type == "Buyer" and subscription.buyer_profile:
            # Update Premium Buyer if exists
            premium_buyer = frappe.db.get_value(
                "Premium Buyer",
                {"buyer_profile": subscription.buyer_profile},
                "name"
            )
            if premium_buyer:
                frappe.db.set_value(
                    "Premium Buyer", premium_buyer,
                    {
                        "subscription_status": "Suspended",
                        "api_access": 0
                    },
                    update_modified=False
                )

    except Exception as e:
        frappe.log_error(
            message=f"Error disabling API access for subscription {subscription.name}: {str(e)}",
            title="API Access Disable Error"
        )


def enable_subscriber_api_access(subscription):
    """
    Re-enable API access for the subscriber associated with the subscription.
    Called when a subscription is reactivated.
    """
    try:
        if subscription.subscriber_type == "Seller" and subscription.seller_profile:
            premium_seller = frappe.db.get_value(
                "Premium Seller",
                {"seller_profile": subscription.seller_profile},
                "name"
            )
            if premium_seller:
                frappe.db.set_value(
                    "Premium Seller", premium_seller,
                    {
                        "subscription_status": "Active",
                        "api_access": 1
                    },
                    update_modified=False
                )

        elif subscription.subscriber_type == "Buyer" and subscription.buyer_profile:
            premium_buyer = frappe.db.get_value(
                "Premium Buyer",
                {"buyer_profile": subscription.buyer_profile},
                "name"
            )
            if premium_buyer:
                frappe.db.set_value(
                    "Premium Buyer", premium_buyer,
                    {
                        "subscription_status": "Active",
                        "api_access": 1
                    },
                    update_modified=False
                )

    except Exception as e:
        frappe.log_error(
            message=f"Error enabling API access for subscription {subscription.name}: {str(e)}",
            title="API Access Enable Error"
        )


def attempt_subscription_payment(subscription):
    """
    Attempt to process payment for subscription renewal.
    This is a placeholder for actual payment gateway integration.

    Returns:
        bool: True if payment successful, False otherwise
    """
    # TODO: Integrate with actual payment gateway (Stripe, PayTR, etc.)
    # For now, this is a placeholder that always returns False
    # to simulate payment failure and trigger the grace period flow

    frappe.logger().info(
        f"Payment attempt for subscription {subscription.name} - "
        f"Amount: {subscription.current_price}"
    )

    # Return False to simulate payment failure
    # In production, this would call the payment gateway API
    return False


def send_expiry_warning(subscription, days_remaining):
    """Send expiry warning notification to subscriber."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Subscription Expiring in {0} Day(s)").format(days_remaining)
        message = _(
            "Your {0} subscription will expire in {1} day(s) on {2}. "
            "Please renew to continue using our services."
        ).format(
            subscription.package_name,
            days_remaining,
            subscription.end_date
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending expiry warning: {str(e)}",
            title="Expiry Warning Email Error"
        )


def send_grace_period_notification(subscription):
    """Send notification when subscription enters grace period."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Subscription Payment Overdue - Grace Period Started")
        message = _(
            "Your {0} subscription payment is overdue. You have been given a grace period "
            "until {1} to make payment. After this date, your subscription will be suspended "
            "and API access will be disabled."
        ).format(
            subscription.package_name,
            subscription.grace_period_end_date
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending grace period notification: {str(e)}",
            title="Grace Period Notification Error"
        )


def send_suspension_warning(subscription, days_remaining):
    """Send warning about upcoming suspension."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Urgent: Subscription Will Be Suspended in {0} Day(s)").format(days_remaining)
        message = _(
            "Your {0} subscription will be SUSPENDED in {1} day(s) on {2} "
            "due to non-payment. Outstanding amount: {3}. "
            "Please make payment immediately to avoid service interruption."
        ).format(
            subscription.package_name,
            days_remaining,
            subscription.grace_period_end_date,
            subscription.outstanding_amount or 0
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending suspension warning: {str(e)}",
            title="Suspension Warning Email Error"
        )


def send_suspension_notification(subscription):
    """Send notification when subscription is suspended."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Subscription Suspended - API Access Disabled")
        message = _(
            "Your {0} subscription has been suspended due to non-payment. "
            "Your API access has been disabled. To reactivate your subscription, "
            "please contact support or make payment of the outstanding amount: {1}."
        ).format(
            subscription.package_name,
            subscription.outstanding_amount or 0
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending suspension notification: {str(e)}",
            title="Suspension Notification Error"
        )


def send_payment_failure_notification(subscription):
    """Send notification when auto-renewal payment fails."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Subscription Renewal Payment Failed")
        message = _(
            "We were unable to process your {0} subscription renewal payment. "
            "Please update your payment method or make a manual payment to avoid "
            "service interruption. Amount due: {1}."
        ).format(
            subscription.package_name,
            subscription.current_price or 0
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending payment failure notification: {str(e)}",
            title="Payment Failure Notification Error"
        )


def send_trial_expiry_notification(subscription, days_remaining):
    """Send notification for expiring trial."""
    try:
        recipient = get_subscriber_email(subscription)
        if not recipient:
            return

        subject = _("Trial Ending in {0} Day(s) - Upgrade Now").format(days_remaining)
        message = _(
            "Your {0} trial subscription will expire in {1} day(s) on {2}. "
            "Upgrade to a paid plan to continue enjoying our premium features and services."
        ).format(
            subscription.package_name,
            days_remaining,
            subscription.trial_end_date
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=message,
            now=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error sending trial expiry notification: {str(e)}",
            title="Trial Expiry Notification Error"
        )


def get_subscriber_email(subscription):
    """Get the email address for the subscriber."""
    try:
        if hasattr(subscription, 'subscriber_type'):
            sub_type = subscription.subscriber_type
        else:
            sub_type = subscription.get('subscriber_type')

        if sub_type == "Seller":
            seller_profile = subscription.seller_profile if hasattr(subscription, 'seller_profile') else subscription.get('seller_profile')
            if seller_profile:
                return frappe.db.get_value("Seller Profile", seller_profile, "email") or \
                       frappe.db.get_value("Seller Profile", seller_profile, "contact_email")

        elif sub_type == "Buyer":
            buyer_profile = subscription.buyer_profile if hasattr(subscription, 'buyer_profile') else subscription.get('buyer_profile')
            if buyer_profile:
                return frappe.db.get_value("User", buyer_profile, "email")

        elif sub_type == "Organization":
            organization = subscription.organization if hasattr(subscription, 'organization') else subscription.get('organization')
            if organization:
                return frappe.db.get_value("Organization", organization, "email") or \
                       frappe.db.get_value("Organization", organization, "contact_email")

    except Exception as e:
        frappe.log_error(
            message=f"Error getting subscriber email: {str(e)}",
            title="Subscriber Email Lookup Error"
        )

    return None


# ==================== API Methods ====================

@frappe.whitelist()
def run_subscription_maintenance():
    """
    Run all subscription maintenance tasks manually.
    This is a whitelisted method that can be called by administrators.
    """
    if not frappe.has_permission("Subscription", "write"):
        frappe.throw(_("You don't have permission to run subscription maintenance"))

    results = {
        "grace_periods_processed": process_grace_periods(),
        "subscriptions_suspended": suspend_overdue_subscriptions(),
        "warnings_sent": send_grace_period_warnings()
    }

    frappe.msgprint(_(
        "Subscription maintenance completed: "
        "{0} grace periods processed, "
        "{1} subscriptions suspended, "
        "{2} warnings sent"
    ).format(
        results["grace_periods_processed"],
        results["subscriptions_suspended"],
        results["warnings_sent"]
    ))

    return results


@frappe.whitelist()
def get_subscription_statistics():
    """
    Get subscription statistics for dashboard.
    Returns counts of subscriptions by status.
    """
    stats = {}

    for status in ["Draft", "Trial", "Active", "Pending Payment", "Grace Period",
                   "Suspended", "Cancelled", "Expired"]:
        count = frappe.db.count("Subscription", filters={"status": status})
        stats[status] = count

    stats["total"] = sum(stats.values())
    stats["active_total"] = stats["Trial"] + stats["Active"]
    stats["at_risk"] = stats["Pending Payment"] + stats["Grace Period"]

    return stats


@frappe.whitelist()
def check_and_update_subscription_status(subscription_name):
    """
    Check and update the status of a specific subscription based on current date.
    Useful for testing or manual intervention.
    """
    subscription = frappe.get_doc("Subscription", subscription_name)
    today = getdate(nowdate())

    old_status = subscription.status

    # Check if subscription should enter grace period
    if subscription.status in ["Active", "Pending Payment"]:
        if subscription.end_date and getdate(subscription.end_date) < today:
            if not subscription.auto_renew:
                subscription.status = "Grace Period"
                subscription.in_grace_period = 1
                subscription.grace_period_start_date = today
                grace_days = subscription.grace_period_days or 7
                subscription.grace_period_end_date = add_days(today, grace_days)

    # Check if grace period has expired
    elif subscription.status == "Grace Period":
        if subscription.grace_period_end_date and getdate(subscription.grace_period_end_date) < today:
            subscription.status = "Suspended"
            subscription.is_suspended = 1
            subscription.api_access_enabled = 0
            subscription.in_grace_period = 0
            subscription.suspended_at = now_datetime()
            subscription.suspended_reason = _("Grace period expired without payment")
            subscription.suspension_type = "Payment Overdue"

    # Check if trial has expired
    elif subscription.status == "Trial":
        if subscription.trial_end_date and getdate(subscription.trial_end_date) < today:
            if subscription.auto_renew:
                subscription.status = "Pending Payment"
            else:
                subscription.status = "Expired"
                subscription.is_active = 0
                subscription.api_access_enabled = 0

    if subscription.status != old_status:
        subscription.save(ignore_permissions=True)
        frappe.msgprint(_(
            "Subscription status changed from {0} to {1}"
        ).format(old_status, subscription.status))

    return {
        "old_status": old_status,
        "new_status": subscription.status,
        "changed": subscription.status != old_status
    }
