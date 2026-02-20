# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tax Calculator Utility for TR-TradeHub Marketplace

This module provides comprehensive tax calculation functionality for the
Turkish marketplace, handling:
- Turkish KDV (VAT) at multiple rates (18%, 8%, 1%, 0%)
- Price-inclusive and price-exclusive tax calculations
- Category-based tax rate lookup
- B2B tax exemption handling
- Tax breakdown for invoicing
- Compound tax calculations
- Shipping tax handling

Turkish Tax System Overview:
- Standard KDV Rate: 18% (Most goods and services)
- Reduced KDV Rate: 8% (Food, textiles, medical supplies, hotels)
- Minimum KDV Rate: 1% (Newspapers, periodicals, basic food)
- Exempt: 0% (Exports, certain financial services)
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, nowdate
from typing import Dict, List, Optional, Union, Tuple
from decimal import Decimal, ROUND_HALF_UP


# =================================================================
# Constants
# =================================================================

# Turkish KDV Rates
TURKISH_VAT_RATES = {
    "standard": 18.0,
    "reduced": 8.0,
    "minimum": 1.0,
    "exempt": 0.0
}

# Default tax rate (Turkish standard KDV)
DEFAULT_TAX_RATE = 18.0

# Rounding precision for tax calculations
TAX_PRECISION = 2


# =================================================================
# Core Tax Calculation Functions
# =================================================================

def calculate_tax(
    amount: float,
    tax_rate: float = None,
    price_includes_tax: bool = False,
    precision: int = TAX_PRECISION
) -> Dict[str, float]:
    """
    Calculate tax amount from a given amount.

    Args:
        amount: Base amount or tax-inclusive amount
        tax_rate: Tax rate percentage (defaults to standard Turkish KDV)
        price_includes_tax: If True, amount already includes tax
        precision: Decimal precision for rounding

    Returns:
        dict: {
            'base_amount': Amount before tax,
            'tax_amount': Tax amount,
            'total_amount': Amount including tax,
            'tax_rate': Applied tax rate
        }
    """
    if tax_rate is None:
        tax_rate = get_default_tax_rate()

    tax_rate = flt(tax_rate)
    amount = flt(amount)

    if price_includes_tax:
        # Extract tax from inclusive price
        # Formula: base = total / (1 + rate/100)
        if tax_rate > 0:
            tax_divisor = Decimal("1") + Decimal(str(tax_rate)) / Decimal("100")
            base_amount = Decimal(str(amount)) / tax_divisor
            tax_amount = Decimal(str(amount)) - base_amount
        else:
            base_amount = Decimal(str(amount))
            tax_amount = Decimal("0")
    else:
        # Calculate tax on base amount
        base_amount = Decimal(str(amount))
        tax_amount = base_amount * Decimal(str(tax_rate)) / Decimal("100")

    # Round values
    base_amount = float(base_amount.quantize(Decimal(f"0.{'0' * precision}"), rounding=ROUND_HALF_UP))
    tax_amount = float(tax_amount.quantize(Decimal(f"0.{'0' * precision}"), rounding=ROUND_HALF_UP))
    total_amount = base_amount + tax_amount

    return {
        "base_amount": base_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "tax_rate": tax_rate
    }


def calculate_tax_for_items(
    items: List[Dict],
    price_includes_tax: bool = False,
    apply_tax_to_shipping: bool = True,
    shipping_amount: float = 0,
    discount_amount: float = 0,
    precision: int = TAX_PRECISION
) -> Dict:
    """
    Calculate tax for multiple items with optional shipping and discounts.

    Args:
        items: List of item dicts with keys:
            - amount/line_total: Item total
            - tax_rate: Item tax rate (optional)
            - qty: Quantity (optional, defaults to 1)
        price_includes_tax: If True, item prices already include tax
        apply_tax_to_shipping: Apply tax to shipping amount
        shipping_amount: Shipping amount
        discount_amount: Discount amount (applied before tax)
        precision: Decimal precision

    Returns:
        dict: {
            'items': List of items with tax breakdown,
            'subtotal': Subtotal before tax,
            'tax_amount': Total tax,
            'shipping_amount': Shipping amount,
            'shipping_tax': Tax on shipping,
            'discount_amount': Discount applied,
            'grand_total': Final total including tax
        }
    """
    result = {
        "items": [],
        "subtotal": 0,
        "tax_amount": 0,
        "shipping_amount": flt(shipping_amount),
        "shipping_tax": 0,
        "discount_amount": flt(discount_amount),
        "grand_total": 0,
        "tax_breakdown": {}
    }

    # Process each item
    for item in items:
        item_amount = flt(item.get("amount") or item.get("line_total", 0))
        item_tax_rate = flt(item.get("tax_rate")) if item.get("tax_rate") is not None else get_default_tax_rate()
        qty = flt(item.get("qty", 1)) or 1

        # Calculate tax for this item
        tax_calc = calculate_tax(
            amount=item_amount,
            tax_rate=item_tax_rate,
            price_includes_tax=price_includes_tax,
            precision=precision
        )

        item_result = {
            **item,
            "base_amount": tax_calc["base_amount"],
            "tax_amount": tax_calc["tax_amount"],
            "tax_rate": tax_calc["tax_rate"],
            "total_amount": tax_calc["total_amount"]
        }

        result["items"].append(item_result)
        result["subtotal"] += tax_calc["base_amount"]
        result["tax_amount"] += tax_calc["tax_amount"]

        # Build tax breakdown by rate
        rate_key = f"{tax_calc['tax_rate']}%"
        if rate_key not in result["tax_breakdown"]:
            result["tax_breakdown"][rate_key] = {
                "rate": tax_calc["tax_rate"],
                "taxable_amount": 0,
                "tax_amount": 0
            }
        result["tax_breakdown"][rate_key]["taxable_amount"] += tax_calc["base_amount"]
        result["tax_breakdown"][rate_key]["tax_amount"] += tax_calc["tax_amount"]

    # Apply discount
    if result["discount_amount"] > 0:
        # Proportionally reduce tax if discount applied
        if result["subtotal"] > 0:
            discount_ratio = result["discount_amount"] / result["subtotal"]
            result["tax_amount"] -= result["tax_amount"] * discount_ratio
            result["subtotal"] -= result["discount_amount"]

    # Calculate shipping tax
    if apply_tax_to_shipping and shipping_amount > 0:
        shipping_tax_rate = get_shipping_tax_rate()
        shipping_tax_calc = calculate_tax(
            amount=shipping_amount,
            tax_rate=shipping_tax_rate,
            price_includes_tax=False,
            precision=precision
        )
        result["shipping_tax"] = shipping_tax_calc["tax_amount"]
        result["tax_amount"] += result["shipping_tax"]

        # Add shipping tax to breakdown
        rate_key = f"{shipping_tax_rate}%"
        if rate_key not in result["tax_breakdown"]:
            result["tax_breakdown"][rate_key] = {
                "rate": shipping_tax_rate,
                "taxable_amount": 0,
                "tax_amount": 0
            }
        result["tax_breakdown"][rate_key]["taxable_amount"] += shipping_amount
        result["tax_breakdown"][rate_key]["tax_amount"] += result["shipping_tax"]

    # Calculate grand total
    result["grand_total"] = (
        result["subtotal"]
        + result["tax_amount"]
        + result["shipping_amount"]
    )

    # Round final values
    result["subtotal"] = round(result["subtotal"], precision)
    result["tax_amount"] = round(result["tax_amount"], precision)
    result["shipping_tax"] = round(result["shipping_tax"], precision)
    result["grand_total"] = round(result["grand_total"], precision)

    return result


# =================================================================
# Tax Rate Lookup Functions
# =================================================================

def get_default_tax_rate() -> float:
    """
    Get the default tax rate from system settings.

    Returns:
        float: Default tax rate percentage
    """
    try:
        # First try to get from Tax Rate DocType
        default_rate = frappe.db.get_value(
            "Tax Rate",
            {"is_default": 1, "is_active": 1},
            "rate"
        )
        if default_rate is not None:
            return flt(default_rate)
    except Exception:
        pass

    return DEFAULT_TAX_RATE


def get_tax_rate_for_listing(listing: str) -> float:
    """
    Get tax rate for a specific listing.

    Args:
        listing: Listing name/ID

    Returns:
        float: Tax rate percentage
    """
    if not listing:
        return get_default_tax_rate()

    # First check listing's own tax rate
    listing_data = frappe.db.get_value(
        "Listing",
        listing,
        ["tax_rate", "category"],
        as_dict=True
    )

    if not listing_data:
        return get_default_tax_rate()

    if listing_data.tax_rate:
        return flt(listing_data.tax_rate)

    # Fall back to category tax rate
    if listing_data.category:
        return get_tax_rate_for_category(listing_data.category)

    return get_default_tax_rate()


def get_tax_rate_for_category(category: str, check_date: str = None) -> float:
    """
    Get tax rate for a specific category.

    Args:
        category: Category name
        check_date: Date to check (for date-effective rates)

    Returns:
        float: Tax rate percentage
    """
    if not category:
        return get_default_tax_rate()

    # Check if category has a direct tax rate link
    try:
        category_tax_rate = frappe.db.get_value("Category", category, "tax_rate")
        if category_tax_rate:
            tax_rate = frappe.db.get_value("Tax Rate", category_tax_rate, "rate")
            if tax_rate is not None:
                return flt(tax_rate)
    except Exception:
        pass

    # Check parent category
    try:
        parent_category = frappe.db.get_value("Category", category, "parent_category")
        if parent_category:
            return get_tax_rate_for_category(parent_category, check_date)
    except Exception:
        pass

    return get_default_tax_rate()


def get_shipping_tax_rate() -> float:
    """
    Get tax rate applicable to shipping charges.

    Returns:
        float: Shipping tax rate percentage
    """
    try:
        # Get tax rate marked for shipping
        shipping_rate = frappe.db.get_value(
            "Tax Rate",
            {"is_active": 1, "apply_to_shipping": 1},
            "rate"
        )
        if shipping_rate is not None:
            return flt(shipping_rate)
    except Exception:
        pass

    return get_default_tax_rate()


# =================================================================
# B2B Tax Handling
# =================================================================

def is_b2b_tax_exempt(buyer: str = None, organization: str = None) -> bool:
    """
    Check if buyer/organization qualifies for B2B tax exemption.

    In Turkey, B2B transactions between VAT-registered entities
    may have different tax treatment (reverse charge mechanism).

    Args:
        buyer: Buyer user/profile
        organization: Organization name

    Returns:
        bool: True if tax exempt
    """
    if organization:
        try:
            org_data = frappe.db.get_value(
                "Organization",
                organization,
                ["is_tax_exempt", "tax_id"],
                as_dict=True
            )
            if org_data and org_data.is_tax_exempt:
                # Verify they have a valid tax ID
                return bool(org_data.tax_id)
        except Exception:
            pass

    return False


def calculate_b2b_tax(
    amount: float,
    tax_rate: float = None,
    buyer: str = None,
    organization: str = None,
    reverse_charge: bool = False
) -> Dict[str, float]:
    """
    Calculate tax for B2B transactions.

    Args:
        amount: Base amount
        tax_rate: Tax rate percentage
        buyer: Buyer profile
        organization: Buyer organization
        reverse_charge: Apply reverse charge mechanism

    Returns:
        dict: Tax calculation result with B2B adjustments
    """
    if tax_rate is None:
        tax_rate = get_default_tax_rate()

    # Check for tax exemption
    if is_b2b_tax_exempt(buyer, organization):
        return {
            "base_amount": flt(amount),
            "tax_amount": 0,
            "total_amount": flt(amount),
            "tax_rate": 0,
            "is_tax_exempt": True,
            "exemption_reason": "B2B Tax Exempt Organization"
        }

    # Reverse charge mechanism (tax liability shifts to buyer)
    if reverse_charge:
        return {
            "base_amount": flt(amount),
            "tax_amount": 0,
            "total_amount": flt(amount),
            "tax_rate": tax_rate,
            "is_reverse_charge": True,
            "reverse_charge_amount": flt(amount) * flt(tax_rate) / 100
        }

    # Standard B2B calculation
    return calculate_tax(amount, tax_rate, price_includes_tax=False)


# =================================================================
# Invoice Tax Breakdown
# =================================================================

def get_tax_breakdown_for_invoice(
    items: List[Dict],
    shipping_amount: float = 0,
    discount_amount: float = 0,
    price_includes_tax: bool = False
) -> Dict:
    """
    Generate detailed tax breakdown for invoice/e-fatura.

    Args:
        items: List of order items
        shipping_amount: Shipping charges
        discount_amount: Total discount
        price_includes_tax: If True, prices include tax

    Returns:
        dict: Detailed tax breakdown for invoicing
    """
    breakdown = {
        "lines": [],
        "tax_summary": {},
        "totals": {
            "subtotal_excl_tax": 0,
            "total_tax": 0,
            "shipping": flt(shipping_amount),
            "shipping_tax": 0,
            "discount": flt(discount_amount),
            "grand_total": 0
        },
        "e_invoice_data": {
            "tax_type_code": "0015",  # KDV code for Turkish e-invoice
            "currency": "TRY"
        }
    }

    # Process each item
    for idx, item in enumerate(items, 1):
        item_amount = flt(item.get("line_total", 0))
        tax_rate = flt(item.get("tax_rate")) if item.get("tax_rate") is not None else get_default_tax_rate()

        tax_calc = calculate_tax(
            amount=item_amount,
            tax_rate=tax_rate,
            price_includes_tax=price_includes_tax
        )

        line = {
            "line_number": idx,
            "description": item.get("title", item.get("listing", "")),
            "quantity": flt(item.get("qty", 1)),
            "unit_price": flt(item.get("unit_price", 0)),
            "base_amount": tax_calc["base_amount"],
            "tax_rate": tax_rate,
            "tax_amount": tax_calc["tax_amount"],
            "total_amount": tax_calc["total_amount"]
        }
        breakdown["lines"].append(line)

        # Update totals
        breakdown["totals"]["subtotal_excl_tax"] += tax_calc["base_amount"]
        breakdown["totals"]["total_tax"] += tax_calc["tax_amount"]

        # Tax summary by rate
        rate_key = f"{tax_rate}%"
        if rate_key not in breakdown["tax_summary"]:
            breakdown["tax_summary"][rate_key] = {
                "rate": tax_rate,
                "tax_code": f"KDV{int(tax_rate)}" if tax_rate in [18, 8, 1, 0] else f"VAT{int(tax_rate)}",
                "taxable_amount": 0,
                "tax_amount": 0
            }
        breakdown["tax_summary"][rate_key]["taxable_amount"] += tax_calc["base_amount"]
        breakdown["tax_summary"][rate_key]["tax_amount"] += tax_calc["tax_amount"]

    # Handle shipping tax
    if shipping_amount > 0:
        shipping_tax_rate = get_shipping_tax_rate()
        shipping_tax_calc = calculate_tax(shipping_amount, shipping_tax_rate)
        breakdown["totals"]["shipping_tax"] = shipping_tax_calc["tax_amount"]
        breakdown["totals"]["total_tax"] += shipping_tax_calc["tax_amount"]

    # Apply discount
    if discount_amount > 0:
        breakdown["totals"]["subtotal_excl_tax"] -= discount_amount
        # Proportionally reduce tax
        if breakdown["totals"]["subtotal_excl_tax"] + discount_amount > 0:
            discount_ratio = discount_amount / (breakdown["totals"]["subtotal_excl_tax"] + discount_amount)
            breakdown["totals"]["total_tax"] *= (1 - discount_ratio)

    # Calculate grand total
    breakdown["totals"]["grand_total"] = (
        breakdown["totals"]["subtotal_excl_tax"]
        + breakdown["totals"]["total_tax"]
        + breakdown["totals"]["shipping"]
    )

    # Round all values
    for key in breakdown["totals"]:
        breakdown["totals"][key] = round(breakdown["totals"][key], TAX_PRECISION)

    return breakdown


# =================================================================
# Price Display Helpers
# =================================================================

def get_price_display(
    price: float,
    tax_rate: float = None,
    show_tax_inclusive: bool = True,
    currency: str = "TRY"
) -> Dict[str, any]:
    """
    Get formatted price display data.

    Args:
        price: Product price
        tax_rate: Tax rate percentage
        show_tax_inclusive: Show tax-inclusive price
        currency: Currency code

    Returns:
        dict: Price display data
    """
    if tax_rate is None:
        tax_rate = get_default_tax_rate()

    tax_calc = calculate_tax(price, tax_rate, price_includes_tax=False)

    return {
        "price_excl_tax": tax_calc["base_amount"],
        "price_incl_tax": tax_calc["total_amount"],
        "tax_amount": tax_calc["tax_amount"],
        "tax_rate": tax_rate,
        "display_price": tax_calc["total_amount"] if show_tax_inclusive else tax_calc["base_amount"],
        "currency": currency,
        "tax_label": f"KDV %{int(tax_rate)}" if tax_rate in [18, 8, 1, 0] else f"VAT {tax_rate}%"
    }


def format_tax_amount(amount: float, currency: str = "TRY") -> str:
    """
    Format tax amount for display.

    Args:
        amount: Tax amount
        currency: Currency code

    Returns:
        str: Formatted tax amount string
    """
    if currency == "TRY":
        return f"₺{amount:,.2f}"
    elif currency == "USD":
        return f"${amount:,.2f}"
    elif currency == "EUR":
        return f"€{amount:,.2f}"
    else:
        return f"{currency} {amount:,.2f}"


# =================================================================
# Validation Functions
# =================================================================

def validate_tax_rate(tax_rate: float) -> bool:
    """
    Validate if tax rate is a valid Turkish KDV rate.

    Args:
        tax_rate: Tax rate to validate

    Returns:
        bool: True if valid
    """
    valid_rates = [0, 1, 8, 18]
    return flt(tax_rate) in valid_rates


def get_suggested_tax_rate(category: str = None, product_type: str = None) -> float:
    """
    Get suggested tax rate based on category/product type.

    Args:
        category: Product category
        product_type: Type of product

    Returns:
        float: Suggested tax rate
    """
    # Category-based suggestions
    reduced_rate_categories = [
        "Food", "Gıda", "Yiyecek",
        "Textile", "Tekstil",
        "Medical", "Tıbbi", "Sağlık",
        "Agriculture", "Tarım",
        "Education", "Eğitim"
    ]

    minimum_rate_categories = [
        "Newspaper", "Gazete",
        "Periodical", "Dergi",
        "Book", "Kitap"
    ]

    if category:
        category_lower = category.lower()
        for cat in minimum_rate_categories:
            if cat.lower() in category_lower:
                return 1.0

        for cat in reduced_rate_categories:
            if cat.lower() in category_lower:
                return 8.0

    return 18.0


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist(allow_guest=True)
def calculate_item_tax(amount, tax_rate=None, price_includes_tax=0):
    """
    API endpoint to calculate tax for a single item.

    Args:
        amount: Item amount
        tax_rate: Tax rate (optional)
        price_includes_tax: 1 if price includes tax, 0 otherwise

    Returns:
        dict: Tax calculation result
    """
    return calculate_tax(
        amount=flt(amount),
        tax_rate=flt(tax_rate) if tax_rate else None,
        price_includes_tax=cint(price_includes_tax)
    )


@frappe.whitelist(allow_guest=True)
def get_listing_tax_rate(listing):
    """
    API endpoint to get tax rate for a listing.

    Args:
        listing: Listing name

    Returns:
        dict: Tax rate info
    """
    rate = get_tax_rate_for_listing(listing)
    return {
        "tax_rate": rate,
        "tax_label": f"KDV %{int(rate)}" if rate in [18, 8, 1, 0] else f"VAT {rate}%"
    }


@frappe.whitelist(allow_guest=True)
def get_cart_tax_summary(cart_id):
    """
    API endpoint to get tax summary for a cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Cart tax summary
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    items = []
    for item in cart.items:
        items.append({
            "listing": item.listing,
            "title": item.title,
            "qty": item.qty,
            "line_total": item.line_total,
            "tax_rate": item.tax_rate
        })

    return calculate_tax_for_items(
        items=items,
        price_includes_tax=cart.price_includes_tax,
        shipping_amount=flt(cart.shipping_amount),
        discount_amount=flt(cart.discount_amount)
    )


@frappe.whitelist()
def get_invoice_tax_breakdown(order):
    """
    API endpoint to get tax breakdown for an order (for invoicing).

    Args:
        order: Marketplace Order name

    Returns:
        dict: Invoice tax breakdown
    """
    order_doc = frappe.get_doc("Marketplace Order", order)

    items = []
    for item in order_doc.items:
        items.append({
            "listing": item.listing,
            "title": item.title,
            "qty": item.qty,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "tax_rate": item.tax_rate
        })

    return get_tax_breakdown_for_invoice(
        items=items,
        shipping_amount=flt(order_doc.shipping_amount),
        discount_amount=flt(order_doc.discount_amount),
        price_includes_tax=order_doc.price_includes_tax if hasattr(order_doc, 'price_includes_tax') else False
    )
