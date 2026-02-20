# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Brand DocType for Trade Hub B2B Marketplace.

This module implements the Brand DocType with logo, description, and verification
status management. Brands can be global or tenant-specific, and require verification
before being fully trusted in the marketplace.

Key Features:
- Logo and branding information management
- Verification workflow (Pending -> Under Review -> Verified/Rejected)
- Multi-tenant support (brands can be global or tenant-specific)
- SEO metadata for brand pages
- URL slug generation for SEO-friendly URLs
- Product count tracking
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, today, getdate


class Brand(Document):
    """
    Brand DocType with verification workflow and multi-tenant support.

    Brands represent product manufacturers or labels. They can be registered
    by sellers and require verification before being marked as trusted.
    """

    def before_insert(self):
        """Set default values before inserting a new brand."""
        self.set_registration_info()
        self.generate_url_slug()
        self.set_tenant_from_user()

    def validate(self):
        """Validate brand data before saving."""
        self.validate_brand_name()
        self.validate_verification_status()
        self.validate_tenant_consistency()
        self.validate_seo_fields()
        self.validate_year_established()
        self.generate_url_slug()

    def on_update(self):
        """Actions after brand is updated."""
        self.clear_brand_cache()

    def on_trash(self):
        """Prevent deletion of brand with linked products."""
        self.check_linked_products()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_registration_info(self):
        """Set registration information for new brands."""
        if not self.registered_by:
            self.registered_by = frappe.session.user
        if not self.registration_date:
            self.registration_date = today()

    def set_tenant_from_user(self):
        """Set tenant from current user if not already set."""
        if not self.tenant and not self.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant:
                self.tenant = user_tenant

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_brand_name(self):
        """Validate brand name is not empty and follows naming conventions."""
        if not self.brand_name:
            frappe.throw(_("Brand Name is required"))

        # Check for invalid characters
        if any(char in self.brand_name for char in ['<', '>', '"', '\\']):
            frappe.throw(_("Brand Name contains invalid characters"))

        # Check length
        if len(self.brand_name) > 140:
            frappe.throw(_("Brand Name cannot exceed 140 characters"))

        # Trim whitespace
        self.brand_name = self.brand_name.strip()

    def validate_verification_status(self):
        """Validate verification status transitions."""
        if self.has_value_changed("verification_status"):
            old_status = self.get_doc_before_save()
            old_status = old_status.verification_status if old_status else "Pending"
            new_status = self.verification_status

            # Define valid transitions
            valid_transitions = {
                "Pending": ["Under Review", "Verified", "Rejected"],
                "Under Review": ["Verified", "Rejected", "Pending"],
                "Verified": ["Rejected", "Pending"],
                "Rejected": ["Pending", "Under Review"]
            }

            if new_status not in valid_transitions.get(old_status, []):
                # Allow System Manager to override
                if not frappe.has_permission("Brand", "write", user=frappe.session.user):
                    frappe.throw(
                        _("Invalid status transition from {0} to {1}").format(
                            old_status, new_status
                        )
                    )

            # Set verification info when status changes to Verified or Rejected
            if new_status in ["Verified", "Rejected"]:
                self.verified_by = frappe.session.user
                self.verification_date = today()
            elif new_status == "Pending":
                # Reset verification info when going back to Pending
                self.verified_by = None
                self.verification_date = None

    def validate_tenant_consistency(self):
        """Ensure tenant consistency for brands."""
        # Global brands should not have tenant
        if self.is_global and self.tenant:
            self.tenant = None
            self.tenant_name = None

        # Non-global brands need tenant
        if not self.is_global and not self.tenant:
            # Only admin can create global brands
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Please select a tenant or mark the brand as global")
                )

    def validate_seo_fields(self):
        """Validate SEO field lengths."""
        if self.seo_title and len(self.seo_title) > 60:
            frappe.msgprint(
                _("SEO Title exceeds recommended length of 60 characters"),
                indicator="orange"
            )

        if self.seo_description and len(self.seo_description) > 160:
            frappe.msgprint(
                _("SEO Description exceeds recommended length of 160 characters"),
                indicator="orange"
            )

    def validate_year_established(self):
        """Validate year established is reasonable."""
        if self.year_established:
            current_year = getdate(today()).year
            if self.year_established < 1800 or self.year_established > current_year:
                frappe.throw(
                    _("Year Established must be between 1800 and {0}").format(
                        current_year
                    )
                )

    # =========================================================================
    # URL SLUG GENERATION
    # =========================================================================

    def generate_url_slug(self):
        """Generate SEO-friendly URL slug from brand name."""
        if not self.url_slug and self.brand_name:
            # Convert to lowercase and replace special characters
            slug = self.brand_name.lower()

            # Turkish character replacements
            turkish_map = {
                'ı': 'i', 'ğ': 'g', 'ü': 'u', 'ş': 's', 'ö': 'o', 'ç': 'c',
                'İ': 'i', 'Ğ': 'g', 'Ü': 'u', 'Ş': 's', 'Ö': 'o', 'Ç': 'c'
            }
            for tr_char, en_char in turkish_map.items():
                slug = slug.replace(tr_char, en_char)

            # Replace spaces and special chars with hyphens
            slug = re.sub(r'[^a-z0-9\-]', '-', slug)
            # Remove consecutive hyphens
            slug = re.sub(r'-+', '-', slug)
            # Remove leading/trailing hyphens
            slug = slug.strip('-')

            # Ensure uniqueness
            base_slug = slug
            counter = 1
            while frappe.db.exists("Brand", {"url_slug": slug, "name": ("!=", self.name or "")}):
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.url_slug = slug

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_products(self):
        """Check for linked products before allowing deletion."""
        product_count = frappe.db.count("SKU Product", {"brand": self.name})
        if product_count > 0:
            frappe.throw(
                _("Cannot delete brand with {0} linked product(s). "
                  "Please reassign products to another brand first.").format(
                    product_count
                )
            )

    # =========================================================================
    # PRODUCT COUNT METHODS
    # =========================================================================

    def update_product_count(self):
        """Update the product count for this brand."""
        count = frappe.db.count(
            "SKU Product",
            filters={"brand": self.name, "status": "Active"}
        )
        self.db_set("product_count", count, update_modified=False)

    def get_active_product_count(self):
        """
        Get count of active products for this brand.

        Returns:
            int: Number of active products
        """
        return frappe.db.count(
            "SKU Product",
            filters={"brand": self.name, "status": "Active"}
        )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_brand_cache(self):
        """Clear cached brand data."""
        cache_keys = [
            "brand_list",
            f"brand:{self.name}",
        ]
        if self.tenant:
            cache_keys.append(f"brand_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_brand_list(tenant=None, include_disabled=False, verified_only=False):
    """
    Get list of brands.

    Args:
        tenant: Optional tenant filter (None = global brands only)
        include_disabled: Include disabled brands
        verified_only: Only include verified brands

    Returns:
        list: List of brand documents
    """
    filters = {}

    if not include_disabled:
        filters["enabled"] = 1

    if verified_only:
        filters["verification_status"] = "Verified"

    if tenant:
        # Include tenant-specific and global brands
        brands = frappe.get_all(
            "Brand",
            or_filters=[
                ["tenant", "=", tenant],
                ["is_global", "=", 1]
            ],
            filters=filters,
            fields=[
                "name", "brand_name", "logo", "verification_status",
                "url_slug", "display_order", "product_count"
            ],
            order_by="display_order asc, brand_name asc"
        )
    else:
        # Only global brands
        filters["is_global"] = 1
        brands = frappe.get_all(
            "Brand",
            filters=filters,
            fields=[
                "name", "brand_name", "logo", "verification_status",
                "url_slug", "display_order", "product_count"
            ],
            order_by="display_order asc, brand_name asc"
        )

    return brands


@frappe.whitelist()
def get_brand_by_slug(slug):
    """
    Get brand by URL slug.

    Args:
        slug: The URL slug of the brand

    Returns:
        dict: Brand data
    """
    brand = frappe.db.get_value(
        "Brand",
        {"url_slug": slug, "enabled": 1},
        ["name", "brand_name", "description", "logo",
         "verification_status", "website", "country_of_origin",
         "year_established", "seo_title", "seo_description",
         "seo_keywords", "product_count"],
        as_dict=True
    )

    if not brand:
        frappe.throw(_("Brand not found"))

    return brand


@frappe.whitelist()
def verify_brand(brand_name, status, notes=None):
    """
    Verify or reject a brand.

    Args:
        brand_name: Name of the brand to verify
        status: New verification status (Verified or Rejected)
        notes: Optional verification notes

    Returns:
        dict: Updated brand data
    """
    # Check permission
    if not frappe.has_permission("Brand", "write"):
        frappe.throw(_("Insufficient permissions to verify brands"))

    if status not in ["Verified", "Rejected"]:
        frappe.throw(_("Status must be 'Verified' or 'Rejected'"))

    brand = frappe.get_doc("Brand", brand_name)
    brand.verification_status = status
    if notes:
        brand.verification_notes = notes
    brand.save(ignore_permissions=True)

    return {
        "name": brand.name,
        "brand_name": brand.brand_name,
        "verification_status": brand.verification_status,
        "verified_by_name": brand.verified_by_name,
        "verification_date": brand.verification_date
    }


@frappe.whitelist()
def get_brand_products(brand_name, limit=20, offset=0):
    """
    Get products for a brand.

    Args:
        brand_name: Name of the brand
        limit: Number of products to return
        offset: Pagination offset

    Returns:
        dict: Products list and total count
    """
    if not frappe.db.exists("Brand", brand_name):
        frappe.throw(_("Brand {0} not found").format(brand_name))

    filters = {"brand": brand_name, "status": "Active"}

    total = frappe.db.count("SKU Product", filters=filters)
    products = frappe.get_all(
        "SKU Product",
        filters=filters,
        fields=[
            "name", "sku_code", "product_name", "base_price", "currency",
            "thumbnail", "url_slug", "seller_name"
        ],
        limit_page_length=cint(limit),
        limit_start=cint(offset),
        order_by="modified desc"
    )

    return {
        "products": products,
        "total": total,
        "limit": cint(limit),
        "offset": cint(offset)
    }


@frappe.whitelist()
def submit_for_verification(brand_name):
    """
    Submit a brand for verification review.

    Args:
        brand_name: Name of the brand to submit

    Returns:
        dict: Updated brand data
    """
    brand = frappe.get_doc("Brand", brand_name)

    # Check if user owns or can edit this brand
    if brand.registered_by != frappe.session.user and not frappe.has_permission("Brand", "write"):
        frappe.throw(_("You can only submit brands you registered"))

    if brand.verification_status != "Pending":
        frappe.throw(_("Only pending brands can be submitted for verification"))

    brand.verification_status = "Under Review"
    brand.save()

    return {
        "name": brand.name,
        "brand_name": brand.brand_name,
        "verification_status": brand.verification_status
    }


@frappe.whitelist()
def update_product_counts():
    """
    Update product counts for all brands.
    Intended to be called via scheduler or manually.

    Returns:
        dict: Number of brands updated
    """
    brands = frappe.get_all("Brand", fields=["name"])
    updated = 0

    for brand_data in brands:
        brand = frappe.get_doc("Brand", brand_data.name)
        old_count = brand.product_count or 0
        brand.update_product_count()
        if brand.product_count != old_count:
            updated += 1

    frappe.db.commit()

    return {"updated_count": updated, "total_brands": len(brands)}
