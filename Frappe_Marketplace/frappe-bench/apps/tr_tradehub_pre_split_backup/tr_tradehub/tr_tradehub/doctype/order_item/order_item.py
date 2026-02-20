# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class OrderItem(Document):
    """
    Order Item child table for products in an Order.

    This child table stores the individual items/products within an order.
    Each item links to an SKU Product and optionally to a specific Product Variant.

    Key features:
    - Product/SKU reference with fetch_from fields
    - Optional variant specification
    - Quantity and pricing with discount/tax calculations
    - Amount auto-calculation
    - Delivery/stock information per item
    - Technical specifications per item

    fetch_from fields (auto-populated from linked documents):
    - product_name, product_sku_code (from SKU Product)
    - variant_name, variant_code (from Product Variant)
    - seller, seller_name (from SKU Product)
    - tenant, tenant_name (from SKU Product)

    Note: fetch_from does NOT work automatically in child tables when
    using frappe.model.set_value(). Use manual_fetch_for_child() from
    trade_hub.utils.fetch_from_helper for JavaScript-triggered updates.
    """

    def validate(self):
        """Validate the Order Item"""
        self.validate_quantity()
        self.validate_unit_price()
        self.validate_variant_product_match()
        self.calculate_amounts()

    def validate_quantity(self):
        """Ensure quantity is positive"""
        if self.quantity is None or self.quantity <= 0:
            frappe.throw(
                frappe._("Quantity must be greater than 0 for item: {0}").format(
                    self.product_name or self.sku_product or "Unknown"
                )
            )

    def validate_unit_price(self):
        """Ensure unit price is non-negative"""
        if self.unit_price is not None and self.unit_price < 0:
            frappe.throw(
                frappe._("Unit Price cannot be negative for item: {0}").format(
                    self.product_name or self.sku_product or "Unknown"
                )
            )

    def validate_variant_product_match(self):
        """Ensure variant belongs to the selected product"""
        if self.variant and self.sku_product:
            variant_product = frappe.db.get_value(
                "Product Variant",
                self.variant,
                "sku_product"
            )
            if variant_product and variant_product != self.sku_product:
                frappe.throw(
                    frappe._("Variant {0} does not belong to Product {1}").format(
                        self.variant, self.sku_product
                    )
                )

    def calculate_amounts(self):
        """Calculate discount_amount, tax_amount, and total amount"""
        quantity = flt(self.quantity) or 0
        unit_price = flt(self.unit_price) or 0
        discount_percentage = flt(self.discount_percentage) or 0
        tax_rate = flt(self.tax_rate) or 0

        # Calculate subtotal before discount
        subtotal = quantity * unit_price

        # Calculate discount amount
        self.discount_amount = flt(subtotal * (discount_percentage / 100), 2)

        # Calculate amount after discount
        amount_after_discount = subtotal - flt(self.discount_amount)

        # Calculate tax amount
        self.tax_amount = flt(amount_after_discount * (tax_rate / 100), 2)

        # Calculate final amount
        self.amount = flt(amount_after_discount + flt(self.tax_amount), 2)


def get_fetch_from_config():
    """
    Return the fetch_from configuration for Order Item.

    This configuration is used by the fetch_from_helper utility
    to perform manual fetching in child tables.

    Returns:
        dict: Mapping of field names to their fetch_from sources
    """
    return {
        "product_name": "sku_product.product_name",
        "product_sku_code": "sku_product.sku_code",
        "seller": "sku_product.seller",
        "seller_name": "sku_product.seller_name",
        "tenant": "sku_product.tenant",
        "tenant_name": "sku_product.tenant_name",
        "variant_name": "variant.variant_name",
        "variant_code": "variant.variant_code"
    }


@frappe.whitelist()
def fetch_product_details(product_name):
    """
    Fetch product details for manual population in child table.

    This function is called from JavaScript when the sku_product field
    changes in the child table, since fetch_from doesn't work automatically.

    Args:
        product_name: The name (ID) of the SKU Product document

    Returns:
        dict: Product details including name, SKU code, seller info, tenant info,
              base price, UOM, weight, and available stock
    """
    if not product_name:
        return {}

    product = frappe.db.get_value(
        "SKU Product",
        product_name,
        [
            "product_name", "sku_code", "seller", "seller_name",
            "tenant", "tenant_name", "stock_uom", "base_price",
            "currency", "weight", "weight_uom", "stock_quantity"
        ],
        as_dict=True
    )

    if not product:
        return {}

    return {
        "product_name": product.get("product_name"),
        "product_sku_code": product.get("sku_code"),
        "seller": product.get("seller"),
        "seller_name": product.get("seller_name"),
        "tenant": product.get("tenant"),
        "tenant_name": product.get("tenant_name"),
        "uom": product.get("stock_uom"),
        "unit_price": product.get("base_price"),
        "currency": product.get("currency"),
        "weight": product.get("weight"),
        "weight_uom": product.get("weight_uom"),
        "available_stock": product.get("stock_quantity")
    }


@frappe.whitelist()
def fetch_variant_details(variant_name):
    """
    Fetch variant details for manual population in child table.

    This function is called from JavaScript when the variant field
    changes in the child table, since fetch_from doesn't work automatically.

    Args:
        variant_name: The name (ID) of the Product Variant document

    Returns:
        dict: Variant details including name, code, price adjustment,
              and parent product reference
    """
    if not variant_name:
        return {}

    variant = frappe.db.get_value(
        "Product Variant",
        variant_name,
        [
            "variant_name", "variant_code", "sku_product",
            "variant_price", "price_adjustment", "variant_stock",
            "weight"
        ],
        as_dict=True
    )

    if not variant:
        return {}

    result = {
        "variant_name": variant.get("variant_name"),
        "variant_code": variant.get("variant_code"),
        "sku_product": variant.get("sku_product"),
        "available_stock": variant.get("variant_stock")
    }

    # If variant has a specific price, include it
    if variant.get("variant_price"):
        result["unit_price"] = variant.get("variant_price")

    # If variant has weight, include it
    if variant.get("weight"):
        result["weight"] = variant.get("weight")

    return result


@frappe.whitelist()
def get_available_variants(product_name):
    """
    Get list of available variants for a product.

    This function returns all active variants for a given SKU Product,
    useful for filtering the variant dropdown in the Order Item.

    Args:
        product_name: The name (ID) of the SKU Product document

    Returns:
        list: List of variant dictionaries with name, variant_name,
              variant_code, and attributes
    """
    if not product_name:
        return []

    variants = frappe.get_all(
        "Product Variant",
        filters={
            "sku_product": product_name,
            "status": "Active"
        },
        fields=[
            "name", "variant_name", "variant_code",
            "color", "size", "material", "packaging",
            "variant_price", "variant_stock"
        ],
        order_by="variant_name"
    )

    return variants


@frappe.whitelist()
def calculate_item_amount(quantity, unit_price, discount_percentage=0, tax_rate=0):
    """
    Calculate item amounts based on quantity, price, discount, and tax.

    This utility function can be called from JavaScript to perform
    real-time amount calculations without server-side validation.

    Args:
        quantity: Item quantity
        unit_price: Price per unit
        discount_percentage: Discount percentage (0-100)
        tax_rate: Tax rate percentage (0-100)

    Returns:
        dict: Calculated amounts including discount_amount, tax_amount, and total amount
    """
    quantity = flt(quantity) or 0
    unit_price = flt(unit_price) or 0
    discount_percentage = flt(discount_percentage) or 0
    tax_rate = flt(tax_rate) or 0

    # Calculate subtotal before discount
    subtotal = quantity * unit_price

    # Calculate discount amount
    discount_amount = flt(subtotal * (discount_percentage / 100), 2)

    # Calculate amount after discount
    amount_after_discount = subtotal - discount_amount

    # Calculate tax amount
    tax_amount = flt(amount_after_discount * (tax_rate / 100), 2)

    # Calculate final amount
    amount = flt(amount_after_discount + tax_amount, 2)

    return {
        "subtotal": flt(subtotal, 2),
        "discount_amount": discount_amount,
        "amount_after_discount": flt(amount_after_discount, 2),
        "tax_amount": tax_amount,
        "amount": amount
    }


@frappe.whitelist()
def validate_order_items(items):
    """
    Validate a list of Order items before submission.

    This function can be called from the Order form to validate
    all items before confirming the order.

    Args:
        items: JSON string or list of item dictionaries

    Returns:
        dict: Validation result with success status, errors, and calculated totals
    """
    import json

    if isinstance(items, str):
        items = json.loads(items)

    errors = []
    total_quantity = 0
    total_amount = 0

    for idx, item in enumerate(items, start=1):
        # Check required fields
        if not item.get("sku_product"):
            errors.append(
                frappe._("Row {0}: Product is required").format(idx)
            )

        # Check quantity
        quantity = item.get("quantity")
        if quantity is None or flt(quantity) <= 0:
            errors.append(
                frappe._("Row {0}: Quantity must be greater than 0").format(idx)
            )
        else:
            total_quantity += flt(quantity)

        # Check unit price
        unit_price = item.get("unit_price")
        if unit_price is None or flt(unit_price) < 0:
            errors.append(
                frappe._("Row {0}: Unit Price cannot be negative").format(idx)
            )

        # Check variant-product match
        if item.get("variant") and item.get("sku_product"):
            variant_product = frappe.db.get_value(
                "Product Variant",
                item.get("variant"),
                "sku_product"
            )
            if variant_product and variant_product != item.get("sku_product"):
                errors.append(
                    frappe._("Row {0}: Variant does not belong to selected Product").format(idx)
                )

        # Calculate item amount for total
        if not errors:
            amount = flt(item.get("amount") or 0)
            if amount == 0 and flt(quantity) > 0 and flt(unit_price) > 0:
                # Recalculate if not provided
                result = calculate_item_amount(
                    quantity,
                    unit_price,
                    item.get("discount_percentage", 0),
                    item.get("tax_rate", 0)
                )
                amount = result.get("amount", 0)
            total_amount += amount

    return {
        "success": len(errors) == 0,
        "errors": errors,
        "total_quantity": flt(total_quantity, 2),
        "total_amount": flt(total_amount, 2),
        "item_count": len(items)
    }


@frappe.whitelist()
def check_stock_availability(product_name, variant_name=None, quantity=1):
    """
    Check stock availability for a product/variant.

    This function checks if the requested quantity is available
    for the specified product or variant.

    Args:
        product_name: The name (ID) of the SKU Product document
        variant_name: The name (ID) of the Product Variant (optional)
        quantity: Requested quantity

    Returns:
        dict: Stock availability status including available quantity,
              is_available flag, and shortage amount if any
    """
    quantity = flt(quantity) or 1

    if variant_name:
        # Check variant stock
        stock = frappe.db.get_value(
            "Product Variant",
            variant_name,
            ["variant_stock", "allow_negative_stock"],
            as_dict=True
        )
        available_stock = flt(stock.get("variant_stock") if stock else 0)
        allow_negative = stock.get("allow_negative_stock") if stock else False
    else:
        # Check product stock
        stock = frappe.db.get_value(
            "SKU Product",
            product_name,
            ["stock_quantity", "allow_negative_stock"],
            as_dict=True
        )
        available_stock = flt(stock.get("stock_quantity") if stock else 0)
        allow_negative = stock.get("allow_negative_stock") if stock else False

    is_available = allow_negative or available_stock >= quantity
    shortage = max(0, quantity - available_stock) if not allow_negative else 0

    return {
        "available_stock": available_stock,
        "requested_quantity": quantity,
        "is_available": is_available,
        "allow_negative_stock": allow_negative,
        "shortage": shortage,
        "message": (
            frappe._("Stock available")
            if is_available
            else frappe._("Insufficient stock: {0} units short").format(shortage)
        )
    }


@frappe.whitelist()
def get_product_pricing(product_name, quantity=1, incoterm=None):
    """
    Get pricing for a product based on quantity and incoterm.

    This function retrieves applicable pricing from Incoterm Price
    records if available, falling back to base price otherwise.

    Args:
        product_name: The name (ID) of the SKU Product document
        quantity: Order quantity for tier pricing
        incoterm: Incoterm (EXW, FOB, CIF, DDP) - optional

    Returns:
        dict: Pricing information including unit_price, currency,
              and any applicable price breaks
    """
    quantity = flt(quantity) or 1

    # Get base product price
    product = frappe.db.get_value(
        "SKU Product",
        product_name,
        ["base_price", "currency", "min_order_quantity", "max_order_quantity"],
        as_dict=True
    )

    if not product:
        return {"error": frappe._("Product not found")}

    result = {
        "base_price": flt(product.get("base_price")),
        "currency": product.get("currency") or "USD",
        "min_order_quantity": flt(product.get("min_order_quantity")),
        "max_order_quantity": flt(product.get("max_order_quantity")),
        "unit_price": flt(product.get("base_price")),
        "price_source": "Base Price"
    }

    # Check for incoterm pricing if specified
    if incoterm:
        incoterm_price = frappe.db.get_value(
            "Incoterm Price",
            {
                "sku_product": product_name,
                "incoterm": incoterm,
                "status": "Active"
            },
            ["name", "base_price", "currency"],
            as_dict=True
        )

        if incoterm_price:
            result["unit_price"] = flt(incoterm_price.get("base_price"))
            result["currency"] = incoterm_price.get("currency") or result["currency"]
            result["price_source"] = f"Incoterm ({incoterm})"
            result["incoterm_price_doc"] = incoterm_price.get("name")

            # Check for quantity-based price breaks
            price_breaks = frappe.get_all(
                "Price Break",
                filters={
                    "parent": incoterm_price.get("name"),
                    "parenttype": "Incoterm Price"
                },
                fields=["min_qty", "max_qty", "unit_price", "discount_percent"],
                order_by="min_qty"
            )

            if price_breaks:
                result["price_breaks"] = price_breaks

                # Find applicable price break for quantity
                for pb in price_breaks:
                    min_qty = flt(pb.get("min_qty"))
                    max_qty = flt(pb.get("max_qty"))
                    if min_qty <= quantity and (max_qty == 0 or quantity <= max_qty):
                        result["unit_price"] = flt(pb.get("unit_price"))
                        result["discount_percent"] = flt(pb.get("discount_percent"))
                        result["price_source"] = f"Incoterm ({incoterm}) - Qty Break"
                        break

    return result
