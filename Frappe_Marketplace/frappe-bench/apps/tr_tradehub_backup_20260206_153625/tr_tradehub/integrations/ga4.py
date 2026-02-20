# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Google Analytics 4 Measurement Protocol Integration

This module provides integration with Google Analytics 4 using the Measurement Protocol.
Events are sent directly to GA4 from the server, which is useful for tracking:
- Server-side transactions
- Backend events not triggered by user interaction
- E-commerce events (purchases, add to cart, etc.)

Configuration:
    Add the following to your site_config.json:
    {
        "ga4_measurement_id": "G-XXXXXXXXXX",
        "ga4_api_secret": "your_api_secret",
        "ga4_enabled": true,
        "ga4_debug": false
    }

Dependencies:
    pip install ga4-measurement-protocol-python

Usage:
    from tr_tradehub.integrations.ga4 import send_event, track_purchase

    # Send a custom event
    send_event("custom_event", {"param1": "value1"}, user_id="user123")

    # Track a purchase
    track_purchase(order_doc)
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime

# Event constants for GA4 standard events
EVENT_PURCHASE = "purchase"
EVENT_ADD_TO_CART = "add_to_cart"
EVENT_REMOVE_FROM_CART = "remove_from_cart"
EVENT_VIEW_ITEM = "view_item"
EVENT_VIEW_ITEM_LIST = "view_item_list"
EVENT_BEGIN_CHECKOUT = "begin_checkout"
EVENT_ADD_PAYMENT_INFO = "add_payment_info"
EVENT_ADD_SHIPPING_INFO = "add_shipping_info"
EVENT_LOGIN = "login"
EVENT_SIGN_UP = "sign_up"
EVENT_SEARCH = "search"
EVENT_GENERATE_LEAD = "generate_lead"

# Custom marketplace events
EVENT_SELLER_REGISTRATION = "seller_registration"
EVENT_RFQ_CREATED = "rfq_created"
EVENT_QUOTE_SUBMITTED = "quote_submitted"
EVENT_ORDER_PLACED = "order_placed"
EVENT_ORDER_COMPLETED = "order_completed"
EVENT_REVIEW_SUBMITTED = "review_submitted"
EVENT_SUBSCRIPTION_STARTED = "subscription_started"
EVENT_SUBSCRIPTION_RENEWED = "subscription_renewed"


def _get_ga4_config():
    """
    Get GA4 configuration from site_config.json.

    Returns:
        dict: GA4 configuration with keys:
            - measurement_id: GA4 Measurement ID (G-XXXXXXXXXX)
            - api_secret: GA4 API Secret
            - enabled: Whether GA4 tracking is enabled
            - debug: Whether to use debug endpoint
    """
    return {
        "measurement_id": frappe.conf.get("ga4_measurement_id"),
        "api_secret": frappe.conf.get("ga4_api_secret"),
        "enabled": frappe.conf.get("ga4_enabled", False),
        "debug": frappe.conf.get("ga4_debug", False)
    }


def _get_ga4_client():
    """
    Get GA4 Measurement Protocol client instance.

    Returns:
        Ga4mp instance or None if not configured

    Note:
        Requires ga4-measurement-protocol-python package:
        pip install ga4-measurement-protocol-python
    """
    config = _get_ga4_config()

    if not config.get("enabled"):
        return None

    measurement_id = config.get("measurement_id")
    api_secret = config.get("api_secret")

    if not measurement_id or not api_secret:
        frappe.log_error(
            _("GA4 Measurement ID or API Secret not configured"),
            _("GA4 Integration Error")
        )
        return None

    try:
        from ga4mp import Ga4mp
        return Ga4mp(
            measurement_id=measurement_id,
            api_secret=api_secret
        )
    except ImportError:
        frappe.log_error(
            _("ga4mp package not installed. Run: pip install ga4-measurement-protocol-python"),
            _("GA4 Integration Error")
        )
        return None
    except Exception as e:
        frappe.log_error(
            str(e),
            _("GA4 Client Initialization Error")
        )
        return None


def _generate_client_id(user_id=None):
    """
    Generate a client ID for GA4 tracking.

    Args:
        user_id: Optional user ID to use as base

    Returns:
        str: Client ID in format expected by GA4
    """
    import hashlib
    import time

    if user_id:
        # Generate consistent client ID from user ID
        hash_input = f"{user_id}_{frappe.local.site}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]

    # Generate random client ID
    timestamp = int(time.time())
    random_part = frappe.generate_hash(length=10)
    return f"{timestamp}.{random_part}"


def send_event(event_name, params=None, user_id=None, client_id=None,
               non_personalized_ads=False, timestamp_micros=None):
    """
    Send a custom event to Google Analytics 4.

    This is the main function for sending events to GA4. It handles:
    - Client initialization
    - User/client ID management
    - Error handling and logging
    - Debug mode support

    Args:
        event_name: Name of the event (e.g., "purchase", "custom_event")
        params: Dictionary of event parameters
        user_id: Optional user ID for cross-device tracking
        client_id: Optional client ID (generated if not provided)
        non_personalized_ads: Set to True to disable personalized advertising
        timestamp_micros: Optional event timestamp in microseconds

    Returns:
        dict: Response from GA4 API or error information

    Example:
        send_event("purchase", {
            "transaction_id": "ORD-001",
            "value": 100.00,
            "currency": "TRY",
            "items": [{"item_id": "SKU-001", "item_name": "Product A"}]
        }, user_id="user@example.com")
    """
    if params is None:
        params = {}

    config = _get_ga4_config()

    # Check if GA4 is enabled
    if not config.get("enabled"):
        return {
            "success": False,
            "message": _("GA4 tracking is not enabled"),
            "sent": False
        }

    # Get GA4 client
    ga4_client = _get_ga4_client()
    if not ga4_client:
        return {
            "success": False,
            "message": _("Failed to initialize GA4 client"),
            "sent": False
        }

    try:
        # Generate client ID if not provided
        if not client_id:
            client_id = _generate_client_id(user_id)

        # Build event payload
        event_payload = {
            "name": event_name,
            "params": params
        }

        # Add timestamp if provided
        if timestamp_micros:
            event_payload["timestamp_micros"] = timestamp_micros

        # Create event using GA4MP
        ga4_client.create_new_event(
            name=event_name,
            params=params
        )

        # Store client_id for the request
        ga4_client.client_id = client_id

        # Set user_id if provided
        if user_id:
            ga4_client.user_id = user_id

        # Set non-personalized ads flag
        if non_personalized_ads:
            ga4_client.non_personalized_ads = True

        # Send events (debug mode sends to debug endpoint)
        if config.get("debug"):
            response = ga4_client.send(debug=True)
        else:
            response = ga4_client.send()

        # Log successful send
        if config.get("debug"):
            frappe.logger().info(
                f"GA4 Event Sent: {event_name} - Response: {response}"
            )

        return {
            "success": True,
            "message": _("Event sent successfully"),
            "sent": True,
            "event_name": event_name,
            "response": response
        }

    except Exception as e:
        # Log error but don't raise to avoid disrupting main flow
        frappe.log_error(
            f"Event: {event_name}\nParams: {params}\nError: {str(e)}",
            _("GA4 Event Send Error")
        )
        return {
            "success": False,
            "message": str(e),
            "sent": False,
            "event_name": event_name
        }


def send_event_async(event_name, params=None, user_id=None, client_id=None):
    """
    Send event to GA4 asynchronously via background job.

    Use this for non-critical events where immediate confirmation is not needed.

    Args:
        event_name: Name of the event
        params: Dictionary of event parameters
        user_id: Optional user ID
        client_id: Optional client ID

    Returns:
        str: Job ID of the background task
    """
    job = frappe.enqueue(
        "tr_tradehub.integrations.ga4.send_event",
        event_name=event_name,
        params=params,
        user_id=user_id,
        client_id=client_id,
        queue="short",
        timeout=60
    )
    return job


def track_purchase(order_doc, user_id=None):
    """
    Track a purchase event in GA4.

    Sends the standard "purchase" event with full e-commerce data.

    Args:
        order_doc: Marketplace Order document or dict
        user_id: Optional user ID (uses order buyer if not provided)

    Returns:
        dict: Result from send_event
    """
    if isinstance(order_doc, str):
        order_doc = frappe.get_doc("Marketplace Order", order_doc)

    # Get user ID from order if not provided
    if not user_id:
        user_id = getattr(order_doc, "buyer", None)

    # Build items array
    items = []
    order_items = getattr(order_doc, "items", [])

    for idx, item in enumerate(order_items):
        item_data = {
            "item_id": getattr(item, "sku", "") or getattr(item, "listing", ""),
            "item_name": getattr(item, "item_name", "") or getattr(item, "listing_title", ""),
            "quantity": cint(getattr(item, "qty", 1)),
            "price": flt(getattr(item, "rate", 0)),
            "index": idx
        }

        # Add optional item parameters
        if hasattr(item, "seller"):
            item_data["item_brand"] = item.seller
        if hasattr(item, "category"):
            item_data["item_category"] = item.category

        items.append(item_data)

    # Build event parameters
    params = {
        "transaction_id": order_doc.name,
        "value": flt(getattr(order_doc, "grand_total", 0)),
        "currency": getattr(order_doc, "currency", "TRY"),
        "items": items
    }

    # Add optional parameters
    if hasattr(order_doc, "shipping_amount"):
        params["shipping"] = flt(order_doc.shipping_amount)
    if hasattr(order_doc, "tax_amount"):
        params["tax"] = flt(order_doc.tax_amount)
    if hasattr(order_doc, "coupon"):
        params["coupon"] = order_doc.coupon

    return send_event(EVENT_PURCHASE, params, user_id=user_id)


def track_add_to_cart(cart_item, user_id=None):
    """
    Track add to cart event in GA4.

    Args:
        cart_item: Cart Item document or dict with item details
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    item_data = {
        "item_id": getattr(cart_item, "sku", "") or getattr(cart_item, "listing", ""),
        "item_name": getattr(cart_item, "item_name", "") or getattr(cart_item, "listing_title", ""),
        "quantity": cint(getattr(cart_item, "qty", 1)),
        "price": flt(getattr(cart_item, "rate", 0))
    }

    params = {
        "currency": getattr(cart_item, "currency", "TRY"),
        "value": flt(getattr(cart_item, "amount", 0)),
        "items": [item_data]
    }

    return send_event(EVENT_ADD_TO_CART, params, user_id=user_id)


def track_remove_from_cart(cart_item, user_id=None):
    """
    Track remove from cart event in GA4.

    Args:
        cart_item: Cart Item document or dict with item details
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    item_data = {
        "item_id": getattr(cart_item, "sku", "") or getattr(cart_item, "listing", ""),
        "item_name": getattr(cart_item, "item_name", "") or getattr(cart_item, "listing_title", ""),
        "quantity": cint(getattr(cart_item, "qty", 1)),
        "price": flt(getattr(cart_item, "rate", 0))
    }

    params = {
        "currency": getattr(cart_item, "currency", "TRY"),
        "value": flt(getattr(cart_item, "amount", 0)),
        "items": [item_data]
    }

    return send_event(EVENT_REMOVE_FROM_CART, params, user_id=user_id)


def track_begin_checkout(cart_doc, user_id=None):
    """
    Track begin checkout event in GA4.

    Args:
        cart_doc: Cart document
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(cart_doc, str):
        cart_doc = frappe.get_doc("Cart", cart_doc)

    if not user_id:
        user_id = getattr(cart_doc, "buyer", None)

    # Build items array
    items = []
    cart_items = getattr(cart_doc, "items", [])

    for item in cart_items:
        items.append({
            "item_id": getattr(item, "sku", "") or getattr(item, "listing", ""),
            "item_name": getattr(item, "item_name", "") or getattr(item, "listing_title", ""),
            "quantity": cint(getattr(item, "qty", 1)),
            "price": flt(getattr(item, "rate", 0))
        })

    params = {
        "currency": getattr(cart_doc, "currency", "TRY"),
        "value": flt(getattr(cart_doc, "total", 0)),
        "items": items
    }

    if hasattr(cart_doc, "coupon") and cart_doc.coupon:
        params["coupon"] = cart_doc.coupon

    return send_event(EVENT_BEGIN_CHECKOUT, params, user_id=user_id)


def track_view_item(listing_doc, user_id=None):
    """
    Track view item event in GA4.

    Args:
        listing_doc: Listing document or dict
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(listing_doc, str):
        listing_doc = frappe.get_doc("Listing", listing_doc)

    item_data = {
        "item_id": listing_doc.name,
        "item_name": getattr(listing_doc, "title", ""),
        "price": flt(getattr(listing_doc, "price", 0))
    }

    if hasattr(listing_doc, "seller"):
        item_data["item_brand"] = listing_doc.seller
    if hasattr(listing_doc, "category"):
        item_data["item_category"] = listing_doc.category

    params = {
        "currency": getattr(listing_doc, "currency", "TRY"),
        "value": flt(getattr(listing_doc, "price", 0)),
        "items": [item_data]
    }

    return send_event(EVENT_VIEW_ITEM, params, user_id=user_id)


def track_search(search_term, results_count=None, user_id=None):
    """
    Track search event in GA4.

    Args:
        search_term: The search query string
        results_count: Optional number of results found
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    params = {
        "search_term": search_term
    }

    if results_count is not None:
        params["results_count"] = cint(results_count)

    return send_event(EVENT_SEARCH, params, user_id=user_id)


def track_seller_registration(seller_app_doc, user_id=None):
    """
    Track seller registration event in GA4.

    Args:
        seller_app_doc: Seller Application document
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(seller_app_doc, str):
        seller_app_doc = frappe.get_doc("Seller Application", seller_app_doc)

    if not user_id:
        user_id = getattr(seller_app_doc, "user", None)

    params = {
        "application_id": seller_app_doc.name,
        "business_type": getattr(seller_app_doc, "business_type", ""),
        "seller_type": getattr(seller_app_doc, "seller_type", ""),
        "status": getattr(seller_app_doc, "status", "")
    }

    return send_event(EVENT_SELLER_REGISTRATION, params, user_id=user_id)


def track_rfq_created(rfq_doc, user_id=None):
    """
    Track RFQ creation event in GA4.

    Args:
        rfq_doc: RFQ document
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(rfq_doc, str):
        rfq_doc = frappe.get_doc("RFQ", rfq_doc)

    if not user_id:
        user_id = getattr(rfq_doc, "buyer", None)

    params = {
        "rfq_id": rfq_doc.name,
        "item_count": len(getattr(rfq_doc, "items", [])),
        "category": getattr(rfq_doc, "category", "")
    }

    return send_event(EVENT_RFQ_CREATED, params, user_id=user_id)


def track_subscription(subscription_doc, event_type="started", user_id=None):
    """
    Track subscription events in GA4.

    Args:
        subscription_doc: Subscription document
        event_type: "started" or "renewed"
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(subscription_doc, str):
        subscription_doc = frappe.get_doc("Subscription", subscription_doc)

    if not user_id:
        user_id = getattr(subscription_doc, "subscriber", None)

    event_name = (EVENT_SUBSCRIPTION_STARTED if event_type == "started"
                  else EVENT_SUBSCRIPTION_RENEWED)

    params = {
        "subscription_id": subscription_doc.name,
        "plan": getattr(subscription_doc, "subscription_plan", ""),
        "billing_period": getattr(subscription_doc, "billing_period", ""),
        "value": flt(getattr(subscription_doc, "amount", 0)),
        "currency": getattr(subscription_doc, "currency", "TRY")
    }

    return send_event(event_name, params, user_id=user_id)


def track_review_submitted(review_doc, user_id=None):
    """
    Track review submission event in GA4.

    Args:
        review_doc: Review document
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if isinstance(review_doc, str):
        review_doc = frappe.get_doc("Review", review_doc)

    if not user_id:
        user_id = getattr(review_doc, "reviewer", None)

    params = {
        "review_id": review_doc.name,
        "rating": cint(getattr(review_doc, "rating", 0)),
        "listing": getattr(review_doc, "listing", ""),
        "seller": getattr(review_doc, "seller", ""),
        "review_type": getattr(review_doc, "review_type", "Product")
    }

    return send_event(EVENT_REVIEW_SUBMITTED, params, user_id=user_id)


# ============================================================================
# Doc Event Handlers
# ============================================================================

def on_order_submit(doc, method):
    """
    Hook for tracking order submission in GA4.

    This is called from doc_events when a Marketplace Order is submitted.

    Args:
        doc: Marketplace Order document
        method: The event method name
    """
    try:
        track_purchase(doc)
    except Exception as e:
        # Log error but don't prevent order submission
        frappe.log_error(
            f"Order: {doc.name}\nError: {str(e)}",
            _("GA4 Order Tracking Error")
        )


def on_seller_application_submit(doc, method):
    """
    Hook for tracking seller application submission in GA4.

    Args:
        doc: Seller Application document
        method: The event method name
    """
    try:
        track_seller_registration(doc)
    except Exception as e:
        frappe.log_error(
            f"Application: {doc.name}\nError: {str(e)}",
            _("GA4 Seller Registration Tracking Error")
        )


def on_review_submit(doc, method):
    """
    Hook for tracking review submission in GA4.

    Args:
        doc: Review document
        method: The event method name
    """
    try:
        track_review_submitted(doc)
    except Exception as e:
        frappe.log_error(
            f"Review: {doc.name}\nError: {str(e)}",
            _("GA4 Review Tracking Error")
        )


def on_rfq_submit(doc, method):
    """
    Hook for tracking RFQ submission in GA4.

    Args:
        doc: RFQ document
        method: The event method name
    """
    try:
        track_rfq_created(doc)
    except Exception as e:
        frappe.log_error(
            f"RFQ: {doc.name}\nError: {str(e)}",
            _("GA4 RFQ Tracking Error")
        )


def on_subscription_insert(doc, method):
    """
    Hook for tracking new subscription in GA4.

    Args:
        doc: Subscription document
        method: The event method name
    """
    try:
        track_subscription(doc, event_type="started")
    except Exception as e:
        frappe.log_error(
            f"Subscription: {doc.name}\nError: {str(e)}",
            _("GA4 Subscription Tracking Error")
        )


# ============================================================================
# Whitelist APIs
# ============================================================================

@frappe.whitelist()
def track_event(event_name, params=None, user_id=None):
    """
    Whitelisted API for tracking custom events from client-side.

    Args:
        event_name: Name of the event
        params: JSON string of event parameters
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    import json

    if params and isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {}

    # Use current user if not provided
    if not user_id:
        user_id = frappe.session.user

    return send_event(event_name, params, user_id=user_id)


@frappe.whitelist()
def track_page_view(page_title, page_location=None, user_id=None):
    """
    Track page view event from client-side.

    Args:
        page_title: Title of the page
        page_location: Full URL of the page
        user_id: Optional user ID

    Returns:
        dict: Result from send_event
    """
    if not user_id:
        user_id = frappe.session.user

    params = {
        "page_title": page_title
    }

    if page_location:
        params["page_location"] = page_location

    return send_event("page_view", params, user_id=user_id)


@frappe.whitelist()
def get_ga4_config_status():
    """
    Check GA4 configuration status.

    Returns:
        dict: Configuration status (enabled, configured, etc.)
    """
    config = _get_ga4_config()

    return {
        "enabled": config.get("enabled", False),
        "configured": bool(config.get("measurement_id") and config.get("api_secret")),
        "debug_mode": config.get("debug", False)
    }
