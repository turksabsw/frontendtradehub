# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
SKU Product DocType for Trade Hub B2B Marketplace.

This module implements the core SKU Product DocType which represents a product
listing in the marketplace. Key features include:
- Multi-tenant data isolation via tenant field
- Product lifecycle states (Draft, Active, Passive, Archive)
- fetch_from pattern for seller and category information
- ERPNext integration support for inventory sync
- SEO metadata management
- Validation rules for pricing and inventory
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate, now_datetime, cstr


class SKUProduct(Document):
    """
    SKU Product DocType for the Trade Hub B2B marketplace.

    Each SKU Product represents a unique product listing with:
    - Unique SKU code identifier
    - Multi-tenant isolation via seller's tenant
    - Product lifecycle management (Draft -> Active -> Passive -> Archive)
    - Pricing and inventory management
    - SEO optimization fields
    - ERPNext integration capability
    """

    def before_insert(self):
        """Set defaults before inserting a new product."""
        # Ensure tenant is set from seller
        self.set_tenant_from_seller()

        # Generate URL slug if not provided
        if not self.url_slug:
            self.generate_url_slug()

        # Set default SEO fields if not provided
        if not self.seo_title:
            self.seo_title = self.product_name[:60] if self.product_name else ""

    def validate(self):
        """Validate product data before saving."""
        self.validate_sku_code()
        self.validate_pricing()
        self.validate_inventory()
        self.validate_physical_attributes()
        self.validate_seo_fields()
        self.validate_url_slug()
        self.validate_tenant_isolation()
        self.validate_status_transition()

    def on_update(self):
        """Actions after product is updated."""
        self.clear_product_cache()

        # Sync with ERPNext if enabled
        if self.sync_with_erpnext:
            self.enqueue_erpnext_sync()

    def after_insert(self):
        """Actions after product is created."""
        # Notify seller of new product
        self.notify_product_created()

    def on_trash(self):
        """Prevent deletion of active products with orders."""
        self.check_linked_documents()

    # =========================================================================
    # TENANT ISOLATION
    # =========================================================================

    def set_tenant_from_seller(self):
        """
        Set tenant from seller's tenant.

        This ensures multi-tenant data isolation by automatically inheriting
        the tenant from the seller profile.
        """
        if self.seller and not self.tenant:
            seller_tenant = frappe.db.get_value(
                "Seller Profile", self.seller, "tenant"
            )
            if seller_tenant:
                self.tenant = seller_tenant

    def validate_tenant_isolation(self):
        """
        Validate that product belongs to user's tenant.

        Prevents cross-tenant data access by verifying the product's tenant
        matches the current user's tenant (unless user is System Manager).
        """
        if not self.tenant:
            # Try to set from seller one more time
            self.set_tenant_from_seller()

        if not self.tenant:
            frappe.throw(_("Product must belong to a tenant"))

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access products in your tenant")
            )

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_sku_code(self):
        """Validate SKU code format and uniqueness."""
        if not self.sku_code:
            frappe.throw(_("SKU Code is required"))

        # Clean and uppercase SKU code
        self.sku_code = cstr(self.sku_code).strip().upper()

        # Validate format (alphanumeric with dashes/underscores)
        if not re.match(r'^[A-Z0-9\-_]+$', self.sku_code):
            frappe.throw(
                _("SKU Code can only contain letters, numbers, dashes, and underscores")
            )

        # Check uniqueness within tenant
        existing = frappe.db.get_value(
            "SKU Product",
            {
                "sku_code": self.sku_code,
                "tenant": self.tenant,
                "name": ("!=", self.name)
            },
            "name"
        )
        if existing:
            frappe.throw(
                _("SKU Code {0} already exists in this tenant").format(self.sku_code)
            )

    def validate_pricing(self):
        """Validate pricing fields."""
        if flt(self.base_price) < 0:
            frappe.throw(_("Base Price cannot be negative"))

        if cint(self.min_order_quantity) < 1:
            self.min_order_quantity = 1

        if cint(self.max_order_quantity) > 0:
            if cint(self.max_order_quantity) < cint(self.min_order_quantity):
                frappe.throw(
                    _("Max Order Quantity cannot be less than Min Order Quantity")
                )

    def validate_inventory(self):
        """Validate inventory fields."""
        if not self.allow_negative_stock and flt(self.stock_quantity) < 0:
            frappe.throw(_("Stock Quantity cannot be negative"))

    def validate_physical_attributes(self):
        """Validate physical dimension fields."""
        for field in ['weight', 'length', 'width', 'height']:
            value = flt(getattr(self, field, 0))
            if value < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.capitalize())
                )

    def validate_seo_fields(self):
        """Validate SEO fields length."""
        if self.seo_title and len(self.seo_title) > 60:
            frappe.msgprint(
                _("SEO Title exceeds recommended 60 characters"),
                indicator='orange',
                alert=True
            )

        if self.seo_description and len(self.seo_description) > 160:
            frappe.msgprint(
                _("SEO Description exceeds recommended 160 characters"),
                indicator='orange',
                alert=True
            )

    def validate_url_slug(self):
        """Validate and sanitize URL slug."""
        if self.url_slug:
            # Sanitize slug
            self.url_slug = self.sanitize_slug(self.url_slug)

            # Check uniqueness
            existing = frappe.db.get_value(
                "SKU Product",
                {"url_slug": self.url_slug, "name": ("!=", self.name)},
                "name"
            )
            if existing:
                frappe.throw(
                    _("URL Slug {0} is already in use").format(self.url_slug)
                )

    def validate_status_transition(self):
        """Validate status transitions follow allowed workflow."""
        if self.is_new():
            if self.status not in ["Draft", "Active"]:
                frappe.throw(_("New products must start in Draft or Active status"))
            return

        # Get previous status
        old_status = frappe.db.get_value("SKU Product", self.name, "status")
        if not old_status or old_status == self.status:
            return

        # Define allowed transitions
        allowed_transitions = {
            "Draft": ["Active", "Archive"],
            "Active": ["Passive", "Archive"],
            "Passive": ["Active", "Archive"],
            "Archive": []  # Cannot transition from Archive
        }

        if self.status not in allowed_transitions.get(old_status, []):
            frappe.throw(
                _("Cannot transition from {0} to {1}").format(old_status, self.status)
            )

    # =========================================================================
    # URL SLUG GENERATION
    # =========================================================================

    def generate_url_slug(self):
        """Generate SEO-friendly URL slug from product name."""
        if not self.product_name:
            return

        slug = self.sanitize_slug(self.product_name)

        # Ensure uniqueness
        base_slug = slug
        counter = 1
        while frappe.db.exists("SKU Product", {"url_slug": slug, "name": ("!=", self.name or "")}):
            slug = f"{base_slug}-{counter}"
            counter += 1

        self.url_slug = slug

    def sanitize_slug(self, text):
        """
        Sanitize text into URL-friendly slug.

        Args:
            text: Text to convert to slug

        Returns:
            str: URL-friendly slug
        """
        # Convert to lowercase
        slug = cstr(text).lower().strip()

        # Replace Turkish characters
        turkish_map = {
            'c': 'c', 's': 's', 'g': 'g', 'i': 'i', 'o': 'o', 'u': 'u',
            'C': 'c', 'S': 's', 'G': 'g', 'I': 'i', 'O': 'o', 'U': 'u'
        }
        for tr_char, en_char in turkish_map.items():
            slug = slug.replace(tr_char, en_char)

        # Replace spaces and special chars with dashes
        slug = re.sub(r'[^a-z0-9]+', '-', slug)

        # Remove leading/trailing dashes
        slug = slug.strip('-')

        # Limit length
        return slug[:100]

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def activate(self):
        """Activate the product for marketplace visibility."""
        if self.status == "Archive":
            frappe.throw(_("Cannot activate archived product"))

        self.status = "Active"
        self.is_published = 1
        self.save()
        return True

    def deactivate(self):
        """Deactivate the product (set to Passive)."""
        if self.status == "Archive":
            frappe.throw(_("Cannot deactivate archived product"))

        self.status = "Passive"
        self.is_published = 0
        self.save()
        return True

    def archive(self):
        """Archive the product (permanent deactivation)."""
        self.status = "Archive"
        self.is_published = 0
        self.save()
        return True

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked orders
        order_count = frappe.db.count(
            "Order Item",
            {"sku_product": self.name}
        )
        if order_count > 0:
            frappe.throw(
                _("Cannot delete product with {0} linked order(s). "
                  "Please archive instead.").format(order_count)
            )

        # Check for active buy box entries
        buybox_count = frappe.db.count(
            "Buy Box Entry",
            {"sku_product": self.name}
        )
        if buybox_count > 0:
            frappe.throw(
                _("Cannot delete product with {0} Buy Box entries. "
                  "Please remove Buy Box entries first.").format(buybox_count)
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_product_cache(self):
        """Clear cached product data."""
        cache_keys = [
            f"sku_product:{self.name}",
            f"sku_product:sku:{self.sku_code}",
            f"sku_product:slug:{self.url_slug}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

        # Clear category product list cache if category changed
        if self.category:
            frappe.cache().delete_value(f"category_products:{self.category}")

    # =========================================================================
    # ERPNEXT INTEGRATION
    # =========================================================================

    def enqueue_erpnext_sync(self):
        """Enqueue background job for ERPNext sync."""
        if not self.sync_with_erpnext:
            return

        frappe.enqueue(
            "tr_tradehub.utils.erpnext_sync.sync_sku_to_item",
            sku_product=self.name,
            queue="short"
        )

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def notify_product_created(self):
        """Notify seller when product is created."""
        # Get seller user
        seller_user = frappe.db.get_value(
            "Seller Profile", self.seller, "user"
        )
        if not seller_user:
            return

        frappe.publish_realtime(
            event="product_created",
            message={
                "product_name": self.product_name,
                "sku_code": self.sku_code,
                "status": self.status
            },
            user=seller_user
        )

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_display_price(self, currency=None):
        """
        Get formatted display price.

        Args:
            currency: Optional currency to convert to

        Returns:
            str: Formatted price string
        """
        from frappe.utils import fmt_money
        return fmt_money(
            self.base_price,
            currency=currency or self.currency
        )

    def is_in_stock(self):
        """Check if product is in stock."""
        if not self.is_stock_item:
            return True
        return flt(self.stock_quantity) > 0 or self.allow_negative_stock

    def get_available_quantity(self):
        """Get available quantity for orders."""
        if not self.is_stock_item:
            return float('inf')
        if self.allow_negative_stock:
            return float('inf')
        return max(0, flt(self.stock_quantity))


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_product_by_sku(sku_code, tenant=None):
    """
    Get product by SKU code.

    Args:
        sku_code: The SKU code to search for
        tenant: Optional tenant filter

    Returns:
        dict: Product data or None
    """
    filters = {"sku_code": sku_code.upper()}
    if tenant:
        filters["tenant"] = tenant
    else:
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    product_name = frappe.db.get_value("SKU Product", filters, "name")
    if product_name:
        return frappe.get_doc("SKU Product", product_name).as_dict()
    return None


@frappe.whitelist()
def get_product_by_slug(url_slug):
    """
    Get product by URL slug.

    Args:
        url_slug: The URL slug to search for

    Returns:
        dict: Product data or None
    """
    product_name = frappe.db.get_value(
        "SKU Product",
        {"url_slug": url_slug, "status": "Active"},
        "name"
    )
    if product_name:
        return frappe.get_doc("SKU Product", product_name).as_dict()
    return None


@frappe.whitelist()
def activate_product(product_name):
    """
    Activate a product.

    Args:
        product_name: Name of the product to activate

    Returns:
        dict: Result with success status
    """
    product = frappe.get_doc("SKU Product", product_name)
    if product.activate():
        return {"success": True, "message": _("Product activated successfully")}
    return {"success": False, "message": _("Failed to activate product")}


@frappe.whitelist()
def deactivate_product(product_name):
    """
    Deactivate a product.

    Args:
        product_name: Name of the product to deactivate

    Returns:
        dict: Result with success status
    """
    product = frappe.get_doc("SKU Product", product_name)
    if product.deactivate():
        return {"success": True, "message": _("Product deactivated successfully")}
    return {"success": False, "message": _("Failed to deactivate product")}


@frappe.whitelist()
def archive_product(product_name):
    """
    Archive a product.

    Args:
        product_name: Name of the product to archive

    Returns:
        dict: Result with success status
    """
    product = frappe.get_doc("SKU Product", product_name)
    if product.archive():
        return {"success": True, "message": _("Product archived successfully")}
    return {"success": False, "message": _("Failed to archive product")}


@frappe.whitelist()
def check_stock_availability(product_name, quantity):
    """
    Check if requested quantity is available.

    Args:
        product_name: Name of the product
        quantity: Requested quantity

    Returns:
        dict: Availability status
    """
    product = frappe.get_doc("SKU Product", product_name)
    available = product.get_available_quantity()
    requested = flt(quantity)

    return {
        "available": available >= requested,
        "available_quantity": available,
        "requested_quantity": requested,
        "is_stock_item": product.is_stock_item
    }
