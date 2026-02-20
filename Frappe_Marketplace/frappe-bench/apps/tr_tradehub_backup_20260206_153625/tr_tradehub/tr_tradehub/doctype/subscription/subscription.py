# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, add_days, getdate, now_datetime, date_diff, get_datetime


class Subscription(Document):
    """
    Subscription DocType for managing seller/buyer subscriptions with grace period support.

    Key Features:
    - Subscription lifecycle management (Draft, Trial, Active, Grace Period, Suspended, Cancelled, Expired)
    - Grace period tracking with configurable duration
    - Automatic status transitions based on dates
    - API access control based on subscription status
    - Package limits enforcement (products, orders, API calls)
    - Upgrade/downgrade support with proration
    """

    def before_insert(self):
        """Set defaults before inserting a new subscription."""
        self.set_created_info()
        self.set_defaults_from_package()

    def before_save(self):
        """Validate and update fields before saving."""
        self.validate_subscriber()
        self.validate_dates()
        self.set_tenant_from_subscriber()
        self.update_status_flags()
        self.calculate_outstanding_amount()
        self.set_modified_info()

    def on_update(self):
        """Handle post-update actions."""
        self.update_subscriber_subscription_status()
        self.sync_premium_profile_api_access()

    def set_created_info(self):
        """Set created timestamp and user."""
        if not self.created_at:
            self.created_at = now_datetime()
        if not self.created_by:
            self.created_by = frappe.session.user

    def set_modified_info(self):
        """Set modified timestamp and user."""
        self.modified_at = now_datetime()
        self.modified_by = frappe.session.user

    def set_defaults_from_package(self):
        """Set default values from the subscription package."""
        if self.subscription_package:
            package = frappe.get_doc("Subscription Package", self.subscription_package)

            # Set grace period days if not set
            if not self.grace_period_days:
                self.grace_period_days = package.grace_period_days or 7

            # Set price if not set
            if not self.current_price:
                self.current_price = package.price

            # Set next payment amount
            if not self.next_payment_amount:
                self.next_payment_amount = package.price

            # Set trial end date if package has trial days
            if package.trial_days and not self.trial_end_date and self.start_date:
                self.trial_end_date = add_days(self.start_date, package.trial_days)
                self.status = "Trial"

    def validate_subscriber(self):
        """Validate that a subscriber is set based on subscriber type."""
        if self.subscriber_type == "Seller" and not self.seller_profile:
            frappe.throw(_("Seller Profile is required for Seller subscriptions"))
        elif self.subscriber_type == "Buyer" and not self.buyer_profile:
            frappe.throw(_("Buyer Profile is required for Buyer subscriptions"))
        elif self.subscriber_type == "Organization" and not self.organization:
            frappe.throw(_("Organization is required for Organization subscriptions"))

        # Check for existing active subscription for the same subscriber
        if not self.name or self.is_new():
            existing = self.get_existing_active_subscription()
            if existing:
                frappe.throw(
                    _("An active subscription ({0}) already exists for this subscriber. "
                      "Please cancel or upgrade the existing subscription.").format(existing)
                )

    def get_existing_active_subscription(self):
        """Check if subscriber already has an active subscription."""
        filters = {
            "subscriber_type": self.subscriber_type,
            "status": ["in", ["Draft", "Trial", "Active", "Pending Payment", "Grace Period"]]
        }

        if self.subscriber_type == "Seller":
            filters["seller_profile"] = self.seller_profile
        elif self.subscriber_type == "Buyer":
            filters["buyer_profile"] = self.buyer_profile
        elif self.subscriber_type == "Organization":
            filters["organization"] = self.organization

        if self.name:
            filters["name"] = ["!=", self.name]

        existing = frappe.db.get_value("Subscription", filters, "name")
        return existing

    def validate_dates(self):
        """Validate subscription date fields."""
        if self.start_date and self.end_date:
            if getdate(self.end_date) < getdate(self.start_date):
                frappe.throw(_("End Date cannot be before Start Date"))

        if self.trial_end_date and self.start_date:
            if getdate(self.trial_end_date) < getdate(self.start_date):
                frappe.throw(_("Trial End Date cannot be before Start Date"))

        if self.grace_period_start_date and self.grace_period_end_date:
            if getdate(self.grace_period_end_date) < getdate(self.grace_period_start_date):
                frappe.throw(_("Grace Period End Date cannot be before Grace Period Start Date"))

    def set_tenant_from_subscriber(self):
        """Set tenant from the subscriber."""
        if self.subscriber_type == "Seller" and self.seller_profile:
            seller = frappe.get_doc("Seller Profile", self.seller_profile)
            if seller.tenant:
                self.tenant = seller.tenant
        elif self.subscriber_type == "Organization" and self.organization:
            org = frappe.get_doc("Organization", self.organization)
            if hasattr(org, "tenant") and org.tenant:
                self.tenant = org.tenant

    def update_status_flags(self):
        """Update status flags based on current status."""
        # Set is_active flag
        active_statuses = ["Trial", "Active"]
        self.is_active = 1 if self.status in active_statuses else 0

        # Set is_suspended flag
        self.is_suspended = 1 if self.status == "Suspended" else 0

        # Set in_grace_period flag
        self.in_grace_period = 1 if self.status == "Grace Period" else 0

        # Update API access based on status
        if self.status in ["Suspended", "Cancelled", "Expired"]:
            self.api_access_enabled = 0
        elif self.status in ["Active", "Trial", "Pending Payment", "Grace Period"]:
            self.api_access_enabled = 1

    def calculate_outstanding_amount(self):
        """Calculate outstanding amount."""
        self.outstanding_amount = (self.total_billed or 0) - (self.total_paid or 0)

    def update_subscriber_subscription_status(self):
        """Update the subscription status on the subscriber record."""
        # This can be used to update premium_seller or premium_buyer status
        pass

    def sync_premium_profile_api_access(self):
        """
        Synchronize API access status with Premium Seller/Buyer profiles.
        Called after subscription status changes to ensure API access is
        enabled/disabled consistently.
        """
        try:
            if self.subscriber_type == "Seller" and self.seller_profile:
                self._sync_premium_seller_api_access()
            elif self.subscriber_type == "Buyer" and self.buyer_profile:
                self._sync_premium_buyer_api_access()
        except Exception as e:
            frappe.log_error(
                message=f"Error syncing API access for subscription {self.name}: {str(e)}",
                title="Subscription API Access Sync Error"
            )

    def _sync_premium_seller_api_access(self):
        """Sync API access with Premium Seller profile."""
        premium_seller = frappe.db.get_value(
            "Premium Seller",
            {"seller_profile": self.seller_profile},
            "name"
        )
        if premium_seller:
            frappe.db.set_value(
                "Premium Seller", premium_seller,
                {
                    "subscription_status": self.status,
                    "api_access": 1 if self.api_access_enabled else 0
                },
                update_modified=False
            )

    def _sync_premium_buyer_api_access(self):
        """Sync API access with Premium Buyer profile."""
        premium_buyer = frappe.db.get_value(
            "Premium Buyer",
            {"buyer_profile": self.buyer_profile},
            "name"
        )
        if premium_buyer:
            frappe.db.set_value(
                "Premium Buyer", premium_buyer,
                {
                    "subscription_status": self.status,
                    "api_access": 1 if self.api_access_enabled else 0
                },
                update_modified=False
            )

    def check_and_transition_status(self):
        """
        Check if subscription status should transition based on current date.
        This is called by scheduled tasks to handle automatic transitions.

        Returns:
            dict: Contains old_status, new_status, and whether a change occurred
        """
        today = getdate(nowdate())
        old_status = self.status
        status_changed = False

        # Check if Active subscription has expired
        if self.status == "Active" and self.end_date:
            if getdate(self.end_date) < today:
                if self.auto_renew:
                    # Attempt renewal - if no payment method, go to pending
                    self.status = "Pending Payment"
                else:
                    # Start grace period
                    self._start_grace_period_internal()
                status_changed = True

        # Check if Trial has expired
        elif self.status == "Trial" and self.trial_end_date:
            if getdate(self.trial_end_date) < today:
                if self.auto_renew:
                    self.status = "Pending Payment"
                else:
                    self.status = "Expired"
                    self.is_active = 0
                    self.api_access_enabled = 0
                status_changed = True

        # Check if Pending Payment should enter grace period
        elif self.status == "Pending Payment":
            # If payment has been pending for more than 3 days, start grace period
            if self.last_renewal_attempt:
                days_pending = date_diff(today, getdate(self.last_renewal_attempt))
                if days_pending >= 3:
                    self._start_grace_period_internal()
                    status_changed = True

        # Check if Grace Period has expired
        elif self.status == "Grace Period" and self.grace_period_end_date:
            if getdate(self.grace_period_end_date) < today:
                self._suspend_internal(_("Grace period expired without payment"))
                status_changed = True

        if status_changed:
            self.save(ignore_permissions=True)

        return {
            "old_status": old_status,
            "new_status": self.status,
            "changed": status_changed
        }

    def _start_grace_period_internal(self):
        """Internal method to start grace period without saving."""
        today = getdate(nowdate())
        grace_days = self.grace_period_days or 7

        self.status = "Grace Period"
        self.in_grace_period = 1
        self.grace_period_start_date = today
        self.grace_period_end_date = add_days(today, grace_days)
        # Keep API access enabled during grace period
        self.api_access_enabled = 1

    def _suspend_internal(self, reason=None):
        """Internal method to suspend without saving."""
        self.status = "Suspended"
        self.is_suspended = 1
        self.is_active = 0
        self.api_access_enabled = 0  # Critical: Disable API access
        self.in_grace_period = 0
        self.suspended_at = now_datetime()
        self.suspended_reason = reason or _("Subscription suspended")
        self.suspension_type = "Payment Overdue"

    # ==================== Grace Period Methods ====================

    def start_grace_period(self):
        """Start the grace period for an overdue subscription."""
        if self.status not in ["Pending Payment"]:
            frappe.throw(_("Grace period can only start from Pending Payment status"))

        today = getdate(nowdate())
        grace_days = self.grace_period_days or 7

        self.status = "Grace Period"
        self.in_grace_period = 1
        self.grace_period_start_date = today
        self.grace_period_end_date = add_days(today, grace_days)
        self.save()

        frappe.msgprint(_("Grace period started. Subscription will be suspended on {0} if payment is not received.").format(
            self.grace_period_end_date
        ))

        return True

    def end_grace_period(self, paid=False):
        """End the grace period."""
        if paid:
            # Payment received, reactivate subscription
            self.reactivate()
        else:
            # Grace period expired without payment, suspend
            self.suspend(reason=_("Grace period expired without payment"), suspension_type="Payment Overdue")

        self.in_grace_period = 0
        self.save()

    def check_grace_period_expiry(self):
        """Check if grace period has expired and take appropriate action."""
        if self.status != "Grace Period":
            return False

        if not self.grace_period_end_date:
            return False

        today = getdate(nowdate())
        grace_end = getdate(self.grace_period_end_date)

        if today > grace_end:
            self.end_grace_period(paid=False)
            return True

        return False

    def get_days_remaining_in_grace(self):
        """Get the number of days remaining in the grace period."""
        if self.status != "Grace Period" or not self.grace_period_end_date:
            return 0

        today = getdate(nowdate())
        grace_end = getdate(self.grace_period_end_date)

        return max(0, date_diff(grace_end, today))

    # ==================== Suspension Methods ====================

    def suspend(self, reason=None, suspension_type="Manual"):
        """Suspend the subscription."""
        if self.status in ["Cancelled", "Expired"]:
            frappe.throw(_("Cannot suspend a cancelled or expired subscription"))

        self.status = "Suspended"
        self.is_suspended = 1
        self.suspended_at = now_datetime()
        self.suspended_reason = reason or _("Subscription suspended")
        self.suspension_type = suspension_type
        self.api_access_enabled = 0
        self.in_grace_period = 0

        self.save()

        frappe.msgprint(_("Subscription has been suspended. Reason: {0}").format(self.suspended_reason))

        # Notify subscriber
        self.send_suspension_notification()

        return True

    def send_suspension_notification(self):
        """Send suspension notification to subscriber."""
        # Implementation for sending email notification
        pass

    # ==================== Reactivation Methods ====================

    def reactivate(self):
        """Reactivate a suspended or grace period subscription."""
        if not self.can_reactivate:
            frappe.throw(_("This subscription cannot be reactivated"))

        if self.status not in ["Suspended", "Grace Period", "Pending Payment"]:
            frappe.throw(_("Only suspended, grace period, or pending payment subscriptions can be reactivated"))

        self.status = "Active"
        self.is_active = 1
        self.is_suspended = 0
        self.api_access_enabled = 1
        self.in_grace_period = 0
        self.last_reactivated_at = now_datetime()
        self.reactivation_count = (self.reactivation_count or 0) + 1

        # Clear suspension fields
        self.suspended_at = None
        self.suspended_reason = None
        self.suspension_type = None

        # Clear grace period fields
        self.grace_period_start_date = None
        self.grace_period_end_date = None
        self.grace_period_warning_sent = 0
        self.suspension_warning_sent = 0

        self.save()

        frappe.msgprint(_("Subscription has been reactivated successfully"))

        return True

    # ==================== Cancellation Methods ====================

    def cancel_subscription(self, reason=None, immediate=False):
        """Cancel the subscription."""
        if self.status in ["Cancelled"]:
            frappe.throw(_("Subscription is already cancelled"))

        self.status = "Cancelled"
        self.is_active = 0
        self.api_access_enabled = 0
        self.cancellation_date = nowdate()
        self.auto_renew = 0

        if reason:
            self.internal_notes = (self.internal_notes or "") + _("\nCancellation Reason: {0}").format(reason)

        self.save()

        frappe.msgprint(_("Subscription has been cancelled"))

        return True

    # ==================== Renewal Methods ====================

    def renew(self, payment_received=True):
        """Renew the subscription for another billing period."""
        if self.status not in ["Active", "Pending Payment", "Grace Period"]:
            frappe.throw(_("Cannot renew subscription with status: {0}").format(self.status))

        if not self.subscription_package:
            frappe.throw(_("Subscription package is required for renewal"))

        package = frappe.get_doc("Subscription Package", self.subscription_package)

        # Calculate new dates
        billing_period = package.billing_period or "Monthly"
        period_days = self.get_period_days(billing_period)

        today = getdate(nowdate())
        new_start = self.end_date or today
        new_end = add_days(new_start, period_days)

        if payment_received:
            self.status = "Active"
            self.is_active = 1
            self.api_access_enabled = 1
            self.start_date = new_start
            self.end_date = new_end
            self.next_billing_date = new_end
            self.last_billing_date = today
            self.renewal_reminder_sent = 0
            self.failed_renewal_attempts = 0
            self.renewal_failure_reason = None

            # Update billing totals
            self.total_billed = (self.total_billed or 0) + (self.current_price or 0)
            self.total_paid = (self.total_paid or 0) + (self.current_price or 0)

            self.save()

            frappe.msgprint(_("Subscription renewed successfully until {0}").format(new_end))
        else:
            self.status = "Pending Payment"
            self.next_billing_date = today
            self.failed_renewal_attempts = (self.failed_renewal_attempts or 0) + 1
            self.last_renewal_attempt = now_datetime()
            self.save()

        return True

    def get_period_days(self, billing_period):
        """Get the number of days for a billing period."""
        periods = {
            "Monthly": 30,
            "Quarterly": 90,
            "Semi-Annual": 180,
            "Annual": 365,
            "Lifetime": 36500  # ~100 years
        }
        return periods.get(billing_period, 30)

    # ==================== Package Change Methods ====================

    def upgrade_package(self, new_package, prorate=True):
        """Upgrade to a new subscription package."""
        if not new_package:
            frappe.throw(_("New package is required for upgrade"))

        new_pkg = frappe.get_doc("Subscription Package", new_package)
        old_pkg = frappe.get_doc("Subscription Package", self.subscription_package) if self.subscription_package else None

        # Validate upgrade is allowed
        if old_pkg and new_pkg.package_rank <= old_pkg.package_rank:
            frappe.throw(_("Cannot upgrade to a lower or same tier package. Use downgrade instead."))

        # Calculate prorate amount if applicable
        prorate_amount = 0
        if prorate and old_pkg and self.end_date:
            days_remaining = date_diff(getdate(self.end_date), getdate(nowdate()))
            if days_remaining > 0:
                daily_rate_old = (old_pkg.price or 0) / self.get_period_days(old_pkg.billing_period)
                daily_rate_new = (new_pkg.price or 0) / self.get_period_days(new_pkg.billing_period)
                prorate_amount = (daily_rate_new - daily_rate_old) * days_remaining

        # Store previous package
        self.previous_package = self.subscription_package
        self.subscription_package = new_package
        self.upgrade_date = nowdate()
        self.prorate_amount = prorate_amount
        self.current_price = new_pkg.price
        self.next_payment_amount = new_pkg.price + prorate_amount

        self.save()

        frappe.msgprint(_("Subscription upgraded to {0}. Prorate amount: {1}").format(
            new_pkg.package_name, prorate_amount
        ))

        return True

    def downgrade_package(self, new_package):
        """Downgrade to a lower subscription package."""
        if not new_package:
            frappe.throw(_("New package is required for downgrade"))

        new_pkg = frappe.get_doc("Subscription Package", new_package)
        old_pkg = frappe.get_doc("Subscription Package", self.subscription_package) if self.subscription_package else None

        # Validate downgrade is allowed
        if old_pkg and new_pkg.package_rank >= old_pkg.package_rank:
            frappe.throw(_("Cannot downgrade to a higher or same tier package. Use upgrade instead."))

        # Downgrade typically takes effect at end of current period
        self.previous_package = self.subscription_package
        self.subscription_package = new_package
        self.downgrade_date = nowdate()
        self.next_payment_amount = new_pkg.price

        self.save()

        frappe.msgprint(_("Subscription will be downgraded to {0} at the end of the current billing period.").format(
            new_pkg.package_name
        ))

        return True

    # ==================== Usage Tracking Methods ====================

    def check_product_limit(self):
        """Check if product limit has been reached."""
        if not self.max_products or self.max_products == 0:
            return True  # Unlimited

        return (self.current_product_count or 0) < self.max_products

    def check_order_limit(self):
        """Check if monthly order limit has been reached."""
        if not self.max_orders_per_month or self.max_orders_per_month == 0:
            return True  # Unlimited

        return (self.current_month_orders or 0) < self.max_orders_per_month

    def check_api_limit(self):
        """Check if daily API call limit has been reached."""
        if not self.max_api_calls_per_day or self.max_api_calls_per_day == 0:
            return True  # Unlimited

        return (self.current_day_api_calls or 0) < self.max_api_calls_per_day

    def increment_api_calls(self):
        """Increment the daily API call counter."""
        frappe.db.set_value(
            "Subscription",
            self.name,
            "current_day_api_calls",
            (self.current_day_api_calls or 0) + 1,
            update_modified=False
        )

    def reset_daily_api_calls(self):
        """Reset the daily API call counter."""
        frappe.db.set_value(
            "Subscription",
            self.name,
            "current_day_api_calls",
            0,
            update_modified=False
        )

    def reset_monthly_orders(self):
        """Reset the monthly order counter."""
        frappe.db.set_value(
            "Subscription",
            self.name,
            "current_month_orders",
            0,
            update_modified=False
        )


# ==================== API Methods ====================

@frappe.whitelist()
def get_subscription_by_seller(seller_profile):
    """Get active subscription for a seller."""
    subscription = frappe.db.get_value(
        "Subscription",
        {
            "seller_profile": seller_profile,
            "subscriber_type": "Seller",
            "status": ["in", ["Active", "Trial", "Grace Period"]]
        },
        ["name", "subscription_package", "package_name", "status", "end_date", "api_access_enabled"],
        as_dict=True
    )
    return subscription


@frappe.whitelist()
def check_subscription_status(subscription_name):
    """Check and return the current status of a subscription."""
    if not subscription_name:
        return {"status": "error", "message": _("Subscription name is required")}

    subscription = frappe.get_doc("Subscription", subscription_name)

    return {
        "status": subscription.status,
        "is_active": subscription.is_active,
        "api_access_enabled": subscription.api_access_enabled,
        "in_grace_period": subscription.in_grace_period,
        "grace_period_end_date": subscription.grace_period_end_date,
        "days_remaining_in_grace": subscription.get_days_remaining_in_grace() if subscription.in_grace_period else 0,
        "end_date": subscription.end_date,
        "package_name": subscription.package_name
    }


@frappe.whitelist()
def start_grace_period(subscription_name):
    """Start grace period for a subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.start_grace_period()


@frappe.whitelist()
def suspend_subscription(subscription_name, reason=None, suspension_type="Manual"):
    """Suspend a subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.suspend(reason=reason, suspension_type=suspension_type)


@frappe.whitelist()
def reactivate_subscription(subscription_name):
    """Reactivate a suspended subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.reactivate()


@frappe.whitelist()
def cancel_subscription(subscription_name, reason=None):
    """Cancel a subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.cancel_subscription(reason=reason)


@frappe.whitelist()
def renew_subscription(subscription_name, payment_received=True):
    """Renew a subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.renew(payment_received=payment_received)


@frappe.whitelist()
def upgrade_subscription(subscription_name, new_package, prorate=True):
    """Upgrade a subscription to a new package."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.upgrade_package(new_package, prorate=prorate)


@frappe.whitelist()
def downgrade_subscription(subscription_name, new_package):
    """Downgrade a subscription to a new package."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    return subscription.downgrade_package(new_package)


@frappe.whitelist()
def check_api_access(seller_profile=None, buyer_profile=None, organization=None):
    """
    Check if API access is enabled for a subscriber.
    Used by API middleware to validate subscription status.
    """
    filters = {
        "status": ["in", ["Active", "Trial", "Pending Payment", "Grace Period"]],
        "api_access_enabled": 1
    }

    if seller_profile:
        filters["seller_profile"] = seller_profile
        filters["subscriber_type"] = "Seller"
    elif buyer_profile:
        filters["buyer_profile"] = buyer_profile
        filters["subscriber_type"] = "Buyer"
    elif organization:
        filters["organization"] = organization
        filters["subscriber_type"] = "Organization"
    else:
        return {"allowed": False, "reason": _("No subscriber specified")}

    subscription = frappe.db.get_value(
        "Subscription",
        filters,
        ["name", "status", "api_access_enabled", "has_api_access", "current_day_api_calls", "max_api_calls_per_day"],
        as_dict=True
    )

    if not subscription:
        return {"allowed": False, "reason": _("No active subscription found")}

    if not subscription.has_api_access:
        return {"allowed": False, "reason": _("API access not included in subscription package")}

    if not subscription.api_access_enabled:
        return {"allowed": False, "reason": _("API access is disabled")}

    # Check API call limits
    if subscription.max_api_calls_per_day and subscription.max_api_calls_per_day > 0:
        if (subscription.current_day_api_calls or 0) >= subscription.max_api_calls_per_day:
            return {"allowed": False, "reason": _("Daily API call limit reached")}

    return {
        "allowed": True,
        "subscription": subscription.name,
        "status": subscription.status,
        "calls_remaining": (subscription.max_api_calls_per_day or 0) - (subscription.current_day_api_calls or 0) if subscription.max_api_calls_per_day else "unlimited"
    }


@frappe.whitelist()
def get_subscriptions_in_grace_period():
    """Get all subscriptions currently in grace period."""
    subscriptions = frappe.get_all(
        "Subscription",
        filters={"status": "Grace Period"},
        fields=["name", "seller_profile", "seller_name", "grace_period_end_date", "outstanding_amount"]
    )
    return subscriptions


@frappe.whitelist()
def get_subscriptions_pending_suspension():
    """Get subscriptions in grace period that have expired."""
    today = nowdate()
    subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": "Grace Period",
            "grace_period_end_date": ["<", today]
        },
        fields=["name", "seller_profile", "seller_name", "grace_period_end_date", "outstanding_amount"]
    )
    return subscriptions


def get_subscription_permission_query(user):
    """Permission query for subscription based on tenant."""
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Get user's tenant
    tenant = frappe.db.get_value("User", user, "tenant")
    if tenant:
        return f"`tabSubscription`.tenant = '{tenant}'"

    # Check if user is a seller
    seller = frappe.db.get_value("Seller Profile", {"user": user}, "name")
    if seller:
        return f"`tabSubscription`.seller_profile = '{seller}'"

    # Check if user is linked to buyer profile
    return f"`tabSubscription`.buyer_profile = '{user}'"


@frappe.whitelist(allow_guest=False)
def verify_api_access_for_request(seller_profile=None, buyer_profile=None, organization=None):
    """
    Verify API access for an incoming API request.
    This method should be called by API middleware to check if the requester
    has valid subscription with API access enabled.

    Returns:
        dict: {
            "allowed": bool,
            "subscription": subscription_name or None,
            "status": subscription_status or None,
            "reason": error_message if not allowed,
            "remaining_calls": number or "unlimited"
        }
    """
    result = check_api_access(
        seller_profile=seller_profile,
        buyer_profile=buyer_profile,
        organization=organization
    )

    # If allowed, increment the API call counter
    if result.get("allowed") and result.get("subscription"):
        try:
            subscription = frappe.get_doc("Subscription", result["subscription"])
            subscription.increment_api_calls()
        except Exception as e:
            frappe.log_error(
                message=f"Error incrementing API calls: {str(e)}",
                title="API Call Counter Error"
            )

    return result


@frappe.whitelist()
def get_active_subscription_for_user(user=None):
    """
    Get the active subscription for a user.
    Checks if user is a seller, buyer, or part of an organization.

    Args:
        user: User ID (defaults to current user)

    Returns:
        dict: Subscription details or None
    """
    if not user:
        user = frappe.session.user

    # Check if user is a seller
    seller_profile = frappe.db.get_value("Seller Profile", {"user": user}, "name")
    if seller_profile:
        return get_subscription_by_seller(seller_profile)

    # Check if user is a buyer with subscription
    subscription = frappe.db.get_value(
        "Subscription",
        {
            "buyer_profile": user,
            "subscriber_type": "Buyer",
            "status": ["in", ["Active", "Trial", "Grace Period"]]
        },
        ["name", "subscription_package", "package_name", "status", "end_date", "api_access_enabled"],
        as_dict=True
    )
    if subscription:
        return subscription

    # Check if user is part of an organization with subscription
    # This would require checking organization membership
    org_name = frappe.db.get_value("Organization", {"owner": user}, "name")
    if org_name:
        subscription = frappe.db.get_value(
            "Subscription",
            {
                "organization": org_name,
                "subscriber_type": "Organization",
                "status": ["in", ["Active", "Trial", "Grace Period"]]
            },
            ["name", "subscription_package", "package_name", "status", "end_date", "api_access_enabled"],
            as_dict=True
        )
        if subscription:
            return subscription

    return None


@frappe.whitelist()
def is_api_access_allowed(seller_profile=None, buyer_profile=None, organization=None):
    """
    Simple boolean check for API access.
    Use this for quick checks without detailed response.

    Returns:
        bool: True if API access is allowed, False otherwise
    """
    result = check_api_access(
        seller_profile=seller_profile,
        buyer_profile=buyer_profile,
        organization=organization
    )
    return result.get("allowed", False)


@frappe.whitelist()
def record_api_usage(subscription_name, endpoint=None, method=None):
    """
    Record API usage for a subscription.
    Called by API middleware to track usage patterns.

    Args:
        subscription_name: The subscription document name
        endpoint: API endpoint called (optional)
        method: HTTP method used (optional)
    """
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        subscription.increment_api_calls()

        # Optionally log detailed usage (for analytics)
        # This could be stored in a separate API Usage Log doctype
        frappe.logger().debug(
            f"API call recorded for {subscription_name}: {method} {endpoint}"
        )

        return {"success": True, "current_calls": subscription.current_day_api_calls + 1}
    except Exception as e:
        frappe.log_error(
            message=f"Error recording API usage: {str(e)}",
            title="API Usage Recording Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_subscription_limits(subscription_name):
    """
    Get the current usage and limits for a subscription.

    Returns:
        dict: Current usage vs limits for products, orders, and API calls
    """
    subscription = frappe.get_doc("Subscription", subscription_name)

    return {
        "products": {
            "current": subscription.current_product_count or 0,
            "limit": subscription.max_products or 0,
            "unlimited": not subscription.max_products
        },
        "orders_per_month": {
            "current": subscription.current_month_orders or 0,
            "limit": subscription.max_orders_per_month or 0,
            "unlimited": not subscription.max_orders_per_month
        },
        "api_calls_per_day": {
            "current": subscription.current_day_api_calls or 0,
            "limit": subscription.max_api_calls_per_day or 0,
            "unlimited": not subscription.max_api_calls_per_day
        },
        "subscription_status": subscription.status,
        "api_access_enabled": subscription.api_access_enabled
    }


@frappe.whitelist()
def force_check_subscription_status(subscription_name):
    """
    Force a status check and transition for a subscription.
    Admin method for manual intervention.
    """
    if not frappe.has_permission("Subscription", "write"):
        frappe.throw(_("You don't have permission to manage subscriptions"))

    subscription = frappe.get_doc("Subscription", subscription_name)
    result = subscription.check_and_transition_status()

    if result["changed"]:
        frappe.msgprint(_(
            "Subscription status changed from {0} to {1}"
        ).format(result["old_status"], result["new_status"]))
    else:
        frappe.msgprint(_("No status change required"))

    return result
