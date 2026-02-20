# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Shipping Calculator Utility for TR-TradeHub Marketplace

This module provides centralized shipping cost calculation for the marketplace.
It integrates:
- Shipping Rules (zone-based, weight-based, tiered pricing)
- Carrier API rates (real-time rates from carriers)
- Free shipping logic
- Turkish domestic shipping optimizations

Key Features:
- Multiple shipping option calculation
- Carrier API integration for real-time rates
- Free shipping threshold calculation
- Express delivery options
- Seller-specific shipping rules
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, nowdate
from typing import Dict, List, Optional
import json


# =================================================================
# Main Shipping Calculator
# =================================================================

def calculate_shipping_options(
    order_amount: float,
    total_weight: float = 0,
    item_count: int = 1,
    destination_country: str = "Turkey",
    destination_city: str = None,
    postal_code: str = None,
    categories: List[str] = None,
    seller: str = None,
    tenant: str = None,
    include_express: bool = True,
    use_carrier_api: bool = True
) -> Dict:
    """
    Calculate all available shipping options for an order.

    Args:
        order_amount: Total order amount
        total_weight: Total weight in kg
        item_count: Number of items
        destination_country: Destination country (default: Turkey)
        destination_city: Destination city
        postal_code: Destination postal code
        categories: List of category names
        seller: Seller profile name (for seller-specific rules)
        tenant: Tenant name (for tenant-specific rules)
        include_express: Include express delivery options
        use_carrier_api: Query carrier APIs for real-time rates

    Returns:
        dict: Shipping options with rates and delivery estimates
    """
    order_data = {
        "order_amount": flt(order_amount),
        "total_weight": flt(total_weight),
        "item_count": cint(item_count),
        "destination": {
            "country": destination_country or "Turkey",
            "city": destination_city or "",
            "postal_code": postal_code or ""
        },
        "categories": categories or [],
        "express": False
    }

    options = []

    # 1. Get shipping rule based options
    rule_options = _get_shipping_rule_options(order_data, seller, tenant)
    options.extend(rule_options)

    # 2. Get carrier API rates if enabled
    if use_carrier_api:
        api_options = _get_carrier_api_rates(order_data, seller)
        options.extend(api_options)

    # 3. Add express options if requested
    if include_express:
        express_options = _get_express_options(order_data, seller, tenant)
        options.extend(express_options)

    # Remove duplicates and sort by price
    unique_options = _deduplicate_options(options)
    sorted_options = sorted(unique_options, key=lambda x: x.get("total_cost", float('inf')))

    # Identify cheapest and fastest
    cheapest = sorted_options[0] if sorted_options else None
    fastest = min(sorted_options, key=lambda x: x.get("estimated_days_max", 999)) if sorted_options else None

    return {
        "success": True,
        "options": sorted_options,
        "cheapest": cheapest,
        "fastest": fastest,
        "destination": order_data["destination"],
        "free_shipping_info": _get_free_shipping_info(order_data, seller, tenant)
    }


def _get_shipping_rule_options(order_data: Dict, seller: str, tenant: str) -> List[Dict]:
    """Get shipping options from shipping rules."""
    options = []

    # Get applicable rules
    filters = {"is_active": 1}
    or_filters = []

    if seller:
        or_filters = [
            {"seller": seller},
            {"seller": ["is", "not set"]}
        ]

    if tenant:
        if or_filters:
            or_filters[0]["tenant"] = tenant
            or_filters.append({"tenant": tenant, "seller": ["is", "not set"]})
        else:
            or_filters = [
                {"tenant": tenant},
                {"tenant": ["is", "not set"]}
            ]

    rules = frappe.get_all(
        "Shipping Rule",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=["name"],
        order_by="priority DESC"
    )

    for rule_ref in rules:
        try:
            rule = frappe.get_doc("Shipping Rule", rule_ref.name)
            result = rule.calculate_shipping(order_data)

            if result:
                # Get carrier details if linked
                carrier_info = {}
                if rule.default_carrier:
                    carrier_info = frappe.db.get_value(
                        "Carrier",
                        rule.default_carrier,
                        ["carrier_name", "logo", "tracking_url_template"],
                        as_dict=True
                    ) or {}

                options.append({
                    "source": "shipping_rule",
                    "rule_name": rule.rule_name,
                    "carrier": rule.default_carrier,
                    "carrier_name": carrier_info.get("carrier_name") or rule.default_carrier,
                    "carrier_logo": carrier_info.get("logo"),
                    "total_cost": flt(result.get("shipping_amount"), 2),
                    "currency": rule.currency or "TRY",
                    "is_free_shipping": result.get("is_free_shipping", False),
                    "estimated_days_min": result.get("estimated_days_min"),
                    "estimated_days_max": result.get("estimated_days_max"),
                    "breakdown": result.get("breakdown", {}),
                    "is_express": False
                })
        except Exception as e:
            frappe.log_error(
                f"Failed to calculate shipping for rule {rule_ref.name}: {str(e)}",
                "Shipping Calculator Error"
            )

    return options


def _get_carrier_api_rates(order_data: Dict, seller: str) -> List[Dict]:
    """Get real-time rates from carrier APIs."""
    options = []

    # Get carriers with API enabled
    carriers = frappe.get_all(
        "Carrier",
        filters={
            "enabled": 1,
            "has_api_integration": 1,
            "supports_rate_api": 1
        },
        fields=["name", "carrier_name", "logo", "currency"]
    )

    # Build addresses
    origin_address = {}
    if seller:
        seller_data = frappe.db.get_value(
            "Seller Profile",
            seller,
            ["warehouse_city", "warehouse_country", "warehouse_postal_code"],
            as_dict=True
        )
        if seller_data:
            origin_address = {
                "city": seller_data.get("warehouse_city"),
                "country": seller_data.get("warehouse_country") or "Turkey",
                "postal_code": seller_data.get("warehouse_postal_code")
            }

    destination_address = order_data.get("destination", {})

    package = {
        "weight": flt(order_data.get("total_weight", 1)),
        "quantity": cint(order_data.get("item_count", 1))
    }

    for carrier_ref in carriers:
        try:
            carrier = frappe.get_doc("Carrier", carrier_ref.name)
            result = carrier.get_rates_from_api(origin_address, destination_address, package)

            if result.get("status") == "success":
                for rate in result.get("rates", []):
                    options.append({
                        "source": "carrier_api",
                        "rule_name": f"{carrier_ref.carrier_name} - {rate.get('service', 'Standard')}",
                        "carrier": carrier_ref.name,
                        "carrier_name": carrier_ref.carrier_name,
                        "carrier_logo": carrier_ref.logo,
                        "service": rate.get("service"),
                        "total_cost": flt(rate.get("price"), 2),
                        "currency": rate.get("currency") or carrier_ref.currency or "TRY",
                        "is_free_shipping": False,
                        "estimated_days_min": rate.get("transit_days"),
                        "estimated_days_max": rate.get("transit_days"),
                        "is_express": "express" in rate.get("service", "").lower()
                    })
        except Exception as e:
            frappe.log_error(
                f"Failed to get carrier API rates for {carrier_ref.name}: {str(e)}",
                "Carrier API Error"
            )

    return options


def _get_express_options(order_data: Dict, seller: str, tenant: str) -> List[Dict]:
    """Get express delivery options."""
    options = []

    # Get rules with express available
    filters = {
        "is_active": 1,
        "express_available": 1
    }

    or_filters = []
    if seller:
        or_filters = [
            {"seller": seller},
            {"seller": ["is", "not set"]}
        ]

    rules = frappe.get_all(
        "Shipping Rule",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=["name"]
    )

    express_order_data = {**order_data, "express": True}

    for rule_ref in rules:
        try:
            rule = frappe.get_doc("Shipping Rule", rule_ref.name)
            result = rule.calculate_shipping(express_order_data)

            if result:
                carrier_info = {}
                if rule.default_carrier:
                    carrier_info = frappe.db.get_value(
                        "Carrier",
                        rule.default_carrier,
                        ["carrier_name", "logo"],
                        as_dict=True
                    ) or {}

                options.append({
                    "source": "shipping_rule",
                    "rule_name": f"{rule.rule_name} (Express)",
                    "carrier": rule.default_carrier,
                    "carrier_name": carrier_info.get("carrier_name") or rule.default_carrier,
                    "carrier_logo": carrier_info.get("logo"),
                    "total_cost": flt(result.get("shipping_amount"), 2),
                    "currency": rule.currency or "TRY",
                    "is_free_shipping": False,
                    "estimated_days_min": result.get("estimated_days_min"),
                    "estimated_days_max": result.get("estimated_days_max"),
                    "breakdown": result.get("breakdown", {}),
                    "is_express": True
                })
        except Exception as e:
            pass  # Express not available is fine

    return options


def _deduplicate_options(options: List[Dict]) -> List[Dict]:
    """Remove duplicate shipping options."""
    seen = set()
    unique = []

    for opt in options:
        key = f"{opt.get('carrier')}:{opt.get('service', 'standard')}:{opt.get('is_express')}"
        if key not in seen:
            seen.add(key)
            unique.append(opt)

    return unique


def _get_free_shipping_info(order_data: Dict, seller: str, tenant: str) -> Dict:
    """Get information about free shipping eligibility."""
    order_amount = flt(order_data.get("order_amount", 0))

    # Find lowest free shipping threshold
    filters = {
        "is_active": 1,
        "free_shipping_enabled": 1
    }

    or_filters = []
    if seller:
        or_filters = [
            {"seller": seller},
            {"seller": ["is", "not set"]}
        ]

    rules = frappe.get_all(
        "Shipping Rule",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=["name", "free_shipping_threshold"],
        order_by="free_shipping_threshold ASC"
    )

    if not rules:
        return {"available": False, "message": _("Free shipping not available")}

    lowest_threshold = flt(rules[0].free_shipping_threshold)

    if order_amount >= lowest_threshold:
        return {
            "available": True,
            "qualified": True,
            "threshold": lowest_threshold,
            "message": _("Free shipping applied!")
        }
    else:
        remaining = lowest_threshold - order_amount
        return {
            "available": True,
            "qualified": False,
            "threshold": lowest_threshold,
            "remaining_amount": remaining,
            "message": _("Add {0} more for free shipping").format(
                frappe.format_value(remaining, {"fieldtype": "Currency"})
            )
        }


# =================================================================
# Checkout Integration
# =================================================================

@frappe.whitelist()
def get_checkout_shipping_options(
    order_amount: float,
    items: str,
    destination_address: str,
    seller: str = None
) -> Dict:
    """
    Get shipping options for checkout.

    Args:
        order_amount: Total order amount
        items: JSON string of cart items
        destination_address: JSON string of destination address
        seller: Seller profile name

    Returns:
        dict: Shipping options for checkout display
    """
    items_list = json.loads(items) if isinstance(items, str) else items
    destination = json.loads(destination_address) if isinstance(destination_address, str) else destination_address

    # Calculate total weight and categories from items
    total_weight = 0
    categories = set()

    for item in items_list:
        total_weight += flt(item.get("weight", 0)) * cint(item.get("quantity", 1))
        if item.get("category"):
            categories.add(item.get("category"))

    result = calculate_shipping_options(
        order_amount=flt(order_amount),
        total_weight=total_weight,
        item_count=len(items_list),
        destination_country=destination.get("country", "Turkey"),
        destination_city=destination.get("city"),
        postal_code=destination.get("postal_code"),
        categories=list(categories),
        seller=seller,
        include_express=True,
        use_carrier_api=True
    )

    return result


@frappe.whitelist()
def apply_shipping_to_order(order_name: str, shipping_option: str) -> Dict:
    """
    Apply selected shipping option to an order.

    Args:
        order_name: Order document name
        shipping_option: JSON string of selected shipping option

    Returns:
        dict: Updated order info
    """
    option = json.loads(shipping_option) if isinstance(shipping_option, str) else shipping_option

    order = frappe.get_doc("Order", order_name)

    # Update order with shipping info
    order.shipping_amount = flt(option.get("total_cost"))
    order.shipping_carrier = option.get("carrier")
    order.shipping_method = option.get("rule_name")
    order.estimated_delivery_days = option.get("estimated_days_max")

    # Recalculate totals
    order.total_amount = flt(order.subtotal) + flt(order.shipping_amount) + flt(order.tax_amount)

    order.save()

    return {
        "success": True,
        "order": order_name,
        "shipping_amount": order.shipping_amount,
        "total_amount": order.total_amount
    }


# =================================================================
# Default Shipping Rules Setup
# =================================================================

def create_default_turkish_shipping_rules():
    """
    Create default shipping rules for Turkish marketplace.

    Creates:
    - Standard domestic shipping
    - Express domestic shipping
    - Free shipping over threshold
    - Local (same city) delivery
    """
    shipping_rules = [
        {
            "rule_name": "Türkiye Standart Kargo",
            "rule_type": "Standard",
            "calculation_method": "Weight Based",
            "is_active": 1,
            "priority": 10,
            "base_rate": 25.00,
            "per_kg_rate": 5.00,
            "currency": "TRY",
            "tax_rate": 18,
            "estimated_days_min": 2,
            "estimated_days_max": 5,
            "free_shipping_enabled": 1,
            "free_shipping_threshold": 500.00,
            "express_available": 1,
            "express_surcharge": 30.00,
            "express_days": 1,
            "apply_to_all_categories": 1,
            "handling_fee": 5.00,
            "handling_fee_type": "Fixed",
            "description": "Türkiye geneli standart kargo teslimatı. 500₺ üzeri siparişlerde ücretsiz."
        },
        {
            "rule_name": "İstanbul İçi Teslimat",
            "rule_type": "Local Delivery",
            "calculation_method": "Fixed",
            "is_active": 1,
            "priority": 20,
            "base_rate": 15.00,
            "currency": "TRY",
            "tax_rate": 18,
            "estimated_days_min": 1,
            "estimated_days_max": 2,
            "free_shipping_enabled": 1,
            "free_shipping_threshold": 200.00,
            "express_available": 1,
            "express_surcharge": 15.00,
            "express_days": 0,
            "apply_to_all_categories": 1,
            "description": "İstanbul içi hızlı teslimat. Aynı gün teslimat seçeneği mevcuttur.",
            "zones": [
                {"country": "Turkey", "city": "İstanbul"}
            ]
        },
        {
            "rule_name": "Ağır Kargo (10kg+)",
            "rule_type": "Freight",
            "calculation_method": "Weight Tiered",
            "is_active": 1,
            "priority": 5,
            "currency": "TRY",
            "tax_rate": 18,
            "min_weight": 10,
            "estimated_days_min": 3,
            "estimated_days_max": 7,
            "apply_to_all_categories": 1,
            "handling_fee": 20.00,
            "handling_fee_type": "Fixed",
            "description": "10 kg üzeri ağır kargolar için özel tarife.",
            "rate_tiers": [
                {"threshold_from": 10, "threshold_to": 30, "rate": 50.00},
                {"threshold_from": 30, "threshold_to": 50, "rate": 80.00},
                {"threshold_from": 50, "threshold_to": 100, "rate": 120.00},
                {"threshold_from": 100, "threshold_to": 0, "rate": 200.00}
            ]
        },
        {
            "rule_name": "Ekonomik Kargo",
            "rule_type": "Economy",
            "calculation_method": "Price Tiered",
            "is_active": 1,
            "priority": 8,
            "currency": "TRY",
            "tax_rate": 18,
            "estimated_days_min": 5,
            "estimated_days_max": 10,
            "apply_to_all_categories": 1,
            "description": "Ekonomik fiyatlı, uzun süreli teslimat seçeneği.",
            "rate_tiers": [
                {"threshold_from": 0, "threshold_to": 100, "rate": 15.00},
                {"threshold_from": 100, "threshold_to": 250, "rate": 20.00},
                {"threshold_from": 250, "threshold_to": 500, "rate": 25.00},
                {"threshold_from": 500, "threshold_to": 0, "rate": 0}
            ]
        }
    ]

    created = []
    skipped = []

    for rule_data in shipping_rules:
        rule_name = rule_data.get("rule_name")

        if frappe.db.exists("Shipping Rule", rule_name):
            skipped.append(rule_name)
            continue

        # Extract child table data
        zones_data = rule_data.pop("zones", [])
        rate_tiers_data = rule_data.pop("rate_tiers", [])

        # Create rule
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            **rule_data
        })

        # Add zones
        for zone in zones_data:
            rule.append("zones", zone)

        # Add rate tiers
        for tier in rate_tiers_data:
            rule.append("rate_tiers", tier)

        rule.insert(ignore_permissions=True)
        created.append(rule_name)

    frappe.db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "message": _("Created {0} shipping rules, {1} already existed").format(
            len(created), len(skipped)
        )
    }


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def setup_default_shipping_rules():
    """
    API endpoint to create default Turkish shipping rules.

    Returns:
        dict: Setup result
    """
    if not frappe.has_permission("Shipping Rule", "create"):
        frappe.throw(_("Not permitted"))

    return create_default_turkish_shipping_rules()


@frappe.whitelist()
def get_shipping_for_listing(
    listing: str,
    quantity: int = 1,
    destination_city: str = None
) -> Dict:
    """
    Get shipping options for a specific listing.

    Args:
        listing: Listing document name
        quantity: Number of items
        destination_city: Destination city

    Returns:
        dict: Shipping options
    """
    listing_doc = frappe.get_doc("Listing", listing)

    return calculate_shipping_options(
        order_amount=flt(listing_doc.selling_price) * cint(quantity),
        total_weight=flt(listing_doc.weight or 0) * cint(quantity),
        item_count=cint(quantity),
        destination_city=destination_city,
        categories=[listing_doc.category] if listing_doc.category else [],
        seller=listing_doc.seller
    )


@frappe.whitelist()
def estimate_delivery_date(
    shipping_option: str,
    order_date: str = None
) -> Dict:
    """
    Estimate delivery date based on shipping option.

    Args:
        shipping_option: JSON string of shipping option
        order_date: Order date (defaults to today)

    Returns:
        dict: Estimated delivery date range
    """
    from frappe.utils import add_days, getdate

    option = json.loads(shipping_option) if isinstance(shipping_option, str) else shipping_option
    base_date = getdate(order_date) if order_date else getdate(nowdate())

    min_days = cint(option.get("estimated_days_min", 1))
    max_days = cint(option.get("estimated_days_max", 5))

    return {
        "estimated_delivery_min": str(add_days(base_date, min_days)),
        "estimated_delivery_max": str(add_days(base_date, max_days)),
        "is_express": option.get("is_express", False),
        "carrier": option.get("carrier_name")
    }
