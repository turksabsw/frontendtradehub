# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate


class Tenant(Document):
    """
    Tenant DocType for multi-tenant isolation in TR-TradeHub marketplace.

    Each tenant represents an isolated marketplace instance with its own:
    - Sellers and buyer accounts
    - Products and listings
    - Orders and transactions
    - Configuration and settings
    """

    def before_insert(self):
        """Set default values before inserting a new tenant."""
        if not self.subscription_start_date:
            self.subscription_start_date = nowdate()

        if not self.created_by:
            self.created_by = frappe.session.user

        # Set default limits based on subscription tier
        self.set_tier_defaults()

    def validate(self):
        """Validate tenant data before saving."""
        self.validate_tax_id()
        self.validate_subscription_dates()
        self.validate_limits()
        self.modified_by = frappe.session.user

    def on_update(self):
        """Actions to perform after tenant is updated."""
        self.clear_tenant_cache()

    def after_insert(self):
        """Actions to perform after tenant is inserted."""
        # Create User Permission for the tenant creator for data isolation
        self.create_user_permission_for_creator()

    def on_trash(self):
        """Prevent deletion of tenant with active sellers or orders."""
        self.check_linked_documents()

    def validate_tax_id(self):
        """Validate Turkish Tax ID format (VKN or TCKN)."""
        if self.tax_id:
            tax_id = self.tax_id.strip()
            # VKN is 10 digits, TCKN is 11 digits
            if not tax_id.isdigit():
                frappe.throw(_("Tax ID must contain only digits"))
            if len(tax_id) not in [10, 11]:
                frappe.throw(_("Tax ID must be 10 digits (VKN) or 11 digits (TCKN)"))

    def validate_subscription_dates(self):
        """Validate subscription date range."""
        if self.subscription_start_date and self.subscription_end_date:
            if getdate(self.subscription_end_date) < getdate(self.subscription_start_date):
                frappe.throw(_("Subscription end date cannot be before start date"))

    def validate_limits(self):
        """Validate tenant limits are positive."""
        if cint(self.max_sellers) < 0:
            frappe.throw(_("Max Sellers cannot be negative"))
        if cint(self.max_listings_per_seller) < 0:
            frappe.throw(_("Max Listings per Seller cannot be negative"))

    def set_tier_defaults(self):
        """Set default limits based on subscription tier."""
        tier_limits = {
            "Free": {"max_sellers": 1, "max_listings_per_seller": 10, "commission_rate": 15.0},
            "Basic": {"max_sellers": 10, "max_listings_per_seller": 100, "commission_rate": 10.0},
            "Professional": {"max_sellers": 50, "max_listings_per_seller": 500, "commission_rate": 7.5},
            "Enterprise": {"max_sellers": 0, "max_listings_per_seller": 0, "commission_rate": 5.0}  # 0 = unlimited
        }

        if self.subscription_tier and self.subscription_tier in tier_limits:
            limits = tier_limits[self.subscription_tier]
            # Only set defaults if not already specified
            if not self.max_sellers:
                self.max_sellers = limits["max_sellers"]
            if not self.max_listings_per_seller:
                self.max_listings_per_seller = limits["max_listings_per_seller"]
            if not self.commission_rate:
                self.commission_rate = limits["commission_rate"]

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked seller profiles
        if frappe.db.exists("Seller Profile", {"tenant": self.name}):
            frappe.throw(
                _("Cannot delete Tenant with active Seller Profiles. Please delete all linked Seller Profiles first.")
            )

    def clear_tenant_cache(self):
        """Clear cached tenant data."""
        cache_key = f"tenant:{self.name}"
        frappe.cache().delete_value(cache_key)

    def create_user_permission_for_creator(self):
        """
        Create User Permission for tenant creator to enable data isolation.

        This ensures that the user who created the tenant can only access data
        belonging to this tenant by creating a User Permission linking the user
        to this tenant. This is the foundation for multi-tenant data isolation.
        """
        if not self.created_by or self.created_by == "Administrator":
            return

        # Check if User Permission already exists
        if frappe.db.exists("User Permission", {
            "user": self.created_by,
            "allow": "Tenant",
            "for_value": self.name
        }):
            return

        try:
            user_permission = frappe.get_doc({
                "doctype": "User Permission",
                "user": self.created_by,
                "allow": "Tenant",
                "for_value": self.name,
                "apply_to_all_doctypes": 1,
                "is_default": 1
            })
            user_permission.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=_("Failed to create User Permission for Tenant {0}").format(self.name)
            )

    def is_active(self):
        """Check if tenant subscription is active."""
        if self.status != "Active":
            return False

        if self.subscription_end_date:
            return getdate(self.subscription_end_date) >= getdate(nowdate())

        return True

    def can_add_seller(self):
        """Check if tenant can add more sellers."""
        if not self.is_active():
            return False

        # 0 means unlimited
        if cint(self.max_sellers) == 0:
            return True

        current_count = frappe.db.count("Seller Profile", {"tenant": self.name})
        return current_count < cint(self.max_sellers)

    def get_seller_count(self):
        """Get count of sellers for this tenant."""
        return frappe.db.count("Seller Profile", {"tenant": self.name})

    def get_listing_count(self):
        """Get total count of listings for this tenant."""
        return frappe.db.count("Listing", {"tenant": self.name})


@frappe.whitelist()
def get_tenant_stats(tenant_name):
    """
    Get statistics for a tenant.

    Args:
        tenant_name: Name of the tenant

    Returns:
        dict: Tenant statistics including seller count, listing count, etc.
    """
    if not frappe.has_permission("Tenant", "read"):
        frappe.throw(_("Not permitted to view tenant statistics"))

    tenant = frappe.get_doc("Tenant", tenant_name)

    return {
        "tenant_name": tenant.tenant_name,
        "company_name": tenant.company_name,
        "status": tenant.status,
        "subscription_tier": tenant.subscription_tier,
        "is_active": tenant.is_active(),
        "seller_count": tenant.get_seller_count(),
        "listing_count": tenant.get_listing_count(),
        "max_sellers": tenant.max_sellers,
        "max_listings_per_seller": tenant.max_listings_per_seller,
        "can_add_seller": tenant.can_add_seller()
    }


@frappe.whitelist()
def check_tenant_limits(tenant_name, check_type):
    """
    Check if a tenant has reached its limits.

    Args:
        tenant_name: Name of the tenant
        check_type: Type of limit to check ('seller' or 'listing')

    Returns:
        dict: Result with can_proceed flag and message
    """
    if not frappe.has_permission("Tenant", "read"):
        frappe.throw(_("Not permitted"))

    tenant = frappe.get_doc("Tenant", tenant_name)

    if check_type == "seller":
        can_proceed = tenant.can_add_seller()
        if can_proceed:
            return {"can_proceed": True, "message": _("You can add a new seller")}
        else:
            return {
                "can_proceed": False,
                "message": _("Seller limit reached. Please upgrade your subscription.")
            }

    return {"can_proceed": False, "message": _("Invalid check type")}
