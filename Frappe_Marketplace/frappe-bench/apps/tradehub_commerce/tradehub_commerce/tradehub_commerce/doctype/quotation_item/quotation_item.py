# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Quotation Item child table for Trade Hub B2B Marketplace.

This module implements line items for seller quotations, capturing
pricing, quantities, and specifications for each item quoted.

Key features:
- Links to SKU Product with fetch_from for product details
- Links to Product Variant with fetch_from for variant details
- Quantity and pricing with calculated amount
- Technical specifications and notes
- Lead time and stock availability information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class QuotationItem(Document):
    """
    Quotation Item child table for quotation line items.

    Each item represents a specific product/service being quoted
    with its quantity, price, and specifications.
    """

    def validate(self):
        """Validate quotation item data."""
        self.validate_quantity()
        self.validate_pricing()
        self.validate_variant_product_match()
        self.calculate_amount()

    def validate_quantity(self):
        """Validate quantity is greater than 0."""
        if not self.quantity or flt(self.quantity) <= 0:
            frappe.throw(
                _("Row {0}: Quantity must be greater than 0").format(self.idx)
            )

        # Check against MOQ if specified
        if self.moq and flt(self.quantity) < flt(self.moq):
            frappe.throw(
                _("Row {0}: Quantity ({1}) is below Minimum Order Quantity ({2})").format(
                    self.idx, self.quantity, self.moq
                )
            )

        # Check against max quantity if specified
        if self.max_quantity and flt(self.quantity) > flt(self.max_quantity):
            frappe.throw(
                _("Row {0}: Quantity ({1}) exceeds Maximum Quantity ({2})").format(
                    self.idx, self.quantity, self.max_quantity
                )
            )

    def validate_pricing(self):
        """Validate unit price is not negative."""
        if flt(self.unit_price) < 0:
            frappe.throw(
                _("Row {0}: Unit Price cannot be negative").format(self.idx)
            )

    def validate_variant_product_match(self):
        """Validate variant belongs to the selected product."""
        if self.variant and self.sku_product:
            variant_product = frappe.db.get_value(
                "Product Variant", self.variant, "sku_product"
            )
            if variant_product and variant_product != self.sku_product:
                frappe.throw(
                    _("Row {0}: Variant {1} does not belong to product {2}").format(
                        self.idx, self.variant, self.sku_product
                    )
                )

    def calculate_amount(self):
        """Calculate line item amount."""
        self.amount = flt(self.quantity) * flt(self.unit_price)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def fetch_product_details(product_name):
    """
    Fetch product details for manual fetch in child table.

    Args:
        product_name: The SKU Product document name

    Returns:
        dict: Product details for populating fields
    """
    if not product_name:
        return {}

    product = frappe.db.get_value(
        "SKU Product",
        product_name,
        ["product_name", "sku_code", "base_price", "currency", "stock_uom", "stock_quantity"],
        as_dict=True
    )

    if not product:
        return {}

    return {
        "product_name": product.product_name,
        "product_sku_code": product.sku_code,
        "unit_price": product.base_price,
        "currency": product.currency,
        "uom": product.stock_uom,
        "available_stock": product.stock_quantity
    }


@frappe.whitelist()
def fetch_variant_details(variant_name):
    """
    Fetch variant details for manual fetch in child table.

    Args:
        variant_name: The Product Variant document name

    Returns:
        dict: Variant details for populating fields
    """
    if not variant_name:
        return {}

    variant = frappe.db.get_value(
        "Product Variant",
        variant_name,
        ["variant_name", "variant_code", "variant_price", "variant_stock"],
        as_dict=True
    )

    if not variant:
        return {}

    return {
        "variant_name": variant.variant_name,
        "variant_code": variant.variant_code,
        "unit_price": variant.variant_price,
        "available_stock": variant.variant_stock
    }


@frappe.whitelist()
def get_available_variants(product_name):
    """
    Get available variants for a product.

    Args:
        product_name: The SKU Product document name

    Returns:
        list: List of available variants
    """
    if not product_name:
        return []

    return frappe.get_all(
        "Product Variant",
        filters={
            "sku_product": product_name,
            "status": "Active"
        },
        fields=[
            "name", "variant_name", "variant_code",
            "variant_price", "variant_stock"
        ],
        order_by="variant_name asc"
    )


@frappe.whitelist()
def calculate_item_amount(quantity, unit_price):
    """
    Calculate item amount.

    Args:
        quantity: Item quantity
        unit_price: Price per unit

    Returns:
        float: Calculated amount
    """
    return flt(quantity) * flt(unit_price)


@frappe.whitelist()
def validate_quotation_items(items):
    """
    Validate a list of quotation items.

    Args:
        items: List of item dictionaries

    Returns:
        dict: Validation result with any errors
    """
    import json
    if isinstance(items, str):
        items = json.loads(items)

    errors = []
    total = 0

    for idx, item in enumerate(items, 1):
        # Check required fields
        if not item.get("item_description"):
            errors.append(f"Row {idx}: Description is required")

        if not item.get("quantity") or flt(item.get("quantity")) <= 0:
            errors.append(f"Row {idx}: Quantity must be greater than 0")

        if not item.get("unit_price") or flt(item.get("unit_price")) < 0:
            errors.append(f"Row {idx}: Unit Price cannot be negative")

        # Check MOQ
        if item.get("moq") and flt(item.get("quantity")) < flt(item.get("moq")):
            errors.append(
                f"Row {idx}: Quantity below Minimum Order Quantity ({item.get('moq')})"
            )

        # Calculate amount
        amount = flt(item.get("quantity")) * flt(item.get("unit_price"))
        total += amount

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "calculated_total": total,
        "item_count": len(items)
    }


def get_fetch_from_config():
    """
    Get fetch_from configuration for this DocType.

    This is used by fetch_from_helper utility for manual fetch in child tables.

    Returns:
        dict: Field mapping for fetch_from
    """
    return {
        "sku_product": {
            "source_doctype": "SKU Product",
            "field_map": {
                "product_name": "product_name",
                "product_sku_code": "sku_code"
            }
        },
        "variant": {
            "source_doctype": "Product Variant",
            "field_map": {
                "variant_name": "variant_name",
                "variant_code": "variant_code"
            }
        }
    }
