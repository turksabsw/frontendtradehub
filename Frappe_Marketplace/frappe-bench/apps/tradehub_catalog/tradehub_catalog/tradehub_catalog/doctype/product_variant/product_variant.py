# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Product Variant DocType for Trade Hub B2B Marketplace.

This module implements the Product Variant DocType which represents a specific
variation of a parent SKU Product. Key features include:
- Multi-tenant data isolation via tenant field (inherited from SKU Product)
- Variant attributes (color, size, material, packaging)
- Individual stock and price tracking
- fetch_from pattern for parent product information
- ERPNext integration support for inventory sync
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate, now_datetime, cstr


class ProductVariant(Document):
    """
    Product Variant DocType for the Trade Hub B2B marketplace.

    Each Product Variant represents a specific variation of a parent SKU Product with:
    - Unique variant code identifier
    - Multi-tenant isolation via parent product's tenant
    - Variant attributes (color, size, material, packaging)
    - Individual stock and pricing management
    - Optional physical attribute overrides
    """

    def before_insert(self):
        """Set defaults before inserting a new variant."""
        # Ensure tenant and seller are set from parent product
        self.set_parent_fields()

        # Generate variant code if not provided
        if not self.variant_code:
            self.generate_variant_code()

        # Generate variant name if not provided
        if not self.variant_name:
            self.generate_variant_name()

    def validate(self):
        """Validate variant data before saving."""
        self.validate_parent_product()
        self.validate_variant_code()
        self.validate_pricing()
        self.validate_inventory()
        self.validate_physical_attributes()
        self.validate_tenant_isolation()
        self.validate_default_variant()
        self.validate_barcode_uniqueness()
        self.calculate_final_price()

    def on_update(self):
        """Actions after variant is updated."""
        self.clear_variant_cache()

        # Sync with ERPNext if enabled
        if self.sync_with_erpnext:
            self.enqueue_erpnext_sync()

    def on_trash(self):
        """Prevent deletion of variants with linked orders."""
        self.check_linked_documents()

    # =========================================================================
    # PARENT PRODUCT FIELD INHERITANCE
    # =========================================================================

    def set_parent_fields(self):
        """
        Set fields from parent SKU Product.

        This ensures multi-tenant data isolation by automatically inheriting
        the tenant and seller from the parent product.
        """
        if not self.sku_product:
            return

        parent = frappe.get_doc("SKU Product", self.sku_product)

        # Set ownership fields if not already set
        if not self.tenant:
            self.tenant = parent.tenant
        if not self.seller:
            self.seller = parent.seller

    # =========================================================================
    # TENANT ISOLATION
    # =========================================================================

    def validate_tenant_isolation(self):
        """
        Validate that variant belongs to user's tenant.

        Prevents cross-tenant data access by verifying the variant's tenant
        matches the current user's tenant (unless user is System Manager).
        """
        if not self.tenant:
            # Try to set from parent product
            self.set_parent_fields()

        if not self.tenant:
            frappe.throw(_("Variant must belong to a tenant"))

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access variants in your tenant")
            )

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_parent_product(self):
        """Validate parent SKU Product exists and is accessible."""
        if not self.sku_product:
            frappe.throw(_("Parent SKU Product is required"))

        # Check parent exists
        if not frappe.db.exists("SKU Product", self.sku_product):
            frappe.throw(
                _("SKU Product {0} does not exist").format(self.sku_product)
            )

        # Check parent is not archived
        parent_status = frappe.db.get_value(
            "SKU Product", self.sku_product, "status"
        )
        if parent_status == "Archive":
            frappe.throw(
                _("Cannot create variant for archived product {0}").format(
                    self.sku_product
                )
            )

    def validate_variant_code(self):
        """Validate variant code format and uniqueness."""
        if not self.variant_code:
            self.generate_variant_code()
            return

        # Clean and uppercase variant code
        self.variant_code = cstr(self.variant_code).strip().upper()

        # Validate format (alphanumeric with dashes/underscores)
        if not re.match(r'^[A-Z0-9\-_]+$', self.variant_code):
            frappe.throw(
                _("Variant Code can only contain letters, numbers, dashes, and underscores")
            )

        # Check uniqueness globally (variant codes should be unique)
        existing = frappe.db.get_value(
            "Product Variant",
            {
                "variant_code": self.variant_code,
                "name": ("!=", self.name)
            },
            "name"
        )
        if existing:
            frappe.throw(
                _("Variant Code {0} already exists").format(self.variant_code)
            )

    def validate_pricing(self):
        """Validate pricing fields."""
        if flt(self.variant_price) < 0:
            frappe.throw(_("Variant Price cannot be negative"))

        if self.price_adjustment_type == "Percentage":
            if flt(self.price_adjustment) < -100:
                frappe.throw(
                    _("Percentage price adjustment cannot be less than -100%")
                )

    def validate_inventory(self):
        """Validate inventory fields."""
        if not self.allow_negative_stock and flt(self.variant_stock) < 0:
            frappe.throw(_("Variant Stock cannot be negative"))

    def validate_physical_attributes(self):
        """Validate physical dimension fields."""
        for field in ['weight', 'length', 'width', 'height']:
            value = flt(getattr(self, field, 0))
            if value < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.capitalize())
                )

    def validate_default_variant(self):
        """Ensure only one default variant per product."""
        if not self.is_default:
            return

        # Check for existing default variant
        existing_default = frappe.db.get_value(
            "Product Variant",
            {
                "sku_product": self.sku_product,
                "is_default": 1,
                "name": ("!=", self.name)
            },
            "name"
        )

        if existing_default:
            # Unset the existing default
            frappe.db.set_value(
                "Product Variant",
                existing_default,
                "is_default",
                0
            )
            frappe.msgprint(
                _("Previous default variant {0} has been unset").format(
                    existing_default
                ),
                alert=True
            )

    def validate_barcode_uniqueness(self):
        """Validate barcode uniqueness if provided."""
        for field in ['barcode', 'ean_code', 'gtin', 'mpn']:
            value = getattr(self, field, None)
            if not value:
                continue

            # Check uniqueness
            existing = frappe.db.get_value(
                "Product Variant",
                {
                    field: value,
                    "name": ("!=", self.name)
                },
                "name"
            )
            if existing:
                frappe.throw(
                    _("{0} '{1}' is already in use by variant {2}").format(
                        field.upper().replace("_", " "),
                        value,
                        existing
                    )
                )

    # =========================================================================
    # PRICE CALCULATION
    # =========================================================================

    def calculate_final_price(self):
        """Calculate final variant price from base price and adjustment."""
        if not self.sku_product:
            return

        # Get base price from parent product
        base_price = frappe.db.get_value(
            "SKU Product", self.sku_product, "base_price"
        ) or 0

        # If variant price is explicitly set and non-zero, use it
        if flt(self.variant_price) > 0:
            return

        # Otherwise calculate from base price + adjustment
        adjustment = flt(self.price_adjustment)

        if self.price_adjustment_type == "Percentage":
            self.variant_price = flt(base_price) * (1 + adjustment / 100)
        else:
            self.variant_price = flt(base_price) + adjustment

    # =========================================================================
    # CODE GENERATION
    # =========================================================================

    def generate_variant_code(self):
        """Generate variant code from parent SKU and attributes."""
        if not self.sku_product:
            return

        # Get parent SKU code
        sku_code = frappe.db.get_value(
            "SKU Product", self.sku_product, "sku_code"
        ) or ""

        # Build variant suffix from attributes
        parts = [sku_code]

        if self.color:
            parts.append(self.sanitize_code_part(self.color[:10]))
        if self.size:
            parts.append(self.sanitize_code_part(self.size[:10]))
        if self.material:
            parts.append(self.sanitize_code_part(self.material[:10]))

        code = "-".join(parts)

        # Ensure uniqueness
        base_code = code
        counter = 1
        while frappe.db.exists(
            "Product Variant",
            {"variant_code": code, "name": ("!=", self.name or "")}
        ):
            code = f"{base_code}-{counter}"
            counter += 1

        self.variant_code = code.upper()

    def generate_variant_name(self):
        """Generate display name from parent product and attributes."""
        if not self.sku_product:
            return

        # Get parent product name
        product_name = frappe.db.get_value(
            "SKU Product", self.sku_product, "product_name"
        ) or ""

        # Build variant name from attributes
        attributes = []
        if self.color:
            attributes.append(self.color)
        if self.size:
            attributes.append(self.size)
        if self.material:
            attributes.append(self.material)
        if self.packaging:
            attributes.append(self.packaging)

        if attributes:
            self.variant_name = f"{product_name} - {' / '.join(attributes)}"
        else:
            self.variant_name = product_name

    def sanitize_code_part(self, text):
        """Sanitize text for use in variant code."""
        if not text:
            return ""

        # Convert to uppercase and remove special characters
        code = cstr(text).upper().strip()

        # Replace Turkish characters
        turkish_map = {
            'C': 'C', 'S': 'S', 'G': 'G', 'I': 'I', 'O': 'O', 'U': 'U',
            'c': 'c', 's': 's', 'g': 'g', 'i': 'i', 'o': 'o', 'u': 'u'
        }
        for tr_char, en_char in turkish_map.items():
            code = code.replace(tr_char, en_char)

        # Keep only alphanumeric
        code = re.sub(r'[^A-Z0-9]', '', code)

        return code

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def activate(self):
        """Activate the variant for availability."""
        if self.status == "Discontinued":
            frappe.throw(_("Cannot activate discontinued variant"))

        self.status = "Active"
        self.save()
        return True

    def deactivate(self):
        """Deactivate the variant."""
        self.status = "Inactive"
        self.save()
        return True

    def discontinue(self):
        """Discontinue the variant (permanent deactivation)."""
        self.status = "Discontinued"
        self.is_default = 0
        self.save()
        return True

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked order items
        order_count = frappe.db.count(
            "Order Item",
            {"product_variant": self.name}
        )
        if order_count > 0:
            frappe.throw(
                _("Cannot delete variant with {0} linked order(s). "
                  "Please discontinue instead.").format(order_count)
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_variant_cache(self):
        """Clear cached variant data."""
        cache_keys = [
            f"product_variant:{self.name}",
            f"product_variant:code:{self.variant_code}",
            f"product_variants:{self.sku_product}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # ERPNEXT INTEGRATION
    # =========================================================================

    def enqueue_erpnext_sync(self):
        """Enqueue background job for ERPNext sync."""
        if not self.sync_with_erpnext:
            return

        frappe.enqueue(
            "tr_tradehub.utils.erpnext_sync.sync_variant_to_item",
            product_variant=self.name,
            queue="short"
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
            self.variant_price,
            currency=currency or self.currency
        )

    def is_in_stock(self):
        """Check if variant is in stock."""
        if not self.is_stock_item:
            return True
        return flt(self.variant_stock) > 0 or self.allow_negative_stock

    def get_available_quantity(self):
        """Get available quantity for orders."""
        if not self.is_stock_item:
            return float('inf')
        if self.allow_negative_stock:
            return float('inf')
        return max(0, flt(self.variant_stock))

    def get_attribute_display(self):
        """Get formatted attribute display string."""
        attributes = []
        if self.color:
            attributes.append(f"Color: {self.color}")
        if self.size:
            attributes.append(f"Size: {self.size}")
        if self.material:
            attributes.append(f"Material: {self.material}")
        if self.packaging:
            attributes.append(f"Packaging: {self.packaging}")
        if self.attribute_1_label and self.attribute_1_value:
            attributes.append(f"{self.attribute_1_label}: {self.attribute_1_value}")
        if self.attribute_2_label and self.attribute_2_value:
            attributes.append(f"{self.attribute_2_label}: {self.attribute_2_value}")

        return " | ".join(attributes) if attributes else ""


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_product_variants(sku_product, include_inactive=False):
    """
    Get all variants for a SKU Product.

    Args:
        sku_product: The parent SKU Product name
        include_inactive: Include inactive variants

    Returns:
        list: List of variant data
    """
    filters = {"sku_product": sku_product}

    if not include_inactive:
        filters["status"] = ("in", ["Active"])

    variants = frappe.get_all(
        "Product Variant",
        filters=filters,
        fields=[
            "name", "variant_code", "variant_name", "status", "is_default",
            "color", "size", "material", "packaging",
            "variant_price", "currency", "variant_stock"
        ],
        order_by="is_default desc, variant_name asc"
    )

    return variants


@frappe.whitelist()
def get_variant_by_code(variant_code):
    """
    Get variant by variant code.

    Args:
        variant_code: The variant code to search for

    Returns:
        dict: Variant data or None
    """
    variant_name = frappe.db.get_value(
        "Product Variant",
        {"variant_code": variant_code.upper()},
        "name"
    )
    if variant_name:
        return frappe.get_doc("Product Variant", variant_name).as_dict()
    return None


@frappe.whitelist()
def get_default_variant(sku_product):
    """
    Get the default variant for a SKU Product.

    Args:
        sku_product: The parent SKU Product name

    Returns:
        dict: Default variant data or first active variant
    """
    # Try to get explicit default
    variant_name = frappe.db.get_value(
        "Product Variant",
        {"sku_product": sku_product, "is_default": 1, "status": "Active"},
        "name"
    )

    # Fall back to first active variant
    if not variant_name:
        variant_name = frappe.db.get_value(
            "Product Variant",
            {"sku_product": sku_product, "status": "Active"},
            "name"
        )

    if variant_name:
        return frappe.get_doc("Product Variant", variant_name).as_dict()
    return None


@frappe.whitelist()
def activate_variant(variant_name):
    """
    Activate a variant.

    Args:
        variant_name: Name of the variant to activate

    Returns:
        dict: Result with success status
    """
    variant = frappe.get_doc("Product Variant", variant_name)
    if variant.activate():
        return {"success": True, "message": _("Variant activated successfully")}
    return {"success": False, "message": _("Failed to activate variant")}


@frappe.whitelist()
def deactivate_variant(variant_name):
    """
    Deactivate a variant.

    Args:
        variant_name: Name of the variant to deactivate

    Returns:
        dict: Result with success status
    """
    variant = frappe.get_doc("Product Variant", variant_name)
    if variant.deactivate():
        return {"success": True, "message": _("Variant deactivated successfully")}
    return {"success": False, "message": _("Failed to deactivate variant")}


@frappe.whitelist()
def discontinue_variant(variant_name):
    """
    Discontinue a variant.

    Args:
        variant_name: Name of the variant to discontinue

    Returns:
        dict: Result with success status
    """
    variant = frappe.get_doc("Product Variant", variant_name)
    if variant.discontinue():
        return {"success": True, "message": _("Variant discontinued successfully")}
    return {"success": False, "message": _("Failed to discontinue variant")}


@frappe.whitelist()
def set_default_variant(variant_name):
    """
    Set a variant as the default for its parent product.

    Args:
        variant_name: Name of the variant to set as default

    Returns:
        dict: Result with success status
    """
    variant = frappe.get_doc("Product Variant", variant_name)
    variant.is_default = 1
    variant.save()
    return {"success": True, "message": _("Variant set as default successfully")}


@frappe.whitelist()
def check_variant_stock(variant_name, quantity):
    """
    Check if requested quantity is available for a variant.

    Args:
        variant_name: Name of the variant
        quantity: Requested quantity

    Returns:
        dict: Availability status
    """
    variant = frappe.get_doc("Product Variant", variant_name)
    available = variant.get_available_quantity()
    requested = flt(quantity)

    return {
        "available": available >= requested,
        "available_quantity": available,
        "requested_quantity": requested,
        "is_stock_item": variant.is_stock_item
    }


@frappe.whitelist()
def get_variant_matrix(sku_product):
    """
    Get variant matrix for a SKU Product showing all attribute combinations.

    Args:
        sku_product: The parent SKU Product name

    Returns:
        dict: Matrix data with attributes and variants
    """
    variants = frappe.get_all(
        "Product Variant",
        filters={"sku_product": sku_product, "status": "Active"},
        fields=[
            "name", "variant_code", "color", "size", "material", "packaging",
            "variant_price", "variant_stock", "is_default"
        ]
    )

    # Extract unique attribute values
    colors = list(set(v["color"] for v in variants if v["color"]))
    sizes = list(set(v["size"] for v in variants if v["size"]))
    materials = list(set(v["material"] for v in variants if v["material"]))
    packagings = list(set(v["packaging"] for v in variants if v["packaging"]))

    # Build lookup map
    variant_map = {}
    for v in variants:
        key = f"{v['color'] or ''}-{v['size'] or ''}-{v['material'] or ''}-{v['packaging'] or ''}"
        variant_map[key] = v

    return {
        "attributes": {
            "colors": sorted(colors),
            "sizes": sorted(sizes),
            "materials": sorted(materials),
            "packagings": sorted(packagings)
        },
        "variants": variants,
        "variant_map": variant_map
    }
