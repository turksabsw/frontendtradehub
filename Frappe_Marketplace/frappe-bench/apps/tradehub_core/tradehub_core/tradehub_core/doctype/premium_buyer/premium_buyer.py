# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, nowdate, add_days
import secrets


class PremiumBuyer(Document):
    """
    Premium Buyer DocType controller.

    Manages enhanced buyer profiles with additional business information,
    procurement details, credit verification, and premium benefits.
    """

    def before_save(self):
        """Process data before saving."""
        self.set_tenant_from_organization()
        self.update_timestamps()
        self.validate_subscription_dates()
        self.check_subscription_status()
        self.update_premium_since()
        self.generate_api_key_if_needed()

    def validate(self):
        """Validate the document data."""
        self.validate_buyer_profile()
        self.validate_year_established()
        self.validate_credit_score()
        self.validate_urls()
        self.validate_api_access()

    def set_tenant_from_organization(self):
        """
        Auto-populate tenant from buyer's organization if not set.
        """
        if self.buyer_profile and not self.tenant:
            # Try to get tenant from user's organization
            org = frappe.db.get_value(
                "Organization",
                {"owner": self.buyer_profile},
                "tenant"
            )
            if org:
                self.tenant = org

    def update_timestamps(self):
        """Update timestamp fields."""
        if self.is_new():
            self.created_at = now_datetime()
            self.created_by = frappe.session.user

        self.modified_at = now_datetime()
        self.modified_by = frappe.session.user

    def update_premium_since(self):
        """Set premium_since date when first activated."""
        if not self.premium_since and self.status == "Active":
            self.premium_since = nowdate()

    def validate_buyer_profile(self):
        """Validate the linked buyer profile (User)."""
        if self.buyer_profile:
            # Check if user exists and is enabled
            user_enabled = frappe.db.get_value(
                "User", self.buyer_profile, "enabled"
            )
            if not user_enabled:
                frappe.msgprint(
                    msg=_("User '{0}' is disabled.").format(self.buyer_profile),
                    title=_("User Warning"),
                    indicator="orange",
                    alert=True
                )

            # Check if premium buyer already exists for this user
            existing = frappe.db.get_value(
                "Premium Buyer",
                {"buyer_profile": self.buyer_profile, "name": ["!=", self.name or ""]},
                "name"
            )
            if existing:
                frappe.throw(
                    _("A Premium Buyer profile already exists for {0}: {1}").format(
                        self.buyer_profile, existing
                    )
                )

    def validate_year_established(self):
        """Validate the year established field."""
        if self.year_established:
            current_year = getdate(nowdate()).year
            if self.year_established < 1800 or self.year_established > current_year:
                frappe.throw(
                    _("Year Established must be between 1800 and {0}").format(current_year)
                )

    def validate_subscription_dates(self):
        """Validate subscription date range."""
        if self.subscription_start_date and self.subscription_end_date:
            if getdate(self.subscription_end_date) < getdate(self.subscription_start_date):
                frappe.throw(
                    _("Subscription End Date cannot be before Start Date")
                )

    def check_subscription_status(self):
        """Check and update subscription status based on dates."""
        if not self.subscription_end_date:
            return

        end_date = getdate(self.subscription_end_date)
        today = getdate(nowdate())

        if today > end_date:
            # Grace period is typically 7 days
            grace_end = add_days(end_date, 7)
            if today <= getdate(grace_end):
                if self.subscription_status != "Grace Period":
                    self.subscription_status = "Grace Period"
                    frappe.msgprint(
                        msg=_("Subscription is in grace period. Please renew to maintain premium benefits."),
                        title=_("Grace Period"),
                        indicator="orange",
                        alert=True
                    )
            else:
                if self.subscription_status not in ["Expired", "Cancelled"]:
                    self.subscription_status = "Expired"
                    self.status = "Expired"

    def validate_credit_score(self):
        """Validate credit score is within valid range."""
        if self.credit_score:
            if self.credit_score < 0 or self.credit_score > 1000:
                frappe.throw(
                    _("Credit Score must be between 0 and 1000")
                )

    def validate_urls(self):
        """Basic URL validation for web fields."""
        url_fields = ["company_website", "linkedin_profile"]

        for field in url_fields:
            url = self.get(field)
            if url and not url.startswith(("http://", "https://")):
                frappe.msgprint(
                    msg=_("{0} should start with http:// or https://").format(
                        self.meta.get_label(field)
                    ),
                    title=_("Invalid URL Format"),
                    indicator="orange",
                    alert=True
                )

    def validate_api_access(self):
        """Validate API access settings."""
        if self.api_access_level and self.api_access_level != "None":
            # Set default API requests per day based on level
            if not self.api_requests_per_day:
                api_limits = {
                    "Basic": 100,
                    "Standard": 500,
                    "Advanced": 2000,
                    "Enterprise": 10000
                }
                self.api_requests_per_day = api_limits.get(self.api_access_level, 100)

    def generate_api_key_if_needed(self):
        """Generate API key if API access is granted and key doesn't exist."""
        if (self.api_access_level and
            self.api_access_level != "None" and
            not self.api_key):
            self.api_key = f"pb_{secrets.token_urlsafe(32)}"

    def is_premium_active(self):
        """Check if premium status is currently active."""
        return (
            self.status == "Active"
            and self.subscription_status in ["Active", "Grace Period"]
        )

    def get_premium_benefits(self):
        """Get the list of premium benefits for this buyer."""
        benefits = []

        if self.priority_support:
            benefits.append(_("Priority Customer Support"))
        if self.dedicated_account_manager:
            benefits.append(_("Dedicated Account Manager"))
        if self.bulk_discount_rate > 0:
            benefits.append(_("{0}% Bulk Discount").format(self.bulk_discount_rate))
        if self.extended_payment_terms:
            benefits.append(_("Extended Payment Terms"))
        if self.early_access_products:
            benefits.append(_("Early Access to Products"))
        if self.api_access_level and self.api_access_level != "None":
            benefits.append(_("{0} API Access").format(self.api_access_level))

        return benefits

    def update_purchase_statistics(self):
        """Update purchase statistics from order data."""
        if not self.buyer_profile:
            return

        # Get order statistics
        order_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(grand_total) as total_amount,
                MAX(creation) as last_order,
                AVG(grand_total) as avg_order_value
            FROM `tabMarketplace Order`
            WHERE buyer = %s AND docstatus = 1
        """, (self.buyer_profile,), as_dict=True)

        if order_stats and order_stats[0].total_orders:
            stats = order_stats[0]
            self.total_orders = stats.total_orders or 0
            self.total_purchase_amount = stats.total_amount or 0
            self.average_order_value = stats.avg_order_value or 0
            if stats.last_order:
                self.last_order_date = getdate(stats.last_order)

            # Calculate average order frequency
            if stats.total_orders > 1:
                first_order = frappe.db.sql("""
                    SELECT MIN(creation) as first_order
                    FROM `tabMarketplace Order`
                    WHERE buyer = %s AND docstatus = 1
                """, (self.buyer_profile,), as_dict=True)

                if first_order and first_order[0].first_order:
                    first_date = getdate(first_order[0].first_order)
                    last_date = getdate(stats.last_order)
                    days_diff = (last_date - first_date).days
                    if days_diff > 0:
                        self.average_order_frequency_days = int(days_diff / (stats.total_orders - 1))

        self.save(ignore_permissions=True)

    def update_performance_metrics(self):
        """Update buyer performance metrics."""
        if not self.buyer_profile:
            return

        # Calculate payment reliability
        payment_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_payments,
                SUM(CASE WHEN payment_status = 'Paid' THEN 1 ELSE 0 END) as on_time_payments
            FROM `tabMarketplace Order`
            WHERE buyer = %s AND docstatus = 1
        """, (self.buyer_profile,), as_dict=True)

        if payment_stats and payment_stats[0].total_payments > 0:
            stats = payment_stats[0]
            self.payment_reliability_rate = (stats.on_time_payments / stats.total_payments) * 100

        # Calculate dispute rate
        dispute_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN has_dispute = 1 THEN 1 ELSE 0 END) as disputed_orders
            FROM `tabMarketplace Order`
            WHERE buyer = %s AND docstatus = 1
        """, (self.buyer_profile,), as_dict=True)

        if dispute_stats and dispute_stats[0].total_orders > 0:
            stats = dispute_stats[0]
            self.dispute_rate = (stats.disputed_orders / stats.total_orders) * 100

        self.save(ignore_permissions=True)

    def get_favorite_categories(self):
        """Get most purchased categories for the buyer."""
        if not self.buyer_profile:
            return []

        categories = frappe.db.sql("""
            SELECT
                l.category,
                COUNT(*) as purchase_count
            FROM `tabMarketplace Order Item` oi
            JOIN `tabMarketplace Order` o ON o.name = oi.parent
            JOIN `tabListing` l ON l.name = oi.listing
            WHERE o.buyer = %s AND o.docstatus = 1
            GROUP BY l.category
            ORDER BY purchase_count DESC
            LIMIT 5
        """, (self.buyer_profile,), as_dict=True)

        return [cat.category for cat in categories if cat.category]


@frappe.whitelist()
def get_premium_buyer_by_user(user):
    """
    Get Premium Buyer record by User.

    Args:
        user: The User name/email

    Returns:
        dict: Premium Buyer details or None
    """
    premium = frappe.db.get_value(
        "Premium Buyer",
        {"buyer_profile": user},
        ["name", "status", "verification_level", "subscription_status", "buyer_score"],
        as_dict=True
    )
    return premium


@frappe.whitelist()
def check_premium_status(user):
    """
    Check if a user has active premium buyer status.

    Args:
        user: The User name/email

    Returns:
        dict: Premium status information
    """
    premium = frappe.db.get_value(
        "Premium Buyer",
        {"buyer_profile": user, "status": "Active"},
        ["name", "verification_level", "subscription_status", "subscription_end_date", "credit_limit"],
        as_dict=True
    )

    if not premium:
        return {"is_premium": False}

    return {
        "is_premium": premium.subscription_status in ["Active", "Grace Period"],
        "premium_buyer": premium.name,
        "verification_level": premium.verification_level,
        "subscription_status": premium.subscription_status,
        "subscription_end_date": premium.subscription_end_date,
        "credit_limit": premium.credit_limit
    }


@frappe.whitelist()
def get_premium_benefits(premium_buyer):
    """
    Get the list of benefits for a premium buyer.

    Args:
        premium_buyer: The Premium Buyer name

    Returns:
        list: List of benefit descriptions
    """
    if not frappe.db.exists("Premium Buyer", premium_buyer):
        frappe.throw(_("Premium Buyer not found"))

    doc = frappe.get_doc("Premium Buyer", premium_buyer)
    return doc.get_premium_benefits()


@frappe.whitelist()
def update_buyer_statistics(premium_buyer):
    """
    Update purchase statistics for a premium buyer.

    Args:
        premium_buyer: The Premium Buyer name
    """
    if not frappe.db.exists("Premium Buyer", premium_buyer):
        frappe.throw(_("Premium Buyer not found"))

    doc = frappe.get_doc("Premium Buyer", premium_buyer)
    doc.update_purchase_statistics()
    doc.update_performance_metrics()

    return {"success": True}


@frappe.whitelist()
def get_buyer_credit_info(premium_buyer):
    """
    Get credit information for a premium buyer.

    Args:
        premium_buyer: The Premium Buyer name

    Returns:
        dict: Credit information
    """
    if not frappe.db.exists("Premium Buyer", premium_buyer):
        frappe.throw(_("Premium Buyer not found"))

    buyer = frappe.get_doc("Premium Buyer", premium_buyer)

    return {
        "credit_verified": buyer.credit_verified,
        "credit_score": buyer.credit_score,
        "credit_limit": buyer.credit_limit,
        "payment_reliability_rate": buyer.payment_reliability_rate,
        "dispute_rate": buyer.dispute_rate
    }


def get_premium_buyer_permission_query(user):
    """
    Permission query for Premium Buyer based on tenant.

    Returns SQL WHERE clause to filter by tenant.
    """
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Get user's tenant
    tenant = None

    # Check if user has an organization
    org_tenant = frappe.db.get_value(
        "Organization",
        {"owner": user},
        "tenant"
    )
    if org_tenant:
        tenant = org_tenant

    if tenant:
        return f"`tabPremium Buyer`.tenant = '{tenant}'"

    # Allow users to see their own premium buyer profile
    return f"`tabPremium Buyer`.buyer_profile = '{user}'"
