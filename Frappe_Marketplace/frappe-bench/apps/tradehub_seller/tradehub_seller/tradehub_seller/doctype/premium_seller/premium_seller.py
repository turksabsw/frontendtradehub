# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, nowdate, add_days


class PremiumSeller(Document):
    """
    Premium Seller DocType controller.

    Manages enhanced seller profiles with additional business information,
    certifications, factory details, and premium benefits.
    """

    def before_save(self):
        """Process data before saving."""
        self.set_tenant_from_seller()
        self.update_timestamps()
        self.validate_subscription_dates()
        self.check_subscription_status()
        self.update_premium_since()

    def validate(self):
        """Validate the document data."""
        self.validate_seller_profile()
        self.validate_year_established()
        self.validate_certifications()
        self.validate_urls()

    def set_tenant_from_seller(self):
        """
        Auto-populate tenant from seller profile if not set.
        Follows the tenant-seller hierarchy pattern.
        """
        if self.seller_profile and not self.tenant:
            seller_tenant = frappe.db.get_value(
                "Seller Profile", self.seller_profile, "tenant"
            )
            if seller_tenant:
                self.tenant = seller_tenant

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

    def validate_seller_profile(self):
        """Validate the linked seller profile."""
        if self.seller_profile:
            # Check if seller profile exists and is active
            seller_status = frappe.db.get_value(
                "Seller Profile", self.seller_profile, "status"
            )
            if seller_status not in ["Active", "Under Review"]:
                frappe.msgprint(
                    msg=_("Seller Profile '{0}' is not active. Status: {1}").format(
                        self.seller_profile, seller_status
                    ),
                    title=_("Seller Profile Warning"),
                    indicator="orange",
                    alert=True
                )

            # Check if premium seller already exists for this seller
            existing = frappe.db.get_value(
                "Premium Seller",
                {"seller_profile": self.seller_profile, "name": ["!=", self.name]},
                "name"
            )
            if existing:
                frappe.throw(
                    _("A Premium Seller profile already exists for {0}: {1}").format(
                        self.seller_profile, existing
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

    def validate_certifications(self):
        """Validate certification entries."""
        if not self.certifications:
            return

        seen = set()
        for cert in self.certifications:
            key = (cert.certification_name, cert.certification_type)
            if key in seen:
                frappe.msgprint(
                    msg=_("Duplicate certification found: {0} ({1})").format(
                        cert.certification_name, cert.certification_type
                    ),
                    title=_("Duplicate Certification"),
                    indicator="orange",
                    alert=True
                )
            seen.add(key)

    def validate_urls(self):
        """Basic URL validation for social media fields."""
        url_fields = [
            "linkedin_url", "website_url", "alibaba_url",
            "made_in_china_url", "indiamart_url", "other_marketplace_url",
            "company_video", "virtual_tour_url"
        ]

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

    def get_active_certifications(self):
        """Get list of currently valid certifications."""
        if not self.certifications:
            return []

        today = getdate(nowdate())
        return [
            cert for cert in self.certifications
            if not cert.expiry_date or getdate(cert.expiry_date) >= today
        ]

    def get_expiring_certifications(self, days=30):
        """Get certifications expiring within specified days."""
        if not self.certifications:
            return []

        today = getdate(nowdate())
        threshold = add_days(today, days)

        return [
            cert for cert in self.certifications
            if cert.expiry_date
            and getdate(cert.expiry_date) >= today
            and getdate(cert.expiry_date) <= getdate(threshold)
        ]

    def is_premium_active(self):
        """Check if premium status is currently active."""
        return (
            self.status == "Active"
            and self.subscription_status in ["Active", "Grace Period"]
        )

    def get_premium_benefits(self):
        """Get the list of premium benefits for this seller."""
        benefits = []

        if self.priority_listing:
            benefits.append(_("Priority Listing in Search Results"))
        if self.featured_placement:
            benefits.append(_("Featured Product Placement"))
        if self.dedicated_account_manager:
            benefits.append(_("Dedicated Account Manager"))
        if self.reduced_commission_rate > 0:
            benefits.append(_("{0}% Commission Reduction").format(self.reduced_commission_rate))
        if self.advanced_analytics:
            benefits.append(_("Advanced Analytics Dashboard"))
        if self.api_access_level and self.api_access_level != "None":
            benefits.append(_("{0} API Access").format(self.api_access_level))

        return benefits

    def update_performance_metrics(self):
        """Update performance metrics from seller data."""
        if not self.seller_profile:
            return

        # Fetch metrics from seller profile
        seller = frappe.get_doc("Seller Profile", self.seller_profile)

        self.on_time_delivery_rate = seller.on_time_delivery_rate or 0
        self.return_rate = seller.return_rate or 0

        # Calculate response rate from messages (if applicable)
        # This would need to be calculated from message/inquiry data

        self.save(ignore_permissions=True)


@frappe.whitelist()
def get_premium_seller_by_profile(seller_profile):
    """
    Get Premium Seller record by Seller Profile.

    Args:
        seller_profile: The Seller Profile name

    Returns:
        dict: Premium Seller details or None
    """
    premium = frappe.db.get_value(
        "Premium Seller",
        {"seller_profile": seller_profile},
        ["name", "status", "verification_level", "subscription_status"],
        as_dict=True
    )
    return premium


@frappe.whitelist()
def check_premium_status(seller_profile):
    """
    Check if a seller has active premium status.

    Args:
        seller_profile: The Seller Profile name

    Returns:
        dict: Premium status information
    """
    premium = frappe.db.get_value(
        "Premium Seller",
        {"seller_profile": seller_profile, "status": "Active"},
        ["name", "verification_level", "subscription_status", "subscription_end_date"],
        as_dict=True
    )

    if not premium:
        return {"is_premium": False}

    return {
        "is_premium": premium.subscription_status in ["Active", "Grace Period"],
        "premium_seller": premium.name,
        "verification_level": premium.verification_level,
        "subscription_status": premium.subscription_status,
        "subscription_end_date": premium.subscription_end_date
    }


@frappe.whitelist()
def get_premium_benefits(premium_seller):
    """
    Get the list of benefits for a premium seller.

    Args:
        premium_seller: The Premium Seller name

    Returns:
        list: List of benefit descriptions
    """
    if not frappe.db.exists("Premium Seller", premium_seller):
        frappe.throw(_("Premium Seller not found"))

    doc = frappe.get_doc("Premium Seller", premium_seller)
    return doc.get_premium_benefits()


@frappe.whitelist()
def get_expiring_certifications(premium_seller, days=30):
    """
    Get certifications that are expiring soon.

    Args:
        premium_seller: The Premium Seller name
        days: Number of days to look ahead (default 30)

    Returns:
        list: List of expiring certification details
    """
    if not frappe.db.exists("Premium Seller", premium_seller):
        frappe.throw(_("Premium Seller not found"))

    doc = frappe.get_doc("Premium Seller", premium_seller)
    expiring = doc.get_expiring_certifications(int(days))

    return [
        {
            "certification_name": cert.certification_name,
            "certification_type": cert.certification_type,
            "expiry_date": cert.expiry_date,
            "days_until_expiry": cert.days_until_expiry() if hasattr(cert, "days_until_expiry") else None
        }
        for cert in expiring
    ]


def get_premium_seller_permission_query(user):
    """
    Permission query for Premium Seller based on tenant.

    Returns SQL WHERE clause to filter by tenant.
    """
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Get user's tenant
    tenant = None

    # Check if user is a seller
    seller_tenant = frappe.db.get_value(
        "Seller Profile",
        {"user": user},
        "tenant"
    )
    if seller_tenant:
        tenant = seller_tenant

    if tenant:
        return f"`tabPremium Seller`.tenant = '{tenant}'"

    return "1=0"  # No access if no tenant
