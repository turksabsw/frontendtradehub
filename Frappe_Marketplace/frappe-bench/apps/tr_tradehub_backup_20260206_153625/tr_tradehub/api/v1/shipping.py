# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Shipping & Logistics API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Shipping rate calculation and rule management
- Shipment creation and management
- Tracking queries and timeline
- Turkish carrier integration (Yurtici, Aras, MNG, PTT)
- International carrier support (UPS, DHL, FedEx)
- Pickup scheduling
- Carrier webhook handling
- Shipping analytics and statistics

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.shipping.<function_name>

All endpoints follow Frappe conventions and patterns.
"""

import json
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import (
    cint,
    cstr,
    flt,
    getdate,
    nowdate,
    now_datetime,
    add_days,
    add_hours,
    get_datetime,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "rate_calculate": {"limit": 60, "window": 60},  # 60 per minute
    "shipment_create": {"limit": 20, "window": 300},  # 20 per 5 min
    "shipment_update": {"limit": 30, "window": 60},  # 30 per minute
    "tracking_query": {"limit": 60, "window": 60},  # 60 per minute
    "pickup_schedule": {"limit": 10, "window": 300},  # 10 per 5 min
    "label_print": {"limit": 30, "window": 300},  # 30 per 5 min
    "webhook": {"limit": 200, "window": 60},  # 200 per minute (carrier callbacks)
}

# Supported carriers
SUPPORTED_CARRIERS = [
    "Yurtici Kargo",
    "Aras Kargo",
    "MNG Kargo",
    "PTT Kargo",
    "SuratKargo",
    "Trendyol Express",
    "HepsiJet",
    "UPS",
    "DHL",
    "FedEx",
]

# Turkish carriers with API integration
TURKISH_CARRIERS_WITH_API = ["Yurtici Kargo", "Aras Kargo"]

# Shipment statuses
SHIPMENT_STATUSES = [
    "Pending",
    "Label Generated",
    "Pickup Scheduled",
    "Picked Up",
    "In Transit",
    "Out for Delivery",
    "Delivered",
    "Failed Delivery",
    "Returning",
    "Returned",
    "Exception",
    "Cancelled",
]


# =============================================================================
# RATE LIMITING
# =============================================================================


def check_rate_limit(
    action: str,
    identifier: Optional[str] = None,
    throw: bool = True,
) -> bool:
    """
    Check if an action is rate limited.

    Args:
        action: The action to check
        identifier: User/IP identifier (defaults to session user)
        throw: If True, raises exception when rate limited

    Returns:
        bool: True if allowed, False if rate limited

    Raises:
        frappe.TooManyRequestsError: If throw=True and rate limited
    """
    if action not in RATE_LIMITS:
        return True

    config = RATE_LIMITS[action]

    # Get identifier (use session user by default)
    if not identifier:
        identifier = frappe.session.user or "unknown"

    cache_key = f"rate_limit:shipping:{action}:{identifier}"

    # Get current count
    current = frappe.cache().get_value(cache_key)
    if current is None:
        frappe.cache().set_value(cache_key, 1, expires_in_sec=config["window"])
        return True

    current = cint(current)
    if current >= config["limit"]:
        if throw:
            frappe.throw(
                _("Too many requests. Please try again later."),
                exc=frappe.TooManyRequestsError,
            )
        return False

    frappe.cache().set_value(cache_key, current + 1, expires_in_sec=config["window"])
    return True


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_current_seller() -> Optional[str]:
    """
    Get the seller profile for the current user.

    Returns:
        str or None: Seller profile name or None if not a seller
    """
    user = frappe.session.user
    if user == "Guest":
        return None

    return frappe.db.get_value("Seller Profile", {"user": user}, "name")


def get_current_buyer() -> str:
    """
    Get the current buyer (user).

    Returns:
        str: User name
    """
    return frappe.session.user


def require_login(func):
    """Decorator to require user login for API endpoints."""
    def wrapper(*args, **kwargs):
        if frappe.session.user == "Guest":
            frappe.throw(_("You must be logged in to perform this action"))
        return func(*args, **kwargs)
    return wrapper


def require_seller(func):
    """Decorator to require seller profile for API endpoints."""
    def wrapper(*args, **kwargs):
        seller = get_current_seller()
        if not seller:
            frappe.throw(_("You must be a seller to access this resource"))
        kwargs["_seller"] = seller
        return func(*args, **kwargs)
    return wrapper


def _log_shipping_event(
    event_type: str,
    shipment_name: Optional[str] = None,
    sub_order_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Log shipping-related events for audit trail."""
    try:
        # Log to Activity Log
        ip_address = None
        user_agent = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
                user_agent = str(frappe.request.user_agent)[:500]
        except Exception:
            pass

        frappe.get_doc({
            "doctype": "Activity Log",
            "user": frappe.session.user,
            "subject": f"Shipping: {event_type}",
            "content": json.dumps({
                "event_type": event_type,
                "shipment": shipment_name,
                "sub_order": sub_order_name,
                "details": details,
                "ip_address": ip_address,
            }),
            "reference_doctype": "Marketplace Shipment" if shipment_name else None,
            "reference_name": shipment_name,
        }).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Shipping event logging error: {str(e)}", "Shipping API")


def _validate_address(address: Dict[str, Any], address_type: str = "address") -> Dict[str, Any]:
    """
    Validate and normalize an address.

    Args:
        address: Address dictionary
        address_type: Type of address (origin, destination)

    Returns:
        dict: Validated and normalized address

    Raises:
        frappe.ValidationError: If address is invalid
    """
    if not address:
        frappe.throw(_("{0} is required").format(address_type.title()))

    required_fields = ["address_line1", "city"]
    for field in required_fields:
        if not address.get(field):
            frappe.throw(_("{0} {1} is required").format(address_type.title(), field))

    # Set default country
    if not address.get("country"):
        address["country"] = "Turkey"

    # Normalize Turkish city names
    if address.get("city"):
        address["city"] = cstr(address["city"]).strip().title()

    # Validate Turkish postal code format (5 digits)
    if address.get("postal_code"):
        postal_code = cstr(address["postal_code"]).strip().replace(" ", "")
        if address.get("country") in ["Turkey", "Türkiye", "TR"]:
            if not postal_code.isdigit() or len(postal_code) != 5:
                frappe.throw(_("Turkish postal code must be 5 digits"))
        address["postal_code"] = postal_code

    return address


def _normalize_carrier_name(carrier: str) -> str:
    """Normalize carrier name to standard format."""
    carrier_map = {
        "yurtici": "Yurtici Kargo",
        "yurticikargo": "Yurtici Kargo",
        "yk": "Yurtici Kargo",
        "aras": "Aras Kargo",
        "araskargo": "Aras Kargo",
        "ak": "Aras Kargo",
        "mng": "MNG Kargo",
        "ptt": "PTT Kargo",
        "surat": "SuratKargo",
        "suratkargo": "SuratKargo",
        "trendyol": "Trendyol Express",
        "hepsijet": "HepsiJet",
        "ups": "UPS",
        "dhl": "DHL",
        "fedex": "FedEx",
    }

    key = cstr(carrier).lower().strip().replace(" ", "").replace("_", "")
    return carrier_map.get(key, carrier)


# =============================================================================
# SHIPPING RATE CALCULATION ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def calculate_shipping_rates(
    destination_city: str,
    destination_country: str = "Turkey",
    destination_postal_code: Optional[str] = None,
    total_weight: float = 0,
    total_amount: float = 0,
    item_count: int = 1,
    origin_city: Optional[str] = None,
    origin_country: str = "Turkey",
    seller: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate available shipping rates for a given destination.

    Args:
        destination_city: Destination city
        destination_country: Destination country (default: Turkey)
        destination_postal_code: Destination postal code (optional)
        total_weight: Total package weight in kg
        total_amount: Order total amount for free shipping calculation
        item_count: Number of items
        origin_city: Origin city (optional, uses seller's city if not provided)
        origin_country: Origin country (default: Turkey)
        seller: Seller profile name (optional)
        category: Product category for category-specific rules (optional)

    Returns:
        dict: Available shipping rates with estimated delivery times
    """
    check_rate_limit("rate_calculate")

    try:
        # Build filters for shipping rules
        filters = {
            "status": "Active",
            "docstatus": ["<", 2],
        }

        # Get applicable shipping rules
        rules = frappe.get_all(
            "Shipping Rule",
            filters=filters,
            fields=[
                "name", "rule_name", "carrier", "calculation_method",
                "base_rate", "per_kg_rate", "per_item_rate",
                "free_shipping_enabled", "free_shipping_threshold",
                "min_delivery_days", "max_delivery_days",
                "is_express", "express_surcharge",
                "min_order_amount", "max_order_amount",
                "min_weight", "max_weight",
            ],
            order_by="priority desc",
        )

        rates = []
        for rule in rules:
            try:
                # Check order amount constraints
                if rule.min_order_amount and flt(total_amount) < flt(rule.min_order_amount):
                    continue
                if rule.max_order_amount and flt(total_amount) > flt(rule.max_order_amount):
                    continue

                # Check weight constraints
                if rule.min_weight and flt(total_weight) < flt(rule.min_weight):
                    continue
                if rule.max_weight and flt(total_weight) > flt(rule.max_weight):
                    continue

                # Check zone restrictions
                if not _check_zone_eligibility(
                    rule.name, destination_city, destination_country, destination_postal_code
                ):
                    continue

                # Calculate rate
                shipping_rate = _calculate_rule_rate(
                    rule=rule,
                    weight=flt(total_weight),
                    amount=flt(total_amount),
                    item_count=cint(item_count),
                )

                # Check free shipping
                is_free_shipping = False
                if rule.free_shipping_enabled and flt(total_amount) >= flt(rule.free_shipping_threshold):
                    is_free_shipping = True
                    shipping_rate = 0

                rates.append({
                    "rule_name": rule.name,
                    "display_name": rule.rule_name,
                    "carrier": rule.carrier,
                    "rate": shipping_rate,
                    "is_free_shipping": is_free_shipping,
                    "free_shipping_threshold": flt(rule.free_shipping_threshold) if rule.free_shipping_enabled else None,
                    "min_delivery_days": cint(rule.min_delivery_days),
                    "max_delivery_days": cint(rule.max_delivery_days),
                    "is_express": rule.is_express,
                    "currency": "TRY",
                })

            except Exception as e:
                frappe.log_error(
                    f"Error calculating rate for rule {rule.name}: {str(e)}",
                    "Shipping Rate Calculation"
                )
                continue

        # Sort by rate (cheapest first)
        rates.sort(key=lambda x: (not x["is_express"], x["rate"]))

        return {
            "success": True,
            "rates": rates,
            "destination": {
                "city": destination_city,
                "country": destination_country,
                "postal_code": destination_postal_code,
            },
            "parameters": {
                "total_weight": flt(total_weight),
                "total_amount": flt(total_amount),
                "item_count": cint(item_count),
            },
        }

    except Exception as e:
        frappe.log_error(f"Shipping rate calculation error: {str(e)}", "Shipping API")
        frappe.throw(_("Error calculating shipping rates"))


def _check_zone_eligibility(
    rule_name: str,
    city: str,
    country: str,
    postal_code: Optional[str] = None,
) -> bool:
    """Check if destination is eligible for a shipping rule's zones."""
    # Get zones for the rule
    zones = frappe.get_all(
        "Shipping Zone",
        filters={"parent": rule_name},
        fields=["country", "city", "postal_code_from", "postal_code_to", "is_excluded"],
    )

    # If no zones defined, rule applies to all destinations
    if not zones:
        return True

    # Check each zone
    for zone in zones:
        # Check country
        if zone.country and zone.country.lower() != country.lower():
            continue

        # Check city (if specified)
        if zone.city and zone.city.lower() != city.lower():
            continue

        # Check postal code range (if specified)
        if zone.postal_code_from and postal_code:
            if postal_code < zone.postal_code_from:
                continue
            if zone.postal_code_to and postal_code > zone.postal_code_to:
                continue

        # If zone is excluded, destination is not eligible
        if zone.is_excluded:
            return False

        # Destination matches a non-excluded zone
        return True

    # No matching zone found - default to not eligible if zones are defined
    return False


def _calculate_rule_rate(
    rule: Dict[str, Any],
    weight: float,
    amount: float,
    item_count: int,
) -> float:
    """Calculate shipping rate based on rule configuration."""
    method = rule.calculation_method

    if method == "Fixed":
        rate = flt(rule.base_rate)

    elif method == "Weight Based":
        rate = flt(rule.base_rate) + (flt(weight) * flt(rule.per_kg_rate))

    elif method == "Price Percentage":
        # Get percentage from rate tiers
        tiers = frappe.get_all(
            "Shipping Rate Tier",
            filters={"parent": rule.name},
            fields=["threshold_from", "threshold_to", "rate_value"],
            order_by="threshold_from asc",
        )

        percentage = 0
        for tier in tiers:
            if flt(tier.threshold_from) <= amount:
                if not tier.threshold_to or amount <= flt(tier.threshold_to):
                    percentage = flt(tier.rate_value)
                    break

        rate = amount * (percentage / 100)

    elif method == "Item Count":
        rate = flt(rule.base_rate) + (cint(item_count) * flt(rule.per_item_rate))

    elif method in ["Weight Tiered", "Price Tiered"]:
        # Get rate from tiers
        tiers = frappe.get_all(
            "Shipping Rate Tier",
            filters={"parent": rule.name},
            fields=["threshold_from", "threshold_to", "rate_value"],
            order_by="threshold_from asc",
        )

        threshold_value = weight if method == "Weight Tiered" else amount
        rate = flt(rule.base_rate)

        for tier in tiers:
            if flt(tier.threshold_from) <= threshold_value:
                if not tier.threshold_to or threshold_value <= flt(tier.threshold_to):
                    rate = flt(tier.rate_value)
                    break

    else:
        rate = flt(rule.base_rate)

    # Add express surcharge if applicable
    if rule.is_express and flt(rule.express_surcharge) > 0:
        rate += flt(rule.express_surcharge)

    return round(rate, 2)


@frappe.whitelist(allow_guest=False)
def get_shipping_rules(
    seller: Optional[str] = None,
    carrier: Optional[str] = None,
    is_express: Optional[bool] = None,
    status: str = "Active",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get available shipping rules.

    Args:
        seller: Filter by seller (optional)
        carrier: Filter by carrier (optional)
        is_express: Filter by express shipping (optional)
        status: Rule status (default: Active)
        page: Page number (default: 1)
        page_size: Items per page (default: 20)

    Returns:
        dict: List of shipping rules with pagination
    """
    filters = {"status": status}

    if seller:
        filters["seller"] = seller
    if carrier:
        filters["carrier"] = _normalize_carrier_name(carrier)
    if is_express is not None:
        filters["is_express"] = cint(is_express)

    # Count total
    total = frappe.db.count("Shipping Rule", filters)

    # Get rules with pagination
    rules = frappe.get_all(
        "Shipping Rule",
        filters=filters,
        fields=[
            "name", "rule_name", "carrier", "calculation_method",
            "base_rate", "free_shipping_enabled", "free_shipping_threshold",
            "min_delivery_days", "max_delivery_days", "is_express",
            "status", "priority", "creation",
        ],
        order_by="priority desc, creation desc",
        start=(page - 1) * page_size,
        limit=page_size,
    )

    return {
        "success": True,
        "rules": rules,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@frappe.whitelist(allow_guest=False)
def get_shipping_rule(rule_name: str) -> Dict[str, Any]:
    """
    Get details of a specific shipping rule.

    Args:
        rule_name: Shipping rule name

    Returns:
        dict: Shipping rule details
    """
    if not frappe.db.exists("Shipping Rule", rule_name):
        frappe.throw(_("Shipping Rule not found"))

    rule = frappe.get_doc("Shipping Rule", rule_name)

    return {
        "success": True,
        "rule": {
            "name": rule.name,
            "rule_name": rule.rule_name,
            "carrier": rule.carrier,
            "calculation_method": rule.calculation_method,
            "base_rate": flt(rule.base_rate),
            "per_kg_rate": flt(rule.per_kg_rate),
            "per_item_rate": flt(rule.per_item_rate),
            "free_shipping_enabled": rule.free_shipping_enabled,
            "free_shipping_threshold": flt(rule.free_shipping_threshold),
            "min_delivery_days": cint(rule.min_delivery_days),
            "max_delivery_days": cint(rule.max_delivery_days),
            "is_express": rule.is_express,
            "express_surcharge": flt(rule.express_surcharge),
            "min_order_amount": flt(rule.min_order_amount),
            "max_order_amount": flt(rule.max_order_amount),
            "min_weight": flt(rule.min_weight),
            "max_weight": flt(rule.max_weight),
            "status": rule.status,
            "priority": cint(rule.priority),
            "zones": [
                {
                    "country": z.country,
                    "city": z.city,
                    "postal_code_from": z.postal_code_from,
                    "postal_code_to": z.postal_code_to,
                    "is_excluded": z.is_excluded,
                }
                for z in rule.zones
            ] if hasattr(rule, "zones") and rule.zones else [],
            "rate_tiers": [
                {
                    "threshold_from": flt(t.threshold_from),
                    "threshold_to": flt(t.threshold_to),
                    "rate_value": flt(t.rate_value),
                }
                for t in rule.rate_tiers
            ] if hasattr(rule, "rate_tiers") and rule.rate_tiers else [],
        },
    }


# =============================================================================
# SHIPMENT MANAGEMENT ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def create_shipment(
    sub_order: str,
    carrier: str,
    origin_address: Dict[str, Any],
    package_info: Optional[Dict[str, Any]] = None,
    service_type: Optional[str] = None,
    special_instructions: Optional[str] = None,
    declared_value: Optional[float] = None,
    is_cod: bool = False,
    cod_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Create a new shipment for a sub order.

    Args:
        sub_order: Sub Order name
        carrier: Carrier name
        origin_address: Sender/origin address
        package_info: Package details (weight, dimensions, count)
        service_type: Service type (Standard, Express, etc.)
        special_instructions: Special handling instructions
        declared_value: Declared value for insurance
        is_cod: Is Cash on Delivery
        cod_amount: COD amount to collect

    Returns:
        dict: Created shipment details
    """
    check_rate_limit("shipment_create")

    # Validate sub order exists and user has permission
    if not frappe.db.exists("Sub Order", sub_order):
        frappe.throw(_("Sub Order not found"))

    sub_order_doc = frappe.get_doc("Sub Order", sub_order)

    # Check permission - seller must own this sub order
    seller = get_current_seller()
    if seller and sub_order_doc.seller != seller:
        frappe.throw(_("You don't have permission to create shipment for this order"))

    # Normalize carrier
    carrier = _normalize_carrier_name(carrier)
    if carrier not in SUPPORTED_CARRIERS:
        frappe.throw(_("Unsupported carrier: {0}").format(carrier))

    # Validate origin address
    origin_address = _validate_address(origin_address, "origin")

    # Default package info
    if not package_info:
        package_info = {}

    try:
        # Create shipment document
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": sub_order,
            "marketplace_order": sub_order_doc.marketplace_order,
            "seller": sub_order_doc.seller,
            "tenant": sub_order_doc.tenant if hasattr(sub_order_doc, "tenant") else None,
            "carrier": carrier,
            "service_type": service_type or "Standard",
            "status": "Pending",
            # Origin address
            "sender_name": origin_address.get("name") or origin_address.get("sender_name"),
            "sender_phone": origin_address.get("phone") or origin_address.get("sender_phone"),
            "sender_email": origin_address.get("email"),
            "origin_address_line1": origin_address.get("address_line1"),
            "origin_address_line2": origin_address.get("address_line2"),
            "origin_city": origin_address.get("city"),
            "origin_state": origin_address.get("state"),
            "origin_postal_code": origin_address.get("postal_code"),
            "origin_country": origin_address.get("country", "Turkey"),
            # Package info
            "package_count": cint(package_info.get("count", 1)),
            "total_weight": flt(package_info.get("weight", 0)),
            "total_length": flt(package_info.get("length", 0)),
            "total_width": flt(package_info.get("width", 0)),
            "total_height": flt(package_info.get("height", 0)),
            # Additional info
            "special_instructions": special_instructions,
            "declared_value": flt(declared_value) if declared_value else None,
            "is_cod": cint(is_cod),
            "cod_amount": flt(cod_amount) if is_cod else None,
        })

        shipment.insert()

        # Log event
        _log_shipping_event(
            event_type="Shipment Created",
            shipment_name=shipment.name,
            sub_order_name=sub_order,
            details={
                "carrier": carrier,
                "service_type": service_type,
            },
        )

        return {
            "success": True,
            "message": _("Shipment created successfully"),
            "shipment": {
                "name": shipment.name,
                "shipment_id": shipment.shipment_id,
                "status": shipment.status,
                "carrier": shipment.carrier,
                "sub_order": shipment.sub_order,
            },
        }

    except Exception as e:
        frappe.log_error(f"Shipment creation error: {str(e)}", "Shipping API")
        frappe.throw(_("Error creating shipment"))


@frappe.whitelist(allow_guest=False)
def get_shipment(shipment_name: str) -> Dict[str, Any]:
    """
    Get details of a specific shipment.

    Args:
        shipment_name: Shipment name or shipment_id

    Returns:
        dict: Shipment details with tracking information
    """
    # Try to find by name or shipment_id
    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        # Try by shipment_id
        shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": shipment_name},
            "name"
        )
        if not shipment_name:
            frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    user = frappe.session.user
    seller = get_current_seller()

    # Allow access to seller, buyer, or admin
    can_access = False
    if seller and shipment.seller == seller:
        can_access = True
    elif shipment.marketplace_order:
        buyer = frappe.db.get_value("Marketplace Order", shipment.marketplace_order, "buyer")
        if buyer == user:
            can_access = True
    if frappe.has_permission("Marketplace Shipment", "read"):
        can_access = True

    if not can_access:
        frappe.throw(_("You don't have permission to view this shipment"))

    # Get tracking events
    tracking_events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment.name},
        fields=[
            "name", "event_type", "event_description", "event_timestamp",
            "location_city", "location_country", "facility_name",
            "is_milestone", "severity",
        ],
        order_by="event_timestamp desc",
        limit=20,
    )

    return {
        "success": True,
        "shipment": {
            "name": shipment.name,
            "shipment_id": shipment.shipment_id,
            "status": shipment.status,
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
            "tracking_url": shipment.tracking_url,
            "sub_order": shipment.sub_order,
            "marketplace_order": shipment.marketplace_order,
            "seller": shipment.seller,
            # Origin
            "origin": {
                "name": shipment.sender_name,
                "phone": shipment.sender_phone,
                "address_line1": shipment.origin_address_line1,
                "address_line2": shipment.origin_address_line2,
                "city": shipment.origin_city,
                "state": shipment.origin_state,
                "postal_code": shipment.origin_postal_code,
                "country": shipment.origin_country,
            },
            # Destination
            "destination": {
                "name": shipment.recipient_name,
                "phone": shipment.recipient_phone,
                "address_line1": shipment.destination_address_line1,
                "address_line2": shipment.destination_address_line2,
                "city": shipment.destination_city,
                "state": shipment.destination_state,
                "postal_code": shipment.destination_postal_code,
                "country": shipment.destination_country,
            },
            # Package info
            "package_count": cint(shipment.package_count),
            "total_weight": flt(shipment.total_weight),
            "dimensions": {
                "length": flt(shipment.total_length),
                "width": flt(shipment.total_width),
                "height": flt(shipment.total_height),
            },
            # Costs
            "shipping_cost": flt(shipment.shipping_cost),
            "insurance_cost": flt(shipment.insurance_cost),
            "total_cost": flt(shipment.total_cost),
            # Dates
            "shipped_at": shipment.shipped_at,
            "delivered_at": shipment.delivered_at,
            "estimated_delivery_date": shipment.estimated_delivery_date,
            # COD
            "is_cod": shipment.is_cod,
            "cod_amount": flt(shipment.cod_amount) if shipment.is_cod else None,
            # Proof of delivery
            "pod_signature": shipment.pod_signature,
            "pod_photo": shipment.pod_photo,
            "delivered_to": shipment.delivered_to,
        },
        "tracking_events": tracking_events,
    }


@frappe.whitelist(allow_guest=False)
def get_seller_shipments(
    status: Optional[str] = None,
    carrier: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get shipments for the current seller.

    Args:
        status: Filter by status (optional)
        carrier: Filter by carrier (optional)
        from_date: Filter from date (optional)
        to_date: Filter to date (optional)
        page: Page number (default: 1)
        page_size: Items per page (default: 20)

    Returns:
        dict: List of shipments with pagination
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to view shipments"))

    filters = {"seller": seller}

    if status:
        filters["status"] = status
    if carrier:
        filters["carrier"] = _normalize_carrier_name(carrier)
    if from_date:
        filters["created_at"] = [">=", getdate(from_date)]
    if to_date:
        if "created_at" in filters:
            filters["created_at"] = ["between", [getdate(from_date), getdate(to_date)]]
        else:
            filters["created_at"] = ["<=", getdate(to_date)]

    # Count total
    total = frappe.db.count("Marketplace Shipment", filters)

    # Get shipments
    shipments = frappe.get_all(
        "Marketplace Shipment",
        filters=filters,
        fields=[
            "name", "shipment_id", "status", "carrier", "tracking_number",
            "sub_order", "marketplace_order", "recipient_name", "destination_city",
            "shipped_at", "delivered_at", "estimated_delivery_date", "creation",
        ],
        order_by="creation desc",
        start=(page - 1) * page_size,
        limit=page_size,
    )

    return {
        "success": True,
        "shipments": shipments,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@frappe.whitelist(allow_guest=False)
def update_shipment_status(
    shipment_name: str,
    status: str,
    tracking_number: Optional[str] = None,
    tracking_url: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update shipment status.

    Args:
        shipment_name: Shipment name
        status: New status
        tracking_number: Tracking number (optional)
        tracking_url: Tracking URL (optional)
        notes: Status change notes (optional)

    Returns:
        dict: Updated shipment details
    """
    check_rate_limit("shipment_update")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    seller = get_current_seller()
    if seller and shipment.seller != seller:
        frappe.throw(_("You don't have permission to update this shipment"))

    # Validate status
    if status not in SHIPMENT_STATUSES:
        frappe.throw(_("Invalid status: {0}").format(status))

    old_status = shipment.status

    try:
        # Update shipment
        shipment.status = status

        if tracking_number:
            shipment.tracking_number = tracking_number
        if tracking_url:
            shipment.tracking_url = tracking_url
        if notes:
            shipment.status_notes = notes

        # Update timestamps
        if status == "Picked Up" and not shipment.shipped_at:
            shipment.shipped_at = now_datetime()
        elif status == "Delivered" and not shipment.delivered_at:
            shipment.delivered_at = now_datetime()

        shipment.save()

        # Log event
        _log_shipping_event(
            event_type="Shipment Status Updated",
            shipment_name=shipment.name,
            sub_order_name=shipment.sub_order,
            details={
                "old_status": old_status,
                "new_status": status,
                "tracking_number": tracking_number,
            },
        )

        return {
            "success": True,
            "message": _("Shipment status updated"),
            "shipment": {
                "name": shipment.name,
                "shipment_id": shipment.shipment_id,
                "status": shipment.status,
                "tracking_number": shipment.tracking_number,
            },
        }

    except Exception as e:
        frappe.log_error(f"Shipment update error: {str(e)}", "Shipping API")
        frappe.throw(_("Error updating shipment"))


@frappe.whitelist(allow_guest=False)
def cancel_shipment(
    shipment_name: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cancel a shipment.

    Args:
        shipment_name: Shipment name
        reason: Cancellation reason (optional)

    Returns:
        dict: Cancellation result
    """
    check_rate_limit("shipment_update")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    seller = get_current_seller()
    if seller and shipment.seller != seller:
        frappe.throw(_("You don't have permission to cancel this shipment"))

    # Check if can be cancelled
    if shipment.status in ["Delivered", "Returned", "Cancelled"]:
        frappe.throw(_("Cannot cancel shipment with status: {0}").format(shipment.status))

    old_status = shipment.status

    try:
        # If shipment has carrier tracking, try to cancel with carrier
        carrier_cancelled = False
        if shipment.tracking_number and shipment.carrier in TURKISH_CARRIERS_WITH_API:
            try:
                from tr_tradehub.integrations.carriers import cancel_shipment as carrier_cancel
                result = carrier_cancel(
                    carrier_type=shipment.carrier,
                    tracking_number=shipment.tracking_number,
                    reason=reason,
                )
                carrier_cancelled = result.get("success", False)
            except Exception as e:
                frappe.log_error(
                    f"Carrier cancellation error: {str(e)}",
                    "Shipping API"
                )

        # Update shipment status
        shipment.status = "Cancelled"
        shipment.cancellation_reason = reason
        shipment.cancelled_at = now_datetime()
        shipment.save()

        # Log event
        _log_shipping_event(
            event_type="Shipment Cancelled",
            shipment_name=shipment.name,
            sub_order_name=shipment.sub_order,
            details={
                "old_status": old_status,
                "reason": reason,
                "carrier_cancelled": carrier_cancelled,
            },
        )

        return {
            "success": True,
            "message": _("Shipment cancelled successfully"),
            "shipment": {
                "name": shipment.name,
                "status": shipment.status,
            },
            "carrier_cancelled": carrier_cancelled,
        }

    except Exception as e:
        frappe.log_error(f"Shipment cancellation error: {str(e)}", "Shipping API")
        frappe.throw(_("Error cancelling shipment"))


# =============================================================================
# TRACKING ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def track_shipment(
    tracking_number: Optional[str] = None,
    shipment_id: Optional[str] = None,
    carrier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Track a shipment by tracking number or shipment ID.

    Args:
        tracking_number: Carrier tracking number
        shipment_id: Marketplace shipment ID
        carrier: Carrier name (required if tracking_number provided without shipment_id)

    Returns:
        dict: Tracking information with events
    """
    check_rate_limit("tracking_query")

    shipment = None

    # Find shipment
    if shipment_id:
        shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": shipment_id},
            "name"
        )
        if shipment_name:
            shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    elif tracking_number:
        shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"tracking_number": tracking_number},
            "name"
        )
        if shipment_name:
            shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    if not shipment and not tracking_number:
        frappe.throw(_("Please provide tracking number or shipment ID"))

    # Get tracking events from database
    events = []
    if shipment:
        events = frappe.get_all(
            "Tracking Event",
            filters={"shipment": shipment.name},
            fields=[
                "event_type", "event_description", "event_timestamp",
                "location_city", "location_state", "location_country",
                "facility_name", "is_milestone", "severity",
            ],
            order_by="event_timestamp desc",
        )

    # If carrier API is available, try to get real-time updates
    carrier_name = carrier or (shipment.carrier if shipment else None)
    carrier_tracking = None

    if tracking_number and carrier_name:
        normalized_carrier = _normalize_carrier_name(carrier_name)
        if normalized_carrier in TURKISH_CARRIERS_WITH_API:
            try:
                from tr_tradehub.integrations.carriers import track_shipment as carrier_track
                carrier_tracking = carrier_track(
                    carrier_type=normalized_carrier,
                    tracking_number=tracking_number,
                )
            except Exception as e:
                frappe.log_error(
                    f"Carrier tracking error: {str(e)}",
                    "Shipping API"
                )

    # Build response
    response = {
        "success": True,
        "tracking_number": tracking_number or (shipment.tracking_number if shipment else None),
        "carrier": carrier_name,
    }

    if shipment:
        response["shipment"] = {
            "shipment_id": shipment.shipment_id,
            "status": shipment.status,
            "tracking_url": shipment.tracking_url,
            "destination_city": shipment.destination_city,
            "shipped_at": shipment.shipped_at,
            "delivered_at": shipment.delivered_at,
            "estimated_delivery_date": shipment.estimated_delivery_date,
        }

    response["events"] = events
    response["carrier_tracking"] = carrier_tracking

    return response


@frappe.whitelist(allow_guest=False)
def get_tracking_timeline(shipment_name: str) -> Dict[str, Any]:
    """
    Get detailed tracking timeline for a shipment.

    Args:
        shipment_name: Shipment name or shipment_id

    Returns:
        dict: Tracking timeline with milestones
    """
    check_rate_limit("tracking_query")

    # Find shipment
    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": shipment_name},
            "name"
        )
        if not shipment_name:
            frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Get all tracking events
    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment.name},
        fields=[
            "name", "event_type", "event_description", "event_timestamp",
            "location_city", "location_state", "location_country", "facility_name",
            "is_milestone", "is_exception", "severity", "carrier_event_code",
            "latitude", "longitude",
        ],
        order_by="event_timestamp asc",
    )

    # Identify milestones
    milestones = [e for e in events if e.get("is_milestone")]

    # Calculate delivery progress
    progress_stages = [
        {"stage": "Created", "completed": True},
        {"stage": "Picked Up", "completed": shipment.status not in ["Pending", "Label Generated", "Pickup Scheduled"]},
        {"stage": "In Transit", "completed": shipment.status in ["In Transit", "Out for Delivery", "Delivered", "Failed Delivery"]},
        {"stage": "Out for Delivery", "completed": shipment.status in ["Out for Delivery", "Delivered"]},
        {"stage": "Delivered", "completed": shipment.status == "Delivered"},
    ]

    return {
        "success": True,
        "shipment": {
            "name": shipment.name,
            "shipment_id": shipment.shipment_id,
            "status": shipment.status,
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
        },
        "timeline": events,
        "milestones": milestones,
        "progress": progress_stages,
        "summary": {
            "total_events": len(events),
            "exceptions": len([e for e in events if e.get("is_exception")]),
            "first_event": events[0] if events else None,
            "latest_event": events[-1] if events else None,
        },
    }


@frappe.whitelist(allow_guest=False)
def refresh_tracking(shipment_name: str) -> Dict[str, Any]:
    """
    Refresh tracking information from carrier API.

    Args:
        shipment_name: Shipment name

    Returns:
        dict: Updated tracking information
    """
    check_rate_limit("tracking_query")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    if not shipment.tracking_number:
        frappe.throw(_("Shipment has no tracking number"))

    carrier = _normalize_carrier_name(shipment.carrier)
    if carrier not in TURKISH_CARRIERS_WITH_API:
        frappe.throw(_("Real-time tracking not available for this carrier"))

    try:
        from tr_tradehub.integrations.carriers import track_shipment as carrier_track
        from tr_tradehub.doctype.tracking_event.tracking_event import process_carrier_events

        # Get tracking from carrier
        result = carrier_track(
            carrier_type=carrier,
            tracking_number=shipment.tracking_number,
        )

        # Process and store events
        if result.get("success") and result.get("events"):
            new_events_count = process_carrier_events(
                shipment=shipment.name,
                carrier=carrier,
                events=result["events"],
            )

            return {
                "success": True,
                "message": _("Tracking refreshed successfully"),
                "new_events": new_events_count,
                "carrier_response": result,
            }

        return {
            "success": True,
            "message": _("No new tracking events"),
            "new_events": 0,
        }

    except Exception as e:
        frappe.log_error(f"Tracking refresh error: {str(e)}", "Shipping API")
        frappe.throw(_("Error refreshing tracking information"))


# =============================================================================
# CARRIER INTEGRATION ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def create_carrier_shipment(
    shipment_name: str,
    generate_label: bool = True,
) -> Dict[str, Any]:
    """
    Create shipment with carrier and get tracking number.

    Args:
        shipment_name: Marketplace Shipment name
        generate_label: Whether to generate shipping label

    Returns:
        dict: Carrier shipment details with tracking number
    """
    check_rate_limit("shipment_create")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    seller = get_current_seller()
    if seller and shipment.seller != seller:
        frappe.throw(_("You don't have permission to process this shipment"))

    # Validate shipment state
    if shipment.tracking_number:
        frappe.throw(_("Shipment already has a tracking number"))

    carrier = _normalize_carrier_name(shipment.carrier)
    if carrier not in TURKISH_CARRIERS_WITH_API:
        frappe.throw(_("Carrier API integration not available for: {0}").format(carrier))

    try:
        from tr_tradehub.integrations.carriers import create_shipment as carrier_create

        # Prepare sender info
        sender_info = {
            "name": shipment.sender_name,
            "phone": shipment.sender_phone,
            "email": shipment.sender_email,
            "address_line1": shipment.origin_address_line1,
            "address_line2": shipment.origin_address_line2,
            "city": shipment.origin_city,
            "state": shipment.origin_state,
            "postal_code": shipment.origin_postal_code,
            "country": shipment.origin_country or "Turkey",
        }

        # Prepare receiver info
        receiver_info = {
            "name": shipment.recipient_name,
            "phone": shipment.recipient_phone,
            "email": shipment.recipient_email,
            "address_line1": shipment.destination_address_line1,
            "address_line2": shipment.destination_address_line2,
            "city": shipment.destination_city,
            "state": shipment.destination_state,
            "postal_code": shipment.destination_postal_code,
            "country": shipment.destination_country or "Turkey",
        }

        # Prepare package info
        package_info = {
            "count": cint(shipment.package_count) or 1,
            "weight": flt(shipment.total_weight),
            "length": flt(shipment.total_length),
            "width": flt(shipment.total_width),
            "height": flt(shipment.total_height),
        }

        # Create shipment with carrier
        result = carrier_create(
            carrier_type=carrier,
            shipment=shipment.name,
            sender_info=sender_info,
            receiver_info=receiver_info,
            package_info=package_info,
            is_cod=shipment.is_cod,
            cod_amount=flt(shipment.cod_amount) if shipment.is_cod else None,
            declared_value=flt(shipment.declared_value),
            special_instructions=shipment.special_instructions,
        )

        if result.get("success"):
            # Update shipment with tracking info
            shipment.tracking_number = result.get("tracking_number")
            shipment.carrier_shipment_id = result.get("carrier_shipment_id")
            shipment.status = "Label Generated"

            # Set tracking URL
            from tr_tradehub.integrations.carriers import get_tracking_url
            shipment.tracking_url = get_tracking_url(carrier, shipment.tracking_number)

            # Store label URL if available
            if result.get("label_url"):
                shipment.label_url = result.get("label_url")

            shipment.save()

            # Log event
            _log_shipping_event(
                event_type="Carrier Shipment Created",
                shipment_name=shipment.name,
                sub_order_name=shipment.sub_order,
                details={
                    "carrier": carrier,
                    "tracking_number": shipment.tracking_number,
                },
            )

            return {
                "success": True,
                "message": _("Carrier shipment created successfully"),
                "shipment": {
                    "name": shipment.name,
                    "tracking_number": shipment.tracking_number,
                    "tracking_url": shipment.tracking_url,
                    "label_url": shipment.label_url,
                    "status": shipment.status,
                },
            }
        else:
            frappe.throw(result.get("error", _("Failed to create carrier shipment")))

    except Exception as e:
        frappe.log_error(f"Carrier shipment creation error: {str(e)}", "Shipping API")
        frappe.throw(_("Error creating carrier shipment"))


@frappe.whitelist(allow_guest=False)
def schedule_pickup(
    shipment_name: str,
    pickup_date: str,
    pickup_time_from: Optional[str] = None,
    pickup_time_to: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Schedule carrier pickup for a shipment.

    Args:
        shipment_name: Shipment name
        pickup_date: Pickup date (YYYY-MM-DD)
        pickup_time_from: Pickup time window start (HH:MM)
        pickup_time_to: Pickup time window end (HH:MM)
        notes: Special instructions for pickup

    Returns:
        dict: Pickup scheduling result
    """
    check_rate_limit("pickup_schedule")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    seller = get_current_seller()
    if seller and shipment.seller != seller:
        frappe.throw(_("You don't have permission to schedule pickup for this shipment"))

    # Validate shipment state
    if not shipment.tracking_number:
        frappe.throw(_("Shipment must have tracking number before scheduling pickup"))

    if shipment.status in ["Picked Up", "In Transit", "Delivered", "Cancelled"]:
        frappe.throw(_("Cannot schedule pickup for shipment with status: {0}").format(shipment.status))

    # Validate pickup date
    pickup_date = getdate(pickup_date)
    if pickup_date < getdate(nowdate()):
        frappe.throw(_("Pickup date cannot be in the past"))

    carrier = _normalize_carrier_name(shipment.carrier)

    try:
        # If carrier API available, schedule through carrier
        carrier_result = None
        if carrier in TURKISH_CARRIERS_WITH_API:
            try:
                from tr_tradehub.integrations.carriers import yurtici_schedule_pickup, aras_schedule_pickup

                pickup_info = {
                    "tracking_number": shipment.tracking_number,
                    "pickup_date": str(pickup_date),
                    "pickup_time_from": pickup_time_from,
                    "pickup_time_to": pickup_time_to,
                    "address": {
                        "address_line1": shipment.origin_address_line1,
                        "city": shipment.origin_city,
                        "postal_code": shipment.origin_postal_code,
                    },
                    "contact_name": shipment.sender_name,
                    "contact_phone": shipment.sender_phone,
                    "notes": notes,
                }

                if carrier == "Yurtici Kargo":
                    carrier_result = yurtici_schedule_pickup(**pickup_info)
                elif carrier == "Aras Kargo":
                    carrier_result = aras_schedule_pickup(**pickup_info)

            except Exception as e:
                frappe.log_error(f"Carrier pickup scheduling error: {str(e)}", "Shipping API")

        # Update shipment
        shipment.status = "Pickup Scheduled"
        shipment.pickup_date = pickup_date
        shipment.pickup_time_from = pickup_time_from
        shipment.pickup_time_to = pickup_time_to
        shipment.pickup_notes = notes

        if carrier_result and carrier_result.get("success"):
            shipment.pickup_confirmation_number = carrier_result.get("confirmation_number")

        shipment.save()

        # Log event
        _log_shipping_event(
            event_type="Pickup Scheduled",
            shipment_name=shipment.name,
            sub_order_name=shipment.sub_order,
            details={
                "pickup_date": str(pickup_date),
                "pickup_time": f"{pickup_time_from} - {pickup_time_to}",
            },
        )

        return {
            "success": True,
            "message": _("Pickup scheduled successfully"),
            "shipment": {
                "name": shipment.name,
                "status": shipment.status,
                "pickup_date": str(shipment.pickup_date),
                "pickup_confirmation_number": shipment.pickup_confirmation_number,
            },
            "carrier_result": carrier_result,
        }

    except Exception as e:
        frappe.log_error(f"Pickup scheduling error: {str(e)}", "Shipping API")
        frappe.throw(_("Error scheduling pickup"))


@frappe.whitelist(allow_guest=False)
def print_label(shipment_name: str) -> Dict[str, Any]:
    """
    Get shipping label for printing.

    Args:
        shipment_name: Shipment name

    Returns:
        dict: Label URL or PDF data
    """
    check_rate_limit("label_print")

    if not frappe.db.exists("Marketplace Shipment", shipment_name):
        frappe.throw(_("Shipment not found"))

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Check permission
    seller = get_current_seller()
    if seller and shipment.seller != seller:
        frappe.throw(_("You don't have permission to print label for this shipment"))

    if not shipment.tracking_number:
        frappe.throw(_("Shipment must have tracking number to print label"))

    # Return existing label URL if available
    if shipment.label_url:
        return {
            "success": True,
            "label_url": shipment.label_url,
            "tracking_number": shipment.tracking_number,
        }

    # Try to get label from carrier
    carrier = _normalize_carrier_name(shipment.carrier)
    if carrier in TURKISH_CARRIERS_WITH_API:
        try:
            from tr_tradehub.integrations.carriers import get_carrier_client
            client = get_carrier_client(carrier)
            label_result = client.get_label(shipment.tracking_number)

            if label_result.get("success") and label_result.get("label_url"):
                shipment.label_url = label_result["label_url"]
                shipment.save()

                return {
                    "success": True,
                    "label_url": shipment.label_url,
                    "tracking_number": shipment.tracking_number,
                }
        except Exception as e:
            frappe.log_error(f"Label retrieval error: {str(e)}", "Shipping API")

    frappe.throw(_("Shipping label not available"))


# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True, methods=["POST"])
def yurtici_webhook() -> Dict[str, Any]:
    """
    Handle Yurtici Kargo webhook callbacks.

    Returns:
        dict: Webhook processing result
    """
    check_rate_limit("webhook", identifier="yurtici")

    try:
        from tr_tradehub.integrations.carriers import yurtici_verify_webhook

        # Get request data
        data = frappe.request.get_data(as_text=True)
        headers = dict(frappe.request.headers)

        # Verify webhook signature
        if not yurtici_verify_webhook(data, headers):
            frappe.throw(_("Invalid webhook signature"), exc=frappe.AuthenticationError)

        # Parse webhook data
        payload = json.loads(data)

        # Process tracking update
        tracking_number = payload.get("tracking_number") or payload.get("kargo_takip_no")
        if tracking_number:
            _process_carrier_webhook(
                carrier="Yurtici Kargo",
                tracking_number=tracking_number,
                payload=payload,
            )

        return {"success": True, "message": "Webhook processed"}

    except Exception as e:
        frappe.log_error(f"Yurtici webhook error: {str(e)}", "Shipping Webhook")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def aras_webhook() -> Dict[str, Any]:
    """
    Handle Aras Kargo webhook callbacks.

    Returns:
        dict: Webhook processing result
    """
    check_rate_limit("webhook", identifier="aras")

    try:
        from tr_tradehub.integrations.carriers import aras_verify_callback

        # Get request data
        data = frappe.request.get_data(as_text=True)
        headers = dict(frappe.request.headers)

        # Verify callback signature
        if not aras_verify_callback(data, headers):
            frappe.throw(_("Invalid callback signature"), exc=frappe.AuthenticationError)

        # Parse callback data
        payload = json.loads(data)

        # Process tracking update
        tracking_number = payload.get("tracking_number") or payload.get("kargo_no")
        if tracking_number:
            _process_carrier_webhook(
                carrier="Aras Kargo",
                tracking_number=tracking_number,
                payload=payload,
            )

        return {"success": True, "message": "Callback processed"}

    except Exception as e:
        frappe.log_error(f"Aras webhook error: {str(e)}", "Shipping Webhook")
        return {"success": False, "error": str(e)}


def _process_carrier_webhook(
    carrier: str,
    tracking_number: str,
    payload: Dict[str, Any],
) -> None:
    """Process carrier webhook/callback data."""
    # Find shipment
    shipment_name = frappe.db.get_value(
        "Marketplace Shipment",
        {"tracking_number": tracking_number},
        "name"
    )

    if not shipment_name:
        frappe.log_error(
            f"Shipment not found for tracking number: {tracking_number}",
            "Shipping Webhook"
        )
        return

    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    # Extract event data from payload
    event_type = payload.get("event_type") or payload.get("durum")
    event_description = payload.get("description") or payload.get("aciklama")
    event_timestamp = payload.get("timestamp") or payload.get("tarih")
    location = payload.get("location") or payload.get("konum")

    # Create tracking event
    try:
        tracking_event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": shipment.name,
            "tracking_number": tracking_number,
            "carrier": carrier,
            "event_type": _map_carrier_event_type(carrier, event_type),
            "event_description": event_description,
            "event_timestamp": event_timestamp,
            "location_city": location.get("city") if isinstance(location, dict) else location,
            "carrier_event_code": event_type,
            "raw_carrier_data": json.dumps(payload),
        })
        tracking_event.insert(ignore_permissions=True)

        # Update shipment status based on event
        _update_shipment_from_event(shipment, tracking_event)

    except Exception as e:
        frappe.log_error(f"Tracking event creation error: {str(e)}", "Shipping Webhook")


def _map_carrier_event_type(carrier: str, carrier_code: str) -> str:
    """Map carrier-specific event codes to standard event types."""
    # Standard event type mappings
    event_mappings = {
        "Yurtici Kargo": {
            "1": "Shipment Created",
            "2": "Pickup Completed",
            "3": "In Transit",
            "4": "Arrived at Facility",
            "5": "Out for Delivery",
            "6": "Delivered",
            "7": "Failed Delivery",
            "8": "Returned to Sender",
        },
        "Aras Kargo": {
            "CREATED": "Shipment Created",
            "PICKED_UP": "Pickup Completed",
            "IN_TRANSIT": "In Transit",
            "OUT_FOR_DELIVERY": "Out for Delivery",
            "DELIVERED": "Delivered",
            "FAILED": "Failed Delivery",
            "RETURNED": "Returned to Sender",
        },
    }

    carrier_map = event_mappings.get(carrier, {})
    return carrier_map.get(str(carrier_code), "Status Update")


def _update_shipment_from_event(shipment, event) -> None:
    """Update shipment status based on tracking event."""
    status_map = {
        "Shipment Created": "Label Generated",
        "Pickup Completed": "Picked Up",
        "Departed Origin Facility": "In Transit",
        "In Transit": "In Transit",
        "Arrived at Facility": "In Transit",
        "Arrived at Destination City": "In Transit",
        "Out for Delivery": "Out for Delivery",
        "Delivered": "Delivered",
        "Signed For": "Delivered",
        "Failed Delivery": "Failed Delivery",
        "Delivery Exception": "Exception",
        "Returned to Sender": "Returned",
    }

    new_status = status_map.get(event.event_type)
    if new_status and new_status != shipment.status:
        # Validate status transition (don't go backwards)
        status_order = [
            "Pending", "Label Generated", "Pickup Scheduled", "Picked Up",
            "In Transit", "Out for Delivery", "Delivered"
        ]

        try:
            current_idx = status_order.index(shipment.status)
            new_idx = status_order.index(new_status)

            if new_idx >= current_idx:
                shipment.status = new_status

                # Update timestamps
                if new_status == "Picked Up":
                    shipment.shipped_at = event.event_timestamp or now_datetime()
                elif new_status == "Delivered":
                    shipment.delivered_at = event.event_timestamp or now_datetime()

                shipment.save(ignore_permissions=True)
        except ValueError:
            # Status not in standard order (exception, returned, etc.)
            if new_status in ["Exception", "Failed Delivery", "Returned"]:
                shipment.status = new_status
                shipment.save(ignore_permissions=True)


# =============================================================================
# STATISTICS ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def get_shipping_statistics(
    seller: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get shipping statistics and analytics.

    Args:
        seller: Seller profile name (optional, uses current seller if not provided)
        from_date: Statistics from date (optional)
        to_date: Statistics to date (optional)

    Returns:
        dict: Shipping statistics
    """
    # Get seller filter
    if not seller:
        seller = get_current_seller()

    filters = {}
    if seller:
        filters["seller"] = seller

    # Date filters
    if from_date or to_date:
        if from_date and to_date:
            filters["creation"] = ["between", [getdate(from_date), getdate(to_date)]]
        elif from_date:
            filters["creation"] = [">=", getdate(from_date)]
        else:
            filters["creation"] = ["<=", getdate(to_date)]

    # Get shipment counts by status
    status_counts = {}
    for status in SHIPMENT_STATUSES:
        status_filters = filters.copy()
        status_filters["status"] = status
        status_counts[status] = frappe.db.count("Marketplace Shipment", status_filters)

    # Use parameterized queries to prevent SQL injection
    params = {}
    seller_filter = ""
    date_filter = ""
    if seller:
        seller_filter = "AND seller = %(seller)s"
        params["seller"] = seller
    if from_date:
        date_filter = "AND creation >= %(from_date)s"
        params["from_date"] = from_date

    # Get carrier breakdown
    carrier_counts = frappe.db.sql("""
        SELECT carrier, COUNT(*) as count
        FROM `tabMarketplace Shipment`
        WHERE 1=1
        {seller_filter}
        {date_filter}
        GROUP BY carrier
        ORDER BY count DESC
    """.format(
        seller_filter=seller_filter,
        date_filter=date_filter,
    ), params, as_dict=True)

    # Get delivery performance
    delivery_stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_delivered,
            AVG(DATEDIFF(delivered_at, shipped_at)) as avg_delivery_days,
            SUM(CASE WHEN delivered_at <= estimated_delivery_date THEN 1 ELSE 0 END) as on_time_deliveries
        FROM `tabMarketplace Shipment`
        WHERE status = 'Delivered'
        AND delivered_at IS NOT NULL
        AND shipped_at IS NOT NULL
        {seller_filter}
        {date_filter}
    """.format(
        seller_filter=seller_filter,
        date_filter=date_filter,
    ), params, as_dict=True)[0]

    # Calculate on-time rate
    on_time_rate = 0
    if delivery_stats.total_delivered:
        on_time_rate = (
            (delivery_stats.on_time_deliveries or 0) / delivery_stats.total_delivered
        ) * 100

    # Get cost statistics
    cost_stats = frappe.db.sql("""
        SELECT
            SUM(shipping_cost) as total_shipping_cost,
            AVG(shipping_cost) as avg_shipping_cost,
            SUM(total_cost) as total_cost
        FROM `tabMarketplace Shipment`
        WHERE status != 'Cancelled'
        {seller_filter}
        {date_filter}
    """.format(
        seller_filter=seller_filter,
        date_filter=date_filter,
    ), params, as_dict=True)[0]

    return {
        "success": True,
        "statistics": {
            "by_status": status_counts,
            "by_carrier": carrier_counts,
            "delivery_performance": {
                "total_delivered": cint(delivery_stats.total_delivered),
                "avg_delivery_days": round(flt(delivery_stats.avg_delivery_days), 1),
                "on_time_deliveries": cint(delivery_stats.on_time_deliveries),
                "on_time_rate": round(on_time_rate, 1),
            },
            "costs": {
                "total_shipping_cost": flt(cost_stats.total_shipping_cost),
                "avg_shipping_cost": round(flt(cost_stats.avg_shipping_cost), 2),
                "total_cost": flt(cost_stats.total_cost),
            },
            "totals": {
                "total_shipments": sum(status_counts.values()),
                "active_shipments": sum(
                    status_counts.get(s, 0)
                    for s in ["Pending", "Label Generated", "Pickup Scheduled", "Picked Up", "In Transit", "Out for Delivery"]
                ),
                "delivered": status_counts.get("Delivered", 0),
                "cancelled": status_counts.get("Cancelled", 0),
                "exceptions": status_counts.get("Exception", 0),
            },
        },
        "filters": {
            "seller": seller,
            "from_date": str(from_date) if from_date else None,
            "to_date": str(to_date) if to_date else None,
        },
    }


@frappe.whitelist(allow_guest=False)
def get_carrier_list() -> Dict[str, Any]:
    """
    Get list of available carriers with their capabilities.

    Returns:
        dict: List of carriers with features
    """
    carriers = []

    for carrier in SUPPORTED_CARRIERS:
        has_api = carrier in TURKISH_CARRIERS_WITH_API
        carriers.append({
            "name": carrier,
            "has_api_integration": has_api,
            "features": {
                "create_shipment": has_api,
                "real_time_tracking": has_api,
                "schedule_pickup": has_api,
                "cancel_shipment": has_api,
                "get_label": has_api,
            },
            "tracking_url_template": _get_tracking_url_template(carrier),
        })

    return {
        "success": True,
        "carriers": carriers,
        "turkish_carriers": [c for c in carriers if c["name"] in SUPPORTED_CARRIERS[:7]],
        "international_carriers": [c for c in carriers if c["name"] in SUPPORTED_CARRIERS[7:]],
    }


def _get_tracking_url_template(carrier: str) -> str:
    """Get tracking URL template for a carrier."""
    templates = {
        "Yurtici Kargo": "https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={tracking_number}",
        "Aras Kargo": "https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={tracking_number}",
        "MNG Kargo": "https://www.mngkargo.com.tr/gonderi-takip/?no={tracking_number}",
        "PTT Kargo": "https://gonderitakip.ptt.gov.tr/?barkod={tracking_number}",
        "SuratKargo": "https://www.suratkargo.com.tr/gonderi-takip?takipNo={tracking_number}",
        "Trendyol Express": "https://www.trendyol.com/kargo-takip/{tracking_number}",
        "HepsiJet": "https://www.hepsijet.com/takip/{tracking_number}",
        "UPS": "https://www.ups.com/track?tracknum={tracking_number}",
        "DHL": "https://www.dhl.com/tr-en/home/tracking.html?tracking-id={tracking_number}",
        "FedEx": "https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
    }
    return templates.get(carrier, "")


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    # Rate calculation
    "calculate_shipping_rates",
    "get_shipping_rules",
    "get_shipping_rule",
    # Shipment management
    "create_shipment",
    "get_shipment",
    "get_seller_shipments",
    "update_shipment_status",
    "cancel_shipment",
    # Tracking
    "track_shipment",
    "get_tracking_timeline",
    "refresh_tracking",
    # Carrier integration
    "create_carrier_shipment",
    "schedule_pickup",
    "print_label",
    # Webhooks
    "yurtici_webhook",
    "aras_webhook",
    # Statistics
    "get_shipping_statistics",
    "get_carrier_list",
]
