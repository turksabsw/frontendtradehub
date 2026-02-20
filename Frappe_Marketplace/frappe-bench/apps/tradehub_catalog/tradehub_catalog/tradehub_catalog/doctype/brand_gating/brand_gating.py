# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Brand Gating DocType for Trade Hub B2B Marketplace.

This module implements the Brand Gating DocType for managing authorized reseller
relationships between brands and sellers. It enforces which sellers can list
products from specific brands and integrates with the Buy Box algorithm.

Key Features:
- Authorization workflow (Pending -> Under Review -> Approved/Rejected)
- Validity period management with auto-expiry
- Product scope restrictions (All/Categories/Specific)
- Pricing restrictions (floor/ceiling percentages)
- Buy Box eligibility and priority boost
- Multi-tenant data isolation via Seller Profile's tenant
- fetch_from pattern for brand, seller, and tenant information

Authorization Types:
- Standard Reseller: Basic authorization to sell brand products
- Authorized Distributor: Verified distributor with enhanced privileges
- Exclusive Distributor: Exclusive rights in a region/category
- Official Partner: Brand-recognized official partner
- Manufacturer Direct: Direct manufacturer selling their own brand
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, today, getdate, now_datetime, add_days


class BrandGating(Document):
    """
    Brand Gating DocType for authorized reseller management.

    Each Brand Gating entry represents an authorization relationship between
    a brand and a seller, controlling what products the seller can list
    and how they participate in the Buy Box algorithm.
    """

    def before_insert(self):
        """Set defaults before inserting a new authorization."""
        self.validate_unique_authorization()
        self.set_default_validity()

    def validate(self):
        """Validate brand gating data before saving."""
        self.validate_brand()
        self.validate_seller()
        self.validate_authorization_status()
        self.validate_validity_dates()
        self.validate_pricing_restrictions()
        self.validate_buybox_settings()
        self.validate_tenant_isolation()
        self.sync_is_active_status()
        self.check_expiry()

    def on_update(self):
        """Actions after brand gating is updated."""
        self.clear_authorization_cache()
        self.notify_status_change()

    def on_trash(self):
        """Actions before brand gating is deleted."""
        self.check_active_products()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_default_validity(self):
        """Set default validity dates if not provided."""
        if not self.valid_from:
            self.valid_from = today()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_unique_authorization(self):
        """
        Validate that only one active authorization exists per brand-seller combination.

        A seller cannot have multiple active authorizations for the same brand.
        """
        existing = frappe.db.get_value(
            "Brand Gating",
            {
                "brand": self.brand,
                "seller": self.seller,
                "authorization_status": ("in", ["Pending", "Under Review", "Approved"]),
                "name": ("!=", self.name or "")
            },
            "name"
        )

        if existing:
            frappe.throw(
                _("An active authorization for this brand-seller combination already exists: {0}").format(
                    existing
                )
            )

    def validate_brand(self):
        """Validate Brand link exists and is valid."""
        if not self.brand:
            frappe.throw(_("Brand is required"))

        brand_data = frappe.db.get_value(
            "Brand",
            self.brand,
            ["enabled", "verification_status"],
            as_dict=True
        )

        if not brand_data:
            frappe.throw(_("Brand not found"))

        if not brand_data.enabled:
            frappe.throw(_("Cannot create authorization for disabled brand"))

        if brand_data.verification_status != "Verified":
            frappe.msgprint(
                _("Warning: Brand {0} is not verified").format(self.brand),
                indicator='orange',
                alert=True
            )

    def validate_seller(self):
        """Validate Seller Profile link exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        seller_data = frappe.db.get_value(
            "Seller Profile",
            self.seller,
            ["status", "verification_status"],
            as_dict=True
        )

        if not seller_data:
            frappe.throw(_("Seller Profile not found"))

        if seller_data.status == "Deactivated":
            frappe.throw(_("Cannot create authorization for deactivated seller"))

        if seller_data.verification_status != "Verified":
            frappe.msgprint(
                _("Warning: Seller {0} is not verified").format(self.seller),
                indicator='orange',
                alert=True
            )

    def validate_authorization_status(self):
        """Validate authorization status transitions."""
        if self.has_value_changed("authorization_status"):
            old_doc = self.get_doc_before_save()
            old_status = old_doc.authorization_status if old_doc else "Pending"
            new_status = self.authorization_status

            # Define valid transitions
            valid_transitions = {
                "Pending": ["Under Review", "Approved", "Rejected"],
                "Under Review": ["Approved", "Rejected", "Pending"],
                "Approved": ["Suspended", "Revoked", "Expired"],
                "Rejected": ["Pending", "Under Review"],
                "Suspended": ["Approved", "Revoked"],
                "Expired": ["Approved", "Pending"],
                "Revoked": ["Pending"]
            }

            if new_status not in valid_transitions.get(old_status, []):
                # Allow System Manager to override
                if "System Manager" not in frappe.get_roles():
                    frappe.throw(
                        _("Invalid status transition from {0} to {1}").format(
                            old_status, new_status
                        )
                    )

            # Set authorization info when status changes to Approved
            if new_status == "Approved" and old_status != "Approved":
                self.authorized_by = frappe.session.user
                self.authorization_date = today()
                self.revoked_by = None
                self.revoked_by_name = None
                self.revocation_date = None

            # Set revocation info when status changes to Revoked or Suspended
            if new_status in ["Revoked", "Suspended"] and old_status not in ["Revoked", "Suspended"]:
                self.revoked_by = frappe.session.user
                self.revocation_date = today()

            # Clear authorization info when going back to Pending
            if new_status == "Pending":
                self.authorized_by = None
                self.authorized_by_name = None
                self.authorization_date = None
                self.revoked_by = None
                self.revoked_by_name = None
                self.revocation_date = None

    def validate_validity_dates(self):
        """Validate validity date range."""
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(_("Valid From date cannot be after Valid To date"))

    def validate_pricing_restrictions(self):
        """Validate pricing restriction values."""
        if flt(self.price_floor) < 0 or flt(self.price_floor) > 100:
            frappe.throw(_("Price Floor must be between 0 and 100 percent"))

        if flt(self.price_ceiling) < 0 or flt(self.price_ceiling) > 200:
            frappe.throw(_("Price Ceiling must be between 0 and 200 percent"))

        if self.price_floor and self.price_ceiling:
            if flt(self.price_floor) > flt(self.price_ceiling):
                frappe.throw(_("Price Floor cannot be greater than Price Ceiling"))

    def validate_buybox_settings(self):
        """Validate Buy Box settings."""
        if cint(self.buybox_priority_boost) < 0 or cint(self.buybox_priority_boost) > 20:
            frappe.throw(_("Buy Box Priority Boost must be between 0 and 20"))

    def validate_tenant_isolation(self):
        """
        Validate that entry belongs to user's tenant.

        Inherits tenant from Seller Profile to ensure multi-tenant data isolation.
        """
        if not self.tenant:
            return

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            current_tenant = get_current_tenant()

            if current_tenant and self.tenant != current_tenant:
                frappe.throw(
                    _("Access denied: You can only access authorizations in your tenant")
                )
        except ImportError:
            pass

    def sync_is_active_status(self):
        """Sync is_active checkbox with authorization status."""
        if self.authorization_status == "Approved" and not self.is_active:
            self.is_active = 1
        elif self.authorization_status != "Approved" and self.is_active:
            self.is_active = 0

    def check_expiry(self):
        """Check if authorization has expired and update status."""
        if self.valid_to and self.authorization_status == "Approved":
            if getdate(self.valid_to) < getdate(today()):
                if self.auto_renew:
                    # Auto-renew: extend validity by 1 year
                    self.valid_to = add_days(getdate(self.valid_to), 365)
                    frappe.msgprint(
                        _("Authorization auto-renewed until {0}").format(self.valid_to),
                        indicator='green'
                    )
                else:
                    self.authorization_status = "Expired"
                    self.is_active = 0
                    frappe.msgprint(
                        _("Authorization has expired"),
                        indicator='red'
                    )

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_active_products(self):
        """Check for active products before allowing deletion."""
        if self.authorization_status == "Approved":
            product_count = frappe.db.count(
                "SKU Product",
                {
                    "brand": self.brand,
                    "seller": self.seller,
                    "status": "Active"
                }
            )
            if product_count > 0:
                frappe.throw(
                    _("Cannot delete authorization with {0} active product(s). "
                      "Please archive or reassign products first.").format(
                        product_count
                    )
                )

    # =========================================================================
    # PRODUCT COUNT METHODS
    # =========================================================================

    def update_product_count(self):
        """Update the current product count for this authorization."""
        count = frappe.db.count(
            "SKU Product",
            filters={
                "brand": self.brand,
                "seller": self.seller,
                "status": ("in", ["Active", "Passive"])
            }
        )
        self.db_set("current_product_count", count, update_modified=False)

    def can_add_product(self):
        """
        Check if seller can add another product under this authorization.

        Returns:
            bool: True if product can be added, False otherwise
        """
        if self.authorization_status != "Approved":
            return False

        if not self.is_active:
            return False

        if self.max_products > 0 and self.current_product_count >= self.max_products:
            return False

        return True

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_authorization_cache(self):
        """Clear cached authorization data."""
        cache_keys = [
            f"brand_gating:{self.brand}:{self.seller}",
            f"brand_authorizations:{self.brand}",
            f"seller_authorizations:{self.seller}",
        ]
        if self.tenant:
            cache_keys.append(f"brand_authorizations:{self.brand}:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # NOTIFICATION METHODS
    # =========================================================================

    def notify_status_change(self):
        """Send notification when authorization status changes."""
        if self.has_value_changed("authorization_status"):
            # This would trigger email/notification to seller
            # Implementation depends on notification settings
            pass


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def check_seller_authorization(brand, seller):
    """
    Check if a seller is authorized to sell a brand.

    Args:
        brand: The Brand name
        seller: The Seller Profile name

    Returns:
        dict: Authorization details or None if not authorized
    """
    authorization = frappe.get_all(
        "Brand Gating",
        filters={
            "brand": brand,
            "seller": seller,
            "authorization_status": "Approved",
            "is_active": 1
        },
        fields=[
            "name", "authorization_type", "is_exclusive", "priority_level",
            "valid_from", "valid_to", "product_scope", "max_products",
            "can_set_price", "price_floor", "price_ceiling", "can_discount",
            "eligible_for_buybox", "buybox_priority_boost"
        ],
        limit=1
    )

    if not authorization:
        return None

    auth = authorization[0]

    # Check validity
    if auth.valid_to and getdate(auth.valid_to) < getdate(today()):
        return None

    return auth


@frappe.whitelist()
def get_brand_authorized_sellers(brand, include_pending=False):
    """
    Get all authorized sellers for a brand.

    Args:
        brand: The Brand name
        include_pending: Whether to include pending authorizations

    Returns:
        list: List of authorized sellers
    """
    filters = {"brand": brand}

    if not include_pending:
        filters["authorization_status"] = "Approved"
        filters["is_active"] = 1

    authorizations = frappe.get_all(
        "Brand Gating",
        filters=filters,
        fields=[
            "name", "seller", "seller_name", "seller_company",
            "authorization_type", "authorization_status", "is_exclusive",
            "priority_level", "valid_from", "valid_to"
        ],
        order_by="priority_level desc, authorization_date asc"
    )

    return authorizations


@frappe.whitelist()
def get_seller_authorized_brands(seller, include_pending=False):
    """
    Get all brands a seller is authorized to sell.

    Args:
        seller: The Seller Profile name
        include_pending: Whether to include pending authorizations

    Returns:
        list: List of authorized brands
    """
    filters = {"seller": seller}

    if not include_pending:
        filters["authorization_status"] = "Approved"
        filters["is_active"] = 1

    authorizations = frappe.get_all(
        "Brand Gating",
        filters=filters,
        fields=[
            "name", "brand", "brand_name", "brand_logo",
            "authorization_type", "authorization_status", "is_exclusive",
            "priority_level", "valid_from", "valid_to",
            "product_scope", "max_products", "current_product_count"
        ],
        order_by="brand_name asc"
    )

    return authorizations


@frappe.whitelist()
def approve_authorization(name, notes=None):
    """
    Approve a brand gating authorization.

    Args:
        name: The Brand Gating name
        notes: Optional authorization notes

    Returns:
        dict: Updated authorization data
    """
    # Check permission
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager can approve authorizations"))

    doc = frappe.get_doc("Brand Gating", name)

    if doc.authorization_status == "Approved":
        return {"success": True, "message": _("Authorization is already approved")}

    doc.authorization_status = "Approved"
    if notes:
        doc.authorization_notes = notes
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "name": doc.name,
        "authorization_status": doc.authorization_status,
        "authorized_by_name": doc.authorized_by_name,
        "authorization_date": doc.authorization_date,
        "message": _("Authorization approved successfully")
    }


@frappe.whitelist()
def reject_authorization(name, notes=None):
    """
    Reject a brand gating authorization.

    Args:
        name: The Brand Gating name
        notes: Optional rejection notes

    Returns:
        dict: Updated authorization data
    """
    # Check permission
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager can reject authorizations"))

    doc = frappe.get_doc("Brand Gating", name)

    if doc.authorization_status == "Rejected":
        return {"success": True, "message": _("Authorization is already rejected")}

    doc.authorization_status = "Rejected"
    if notes:
        doc.authorization_notes = notes
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "name": doc.name,
        "authorization_status": doc.authorization_status,
        "message": _("Authorization rejected")
    }


@frappe.whitelist()
def suspend_authorization(name, notes=None):
    """
    Suspend an approved authorization.

    Args:
        name: The Brand Gating name
        notes: Optional suspension notes

    Returns:
        dict: Updated authorization data
    """
    # Check permission
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager can suspend authorizations"))

    doc = frappe.get_doc("Brand Gating", name)

    if doc.authorization_status != "Approved":
        frappe.throw(_("Only approved authorizations can be suspended"))

    doc.authorization_status = "Suspended"
    if notes:
        doc.internal_notes = (doc.internal_notes or "") + f"\nSuspended: {notes}"
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "name": doc.name,
        "authorization_status": doc.authorization_status,
        "message": _("Authorization suspended")
    }


@frappe.whitelist()
def revoke_authorization(name, notes=None):
    """
    Revoke an authorization permanently.

    Args:
        name: The Brand Gating name
        notes: Optional revocation notes

    Returns:
        dict: Updated authorization data
    """
    # Check permission
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager can revoke authorizations"))

    doc = frappe.get_doc("Brand Gating", name)

    if doc.authorization_status in ["Rejected", "Revoked"]:
        return {"success": True, "message": _("Authorization is already revoked/rejected")}

    doc.authorization_status = "Revoked"
    if notes:
        doc.internal_notes = (doc.internal_notes or "") + f"\nRevoked: {notes}"
    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "name": doc.name,
        "authorization_status": doc.authorization_status,
        "revoked_by_name": doc.revoked_by_name,
        "revocation_date": doc.revocation_date,
        "message": _("Authorization revoked")
    }


@frappe.whitelist()
def request_authorization(brand, seller, authorization_type="Standard Reseller",
                          authorization_document=None, notes=None):
    """
    Request a new brand authorization.

    Args:
        brand: The Brand name
        seller: The Seller Profile name
        authorization_type: Type of authorization requested
        authorization_document: Optional document attachment
        notes: Optional request notes

    Returns:
        dict: Created authorization data
    """
    # Check if authorization already exists
    existing = frappe.get_all(
        "Brand Gating",
        filters={
            "brand": brand,
            "seller": seller,
            "authorization_status": ("in", ["Pending", "Under Review", "Approved"])
        },
        limit=1
    )

    if existing:
        frappe.throw(_("An authorization request already exists for this brand-seller combination"))

    doc = frappe.new_doc("Brand Gating")
    doc.brand = brand
    doc.seller = seller
    doc.authorization_type = authorization_type
    doc.authorization_status = "Pending"
    if authorization_document:
        doc.authorization_document = authorization_document
    if notes:
        doc.authorization_notes = notes
    doc.insert()

    return {
        "success": True,
        "name": doc.name,
        "message": _("Authorization request submitted successfully")
    }


@frappe.whitelist()
def get_buybox_eligibility(brand, seller):
    """
    Get Buy Box eligibility for a brand-seller combination.

    Args:
        brand: The Brand name
        seller: The Seller Profile name

    Returns:
        dict: Buy Box eligibility details
    """
    authorization = frappe.get_all(
        "Brand Gating",
        filters={
            "brand": brand,
            "seller": seller,
            "authorization_status": "Approved",
            "is_active": 1
        },
        fields=[
            "name", "eligible_for_buybox", "buybox_priority_boost",
            "suppress_unauthorized", "authorization_type"
        ],
        limit=1
    )

    if not authorization:
        return {
            "is_authorized": False,
            "eligible_for_buybox": False,
            "priority_boost": 0,
            "message": _("Seller is not authorized for this brand")
        }

    auth = authorization[0]
    return {
        "is_authorized": True,
        "eligible_for_buybox": auth.eligible_for_buybox,
        "priority_boost": cint(auth.buybox_priority_boost),
        "authorization_type": auth.authorization_type,
        "suppress_unauthorized": auth.suppress_unauthorized
    }


@frappe.whitelist()
def check_expiring_authorizations(days=30):
    """
    Get authorizations expiring within specified days.

    Args:
        days: Number of days to look ahead (default 30)

    Returns:
        list: Authorizations expiring soon
    """
    from frappe.utils import add_days

    expiry_date = add_days(today(), cint(days))

    expiring = frappe.get_all(
        "Brand Gating",
        filters={
            "authorization_status": "Approved",
            "is_active": 1,
            "valid_to": ["<=", expiry_date],
            "valid_to": [">=", today()]
        },
        fields=[
            "name", "brand", "brand_name", "seller", "seller_name",
            "valid_to", "auto_renew", "tenant"
        ],
        order_by="valid_to asc"
    )

    return expiring


@frappe.whitelist()
def get_authorization_statistics(brand=None, seller=None, tenant=None):
    """
    Get brand gating statistics.

    Args:
        brand: Optional brand filter
        seller: Optional seller filter
        tenant: Optional tenant filter

    Returns:
        dict: Statistics including counts by status
    """
    filters = {}
    if brand:
        filters["brand"] = brand
    if seller:
        filters["seller"] = seller
    if tenant:
        filters["tenant"] = tenant

    authorizations = frappe.get_all(
        "Brand Gating",
        filters=filters,
        fields=["authorization_status", "authorization_type", "is_exclusive"]
    )

    # Count by status
    status_counts = {}
    type_counts = {}
    exclusive_count = 0

    for auth in authorizations:
        status = auth.authorization_status
        auth_type = auth.authorization_type

        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[auth_type] = type_counts.get(auth_type, 0) + 1

        if auth.is_exclusive:
            exclusive_count += 1

    return {
        "total": len(authorizations),
        "by_status": status_counts,
        "by_type": type_counts,
        "exclusive_count": exclusive_count,
        "approved_count": status_counts.get("Approved", 0),
        "pending_count": status_counts.get("Pending", 0) + status_counts.get("Under Review", 0)
    }
