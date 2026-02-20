# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Google Analytics 4 Measurement Protocol Integration

This module provides GA4 event tracking for key e-commerce actions:
- view_item: When a user views a product
- add_to_cart: When a user adds a product to cart
- purchase: When an order is completed

Configuration:
    GA4 credentials should be stored in site_config.json:
    - ga4_measurement_id: GA4 Measurement ID (format: G-XXXXXXXX)
    - ga4_api_secret: GA4 API secret from Data Streams settings

Usage:
    from tr_tradehub.utils.ga4_analytics import (
        track_add_to_cart,
        track_view_item,
        track_purchase
    )
"""

import frappe
from frappe import _
from frappe.utils import flt, cstr
import hashlib


def get_ga4_config():
    """
    Get GA4 configuration from site_config.json.

    Returns:
        dict: GA4 configuration with measurement_id and api_secret
              Returns None if not configured
    """
    config = frappe.conf

    measurement_id = config.get("ga4_measurement_id")
    api_secret = config.get("ga4_api_secret")

    if not measurement_id or not api_secret:
        return None

    return {
        "measurement_id": measurement_id,
        "api_secret": api_secret
    }


def get_ga4_client():
    """
    Get GA4 Measurement Protocol client.

    Returns:
        Ga4mp: GA4 client instance or None if not configured
    """
    config = get_ga4_config()
    if not config:
        return None

    try:
        from ga4mp import Ga4mp
        return Ga4mp(
            measurement_id=config["measurement_id"],
            api_secret=config["api_secret"]
        )
    except ImportError:
        frappe.log_error(
            title=_("GA4 Package Not Installed"),
            message=_("ga4-measurement-protocol-python package is not installed. "
                      "Install with: pip install ga4-measurement-protocol-python")
        )
        return None
    except Exception as e:
        frappe.log_error(
            title=_("GA4 Client Error"),
            message=str(e)
        )
        return None


def get_client_id(user=None):
    """
    Generate a client_id for GA4 tracking.

    For logged-in users, generates a hash of the user email.
    For anonymous users, uses session ID or generates a random ID.

    Args:
        user: User email (optional, defaults to current session user)

    Returns:
        str: Client ID for GA4 tracking
    """
    if not user:
        user = frappe.session.user

    if user and user != "Guest":
        # Hash user email for privacy
        return hashlib.sha256(user.encode()).hexdigest()[:32]

    # For guests, use session ID if available
    if hasattr(frappe.local, "session") and frappe.local.session.get("sid"):
        return hashlib.sha256(frappe.local.session.sid.encode()).hexdigest()[:32]

    # Fallback: generate random ID
    import uuid
    return str(uuid.uuid4()).replace("-", "")[:32]


def format_ga4_item(listing_data, qty=1, variant=None):
    """
    Format a listing item for GA4 e-commerce events.

    Args:
        listing_data: dict with listing information (name, title, price, etc.)
        qty: Quantity (default 1)
        variant: Variant information (optional)

    Returns:
        dict: GA4 item format
    """
    item = {
        "item_id": cstr(listing_data.get("name") or listing_data.get("listing")),
        "item_name": cstr(listing_data.get("title") or listing_data.get("listing_title", "")),
        "price": flt(listing_data.get("selling_price") or listing_data.get("unit_price", 0)),
        "quantity": int(flt(qty))
    }

    # Add category if available
    category = listing_data.get("category") or listing_data.get("category_name")
    if category:
        item["item_category"] = cstr(category)

    # Add seller/brand as item_brand
    seller = listing_data.get("seller") or listing_data.get("seller_name")
    if seller:
        item["item_brand"] = cstr(seller)

    # Add variant if specified
    if variant:
        item["item_variant"] = cstr(variant)

    # Add SKU if available
    sku = listing_data.get("sku")
    if sku:
        item["sku"] = cstr(sku)

    return item


def send_ga4_event(event_name, params, user=None):
    """
    Send an event to GA4 via Measurement Protocol.

    This function handles errors gracefully and logs failures
    without interrupting the main application flow.

    Args:
        event_name: GA4 event name (e.g., 'add_to_cart', 'purchase')
        params: Event parameters dict
        user: User for client_id generation (optional)

    Returns:
        bool: True if event sent successfully, False otherwise
    """
    try:
        ga4 = get_ga4_client()
        if not ga4:
            return False

        client_id = get_client_id(user)

        # Create event
        event = ga4.create_new_event(name=event_name)

        # Add parameters
        for key, value in params.items():
            if value is not None:
                event.set_event_param(name=key, value=value)

        # Send event
        ga4.send(events=[event], client_id=client_id)

        return True

    except Exception as e:
        frappe.log_error(
            title=_("GA4 Event Error"),
            message=f"Event: {event_name}\nParams: {params}\nError: {str(e)}"
        )
        return False


def track_view_item(listing, user=None, currency="TRY"):
    """
    Track a view_item event when a user views a product.

    GA4 Event: view_item
    Parameters:
        - currency: Currency code (default TRY)
        - value: Item price
        - items: Array with item details

    Args:
        listing: Listing name or dict with listing data
        user: User email (optional)
        currency: Currency code (default TRY)

    Returns:
        bool: True if event sent successfully
    """
    try:
        # Get listing data
        if isinstance(listing, str):
            listing_data = frappe.db.get_value(
                "Listing",
                listing,
                ["name", "title", "selling_price", "category", "seller", "sku"],
                as_dict=True
            )
            if not listing_data:
                return False
        else:
            listing_data = listing

        # Format item
        item = format_ga4_item(listing_data)

        # Build event params
        params = {
            "currency": currency,
            "value": item.get("price", 0),
            "items": [item]
        }

        return send_ga4_event("view_item", params, user)

    except Exception as e:
        frappe.log_error(
            title=_("GA4 view_item Error"),
            message=str(e)
        )
        return False


def track_add_to_cart(listing, qty=1, variant=None, user=None, currency="TRY"):
    """
    Track an add_to_cart event when a user adds a product to cart.

    GA4 Event: add_to_cart
    Parameters:
        - currency: Currency code (default TRY)
        - value: Total value of items added
        - items: Array with item details

    Args:
        listing: Listing name or dict with listing data
        qty: Quantity added
        variant: Variant information (optional)
        user: User email (optional)
        currency: Currency code (default TRY)

    Returns:
        bool: True if event sent successfully
    """
    try:
        # Get listing data
        if isinstance(listing, str):
            listing_data = frappe.db.get_value(
                "Listing",
                listing,
                ["name", "title", "selling_price", "category", "seller", "sku", "currency"],
                as_dict=True
            )
            if not listing_data:
                return False
        else:
            listing_data = listing

        # Use listing currency if available
        if listing_data.get("currency"):
            currency = listing_data.get("currency")

        # Format item
        item = format_ga4_item(listing_data, qty, variant)

        # Calculate total value
        value = flt(item.get("price", 0)) * int(flt(qty))

        # Build event params
        params = {
            "currency": currency,
            "value": value,
            "items": [item]
        }

        return send_ga4_event("add_to_cart", params, user)

    except Exception as e:
        frappe.log_error(
            title=_("GA4 add_to_cart Error"),
            message=str(e)
        )
        return False


def track_purchase(order, user=None):
    """
    Track a purchase event when an order is completed.

    GA4 Event: purchase
    Parameters:
        - transaction_id: Order ID
        - currency: Currency code
        - value: Grand total
        - tax: Total tax amount
        - shipping: Shipping amount
        - coupon: Coupon code (if applied)
        - items: Array with item details

    Args:
        order: Marketplace Order document or order name
        user: User email (optional)

    Returns:
        bool: True if event sent successfully
    """
    try:
        # Get order document
        if isinstance(order, str):
            order = frappe.get_doc("Marketplace Order", order)

        # Format items
        items = []
        for item in order.items:
            ga4_item = format_ga4_item({
                "name": item.listing,
                "title": item.title,
                "selling_price": item.unit_price,
                "category": frappe.db.get_value("Listing", item.listing, "category") if item.listing else None,
                "seller": item.seller,
                "sku": item.sku
            }, item.qty)
            items.append(ga4_item)

        # Build event params
        params = {
            "transaction_id": order.order_id or order.name,
            "currency": order.currency or "TRY",
            "value": flt(order.grand_total),
            "tax": flt(order.tax_amount),
            "shipping": flt(order.shipping_amount),
            "items": items
        }

        # Add coupon if applied
        if order.coupon_code:
            params["coupon"] = order.coupon_code

        # Use order buyer for user if not specified
        if not user:
            user = order.buyer

        return send_ga4_event("purchase", params, user)

    except Exception as e:
        frappe.log_error(
            title=_("GA4 purchase Error"),
            message=str(e)
        )
        return False


@frappe.whitelist(allow_guest=True)
def track_view_item_api(listing, currency="TRY"):
    """
    API endpoint to track view_item event from client-side.

    Args:
        listing: Listing name
        currency: Currency code (default TRY)

    Returns:
        dict: Success status
    """
    success = track_view_item(listing, frappe.session.user, currency)
    return {"success": success}


@frappe.whitelist(allow_guest=True)
def track_add_to_cart_api(listing, qty=1, variant=None, currency="TRY"):
    """
    API endpoint to track add_to_cart event from client-side.

    Args:
        listing: Listing name
        qty: Quantity added
        variant: Variant information (optional)
        currency: Currency code (default TRY)

    Returns:
        dict: Success status
    """
    success = track_add_to_cart(
        listing,
        qty=int(flt(qty)),
        variant=variant,
        user=frappe.session.user,
        currency=currency
    )
    return {"success": success}
