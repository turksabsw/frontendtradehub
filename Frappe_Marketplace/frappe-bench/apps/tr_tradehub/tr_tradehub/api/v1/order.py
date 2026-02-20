# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Order & Checkout API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Cart management (add, update, remove items)
- Checkout flow (start, complete, cancel)
- Order placement and management
- Sub Order tracking for sellers
- Order events and history
- Order statistics and analytics

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.order.<function_name>

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
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "cart_add": {"limit": 60, "window": 60},  # 60 per minute
    "cart_update": {"limit": 60, "window": 60},  # 60 per minute
    "checkout_start": {"limit": 10, "window": 300},  # 10 per 5 min
    "checkout_complete": {"limit": 10, "window": 300},  # 10 per 5 min
    "order_create": {"limit": 10, "window": 300},  # 10 per 5 min
    "order_status_update": {"limit": 30, "window": 300},  # 30 per 5 min
}


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

    cache_key = f"rate_limit:order:{action}:{identifier}"

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


def _log_order_event(
    event_type: str,
    order_name: Optional[str] = None,
    sub_order_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Log order-related events for audit trail."""
    try:
        if not frappe.db.exists("DocType", "Order Event"):
            return

        ip_address = None
        user_agent = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
                user_agent = str(frappe.request.user_agent)[:500]
        except Exception:
            pass

        event_data = {
            "doctype": "Order Event",
            "event_type": event_type,
            "actor": frappe.session.user,
            "actor_type": "Buyer",  # Default, can be overridden
            "ip_address": ip_address,
            "user_agent": user_agent,
            "severity": "Info",
        }

        if order_name:
            event_data["marketplace_order"] = order_name

        if sub_order_name:
            event_data["sub_order"] = sub_order_name

        if details:
            event_data["event_data"] = json.dumps(details)

        frappe.get_doc(event_data).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Order event logging error: {str(e)}", "Order API")


def _validate_shipping_address(address: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate shipping address data.

    Args:
        address: Address dictionary

    Returns:
        dict: Validated address with error info if any
    """
    errors = []

    required_fields = ["address_line1", "city", "postal_code"]
    for field in required_fields:
        if not address.get(field):
            errors.append(_("{0} is required").format(field.replace("_", " ").title()))

    # Validate Turkish postal code format (5 digits)
    postal_code = address.get("postal_code", "")
    if postal_code:
        postal_code = str(postal_code).strip()
        if not postal_code.isdigit() or len(postal_code) != 5:
            errors.append(_("Postal code must be 5 digits"))

    # Validate phone if provided
    phone = address.get("phone", "")
    if phone:
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.replace("+", "").isdigit():
            errors.append(_("Invalid phone number format"))

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "address": {
            "address_line1": address.get("address_line1", "").strip(),
            "address_line2": address.get("address_line2", "").strip() if address.get("address_line2") else None,
            "city": address.get("city", "").strip(),
            "state": address.get("state", "").strip() if address.get("state") else None,
            "postal_code": postal_code,
            "country": address.get("country", "Turkey"),
            "phone": phone if phone else None,
        }
    }


# =============================================================================
# CART ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_cart(
    cart_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get cart details for the current user or session.

    Args:
        cart_id: Cart ID (optional)
        session_id: Session ID for guest users (optional)

    Returns:
        dict: Cart data with items and summary

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_cart
        GET /api/method/tr_tradehub.api.v1.order.get_cart?cart_id=CART-XXXXX
    """
    # Use the Cart DocType API
    from tr_tradehub.tr_tradehub.doctype.cart.cart import get_cart as _get_cart

    result = _get_cart(cart_id=cart_id, session_id=session_id)

    if "error" in result:
        return {
            "success": False,
            "has_cart": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "has_cart": True,
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def get_or_create_cart(session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get existing active cart or create a new one.

    Args:
        session_id: Session ID for guest users (optional)

    Returns:
        dict: Cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.get_or_create_cart
        {"session_id": "guest-session-xxxxx"}
    """
    from tr_tradehub.tr_tradehub.doctype.cart.cart import get_or_create_cart as _get_or_create_cart

    result = _get_or_create_cart(session_id=session_id)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def add_to_cart(
    listing: str,
    qty: int = 1,
    variant: Optional[str] = None,
    cart_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add an item to the cart.

    Args:
        listing: Listing name or listing_code
        qty: Quantity to add (default: 1)
        variant: Listing Variant name (optional)
        cart_id: Cart ID (optional)
        session_id: Session ID for guest users (optional)

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.add_to_cart
        {
            "listing": "LST-XXXXX",
            "qty": 2,
            "session_id": "guest-session-xxxxx"
        }
    """
    check_rate_limit("cart_add")

    if not listing:
        frappe.throw(_("Listing is required"))

    if cint(qty) <= 0:
        frappe.throw(_("Quantity must be greater than 0"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import add_to_cart as _add_to_cart

    result = _add_to_cart(
        listing=listing,
        qty=cint(qty),
        variant=variant,
        cart_id=cart_id,
        session_id=session_id,
    )

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "message": _("Item added to cart"),
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def update_cart_item(
    cart_id: str,
    line_name: str,
    qty: int,
) -> Dict[str, Any]:
    """
    Update quantity of a cart item.

    Args:
        cart_id: Cart ID
        line_name: Cart Line name or Listing name
        qty: New quantity (set to 0 to remove)

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.update_cart_item
        {
            "cart_id": "CART-XXXXX",
            "line_name": "LST-XXXXX",
            "qty": 3
        }
    """
    check_rate_limit("cart_update")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    if not line_name:
        frappe.throw(_("Line name is required"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import update_cart_item as _update_cart_item

    result = _update_cart_item(
        cart_id=cart_id,
        line_name=line_name,
        qty=flt(qty),
    )

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "message": _("Cart updated"),
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def remove_from_cart(
    cart_id: str,
    line_name: str,
) -> Dict[str, Any]:
    """
    Remove an item from the cart.

    Args:
        cart_id: Cart ID
        line_name: Cart Line name or Listing name

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.remove_from_cart
        {
            "cart_id": "CART-XXXXX",
            "line_name": "LST-XXXXX"
        }
    """
    check_rate_limit("cart_update")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    if not line_name:
        frappe.throw(_("Line name is required"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import remove_from_cart as _remove_from_cart

    result = _remove_from_cart(cart_id=cart_id, line_name=line_name)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "message": _("Item removed from cart"),
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def clear_cart(cart_id: str) -> Dict[str, Any]:
    """
    Clear all items from the cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.clear_cart
        {"cart_id": "CART-XXXXX"}
    """
    check_rate_limit("cart_update")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import clear_cart_items

    result = clear_cart_items(cart_id=cart_id)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "message": _("Cart cleared"),
        "cart": result,
    }


@frappe.whitelist(allow_guest=True)
def apply_coupon(
    cart_id: str,
    coupon_code: str,
) -> Dict[str, Any]:
    """
    Apply a coupon code to the cart.

    Args:
        cart_id: Cart ID
        coupon_code: Coupon code to apply

    Returns:
        dict: Updated cart with discount info

    Example:
        POST /api/method/tr_tradehub.api.v1.order.apply_coupon
        {
            "cart_id": "CART-XXXXX",
            "coupon_code": "SAVE20"
        }
    """
    check_rate_limit("cart_update")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    if not coupon_code:
        frappe.throw(_("Coupon code is required"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import apply_coupon_to_cart

    result = apply_coupon_to_cart(cart_id=cart_id, coupon_code=coupon_code.strip().upper())

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": result.get("success", True),
        "message": result.get("message", _("Coupon applied")),
        "discount": result.get("discount"),
        "cart": result.get("cart"),
    }


@frappe.whitelist(allow_guest=True)
def remove_coupon(cart_id: str) -> Dict[str, Any]:
    """
    Remove applied coupon from the cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.remove_coupon
        {"cart_id": "CART-XXXXX"}
    """
    check_rate_limit("cart_update")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "write"):
                return {"success": False, "message": _("Not permitted to update this cart")}

    cart.remove_coupon()

    from tr_tradehub.tr_tradehub.doctype.cart.cart import get_cart as _get_cart

    return {
        "success": True,
        "message": _("Coupon removed"),
        "cart": _get_cart(cart_id=cart_id),
    }


@frappe.whitelist()
def get_cart_summary(cart_id: str) -> Dict[str, Any]:
    """
    Get cart summary with seller grouping.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Cart summary with seller breakdown

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_cart_summary?cart_id=CART-XXXXX
    """
    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "read"):
                return {"success": False, "message": _("Not permitted to view this cart")}

    return {
        "success": True,
        "summary": cart.get_summary(),
        "sellers": cart.get_sellers(),
        "item_count": cart.get_item_count(),
        "seller_count": cart.get_seller_count(),
    }


# =============================================================================
# CHECKOUT ENDPOINTS
# =============================================================================


@frappe.whitelist()
def start_checkout(cart_id: str) -> Dict[str, Any]:
    """
    Start the checkout process for a cart.

    Validates all items, reserves stock, and transitions cart to checkout status.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Checkout data with validation status

    Example:
        POST /api/method/tr_tradehub.api.v1.order.start_checkout
        {"cart_id": "CART-XXXXX"}
    """
    check_rate_limit("checkout_start")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to checkout"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import start_checkout as _start_checkout

    result = _start_checkout(cart_id=cart_id)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    _log_order_event("checkout_started", details={"cart_id": cart_id})

    return {
        "success": True,
        "message": _("Checkout started"),
        "cart": result.get("cart"),
        "checkout_session_id": frappe.generate_hash(length=20),
    }


@frappe.whitelist()
def cancel_checkout(cart_id: str) -> Dict[str, Any]:
    """
    Cancel checkout and return cart to active state.

    Releases reserved stock and allows cart modifications again.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Updated cart data

    Example:
        POST /api/method/tr_tradehub.api.v1.order.cancel_checkout
        {"cart_id": "CART-XXXXX"}
    """
    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import cancel_checkout as _cancel_checkout

    result = _cancel_checkout(cart_id=cart_id)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    _log_order_event("checkout_cancelled", details={"cart_id": cart_id})

    return {
        "success": True,
        "message": _("Checkout cancelled"),
        "cart": result,
    }


@frappe.whitelist()
def complete_checkout(
    cart_id: str,
    shipping_address: Optional[Dict[str, Any]] = None,
    billing_address: Optional[Dict[str, Any]] = None,
    payment_method: Optional[str] = None,
    notes: Optional[str] = None,
    same_as_shipping: bool = True,
) -> Dict[str, Any]:
    """
    Complete checkout and create a Marketplace Order.

    This converts the cart to an order, creating sub-orders for each seller.

    Args:
        cart_id: Cart ID
        shipping_address: Shipping address details
        billing_address: Billing address details (optional if same_as_shipping)
        payment_method: Selected payment method
        notes: Order notes (optional)
        same_as_shipping: If True, billing address = shipping address

    Returns:
        dict: Created order information

    Example:
        POST /api/method/tr_tradehub.api.v1.order.complete_checkout
        {
            "cart_id": "CART-XXXXX",
            "shipping_address": {
                "address_line1": "123 Main St",
                "city": "Istanbul",
                "postal_code": "34000",
                "phone": "+905551234567"
            },
            "payment_method": "credit_card",
            "same_as_shipping": true
        }
    """
    check_rate_limit("checkout_complete")

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to complete checkout"))

    # Parse addresses if JSON strings
    if isinstance(shipping_address, str):
        shipping_address = json.loads(shipping_address)
    if isinstance(billing_address, str):
        billing_address = json.loads(billing_address)

    # Validate shipping address
    if not shipping_address:
        frappe.throw(_("Shipping address is required"))

    shipping_validation = _validate_shipping_address(shipping_address)
    if not shipping_validation["is_valid"]:
        frappe.throw("\n".join(shipping_validation["errors"]))

    shipping_address = shipping_validation["address"]

    # Handle billing address
    if same_as_shipping or not billing_address:
        billing_address = shipping_address
    else:
        billing_validation = _validate_shipping_address(billing_address)
        if not billing_validation["is_valid"]:
            frappe.throw(_("Billing address: ") + "\n".join(billing_validation["errors"]))
        billing_address = billing_validation["address"]

    from tr_tradehub.tr_tradehub.doctype.cart.cart import convert_cart_to_order

    result = convert_cart_to_order(
        cart_id=cart_id,
        shipping_address=shipping_address,
        billing_address=billing_address,
        payment_method=payment_method,
        notes=notes,
    )

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    order_name = result.get("order_name")
    order_id = result.get("order_id")

    _log_order_event(
        "order_created",
        order_name=order_name,
        details={
            "cart_id": cart_id,
            "payment_method": payment_method,
        },
    )

    return {
        "success": True,
        "message": _("Order created successfully"),
        "order_name": order_name,
        "order_id": order_id,
        "redirect_url": f"/order/{order_id}",
    }


# =============================================================================
# ORDER MANAGEMENT ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_order(
    order_name: Optional[str] = None,
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get order details.

    Args:
        order_name: Frappe document name
        order_id: Customer-facing order ID

    Returns:
        dict: Order details

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_order?order_id=TRH-XXXXX
    """
    from tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order import get_order as _get_order

    result = _get_order(order_name=order_name, order_id=order_id)

    if "error" in result:
        return {
            "success": False,
            "message": result.get("error"),
        }

    return {
        "success": True,
        "order": result,
    }


@frappe.whitelist()
def get_my_orders(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get orders for the current user (buyer).

    Args:
        status: Filter by status (optional)
        page: Page number (default: 1)
        page_size: Results per page (default: 20)

    Returns:
        dict: Orders with pagination

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_my_orders
        GET /api/method/tr_tradehub.api.v1.order.get_my_orders?status=Delivered&page=2
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to view orders"))

    from tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order import get_buyer_orders

    result = get_buyer_orders(
        buyer=user,
        status=status,
        page=cint(page),
        page_size=cint(page_size),
    )

    return {
        "success": True,
        "orders": result.get("orders", []),
        "total": result.get("total", 0),
        "page": result.get("page", 1),
        "page_size": result.get("page_size", 20),
        "total_pages": result.get("total_pages", 1),
    }


@frappe.whitelist()
def get_order_timeline(
    order_name: Optional[str] = None,
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get order event timeline/history.

    Args:
        order_name: Frappe document name
        order_id: Customer-facing order ID

    Returns:
        dict: Order timeline events

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_order_timeline?order_id=TRH-XXXXX
    """
    if not order_name and not order_id:
        frappe.throw(_("Either order_name or order_id is required"))

    if order_id and not order_name:
        order_name = frappe.db.get_value(
            "Marketplace Order", {"order_id": order_id}, "name"
        )

    if not order_name:
        return {"success": False, "message": _("Order not found")}

    # Permission check
    order = frappe.get_doc("Marketplace Order", order_name)
    if frappe.session.user != "Administrator":
        if order.buyer != frappe.session.user:
            seller = get_current_seller()
            if not seller or seller not in [i.seller for i in order.items]:
                if not frappe.has_permission("Marketplace Order", "read"):
                    return {"success": False, "message": _("Not permitted to view this order")}

    # Get order events
    events = []
    if frappe.db.exists("DocType", "Order Event"):
        events = frappe.get_all(
            "Order Event",
            filters={"marketplace_order": order_name},
            fields=[
                "name", "event_type", "event_category", "actor", "actor_type",
                "previous_status", "new_status", "event_data", "notes",
                "is_buyer_visible", "creation"
            ],
            order_by="creation DESC",
        )

        # Filter buyer-visible events for non-admin
        if frappe.session.user != "Administrator" and order.buyer == frappe.session.user:
            events = [e for e in events if e.get("is_buyer_visible", True)]

    # Add standard timeline milestones
    timeline = []

    # Order created
    timeline.append({
        "event": "Order Placed",
        "timestamp": order.creation,
        "status": "Completed",
        "icon": "shopping-cart",
    })

    # Payment
    if order.payment_status == "Paid":
        timeline.append({
            "event": "Payment Received",
            "timestamp": order.paid_at,
            "status": "Completed",
            "icon": "credit-card",
        })

    # Confirmed
    if order.confirmed_at:
        timeline.append({
            "event": "Order Confirmed",
            "timestamp": order.confirmed_at,
            "status": "Completed",
            "icon": "check-circle",
        })

    # Shipped
    if order.shipped_at:
        timeline.append({
            "event": "Order Shipped",
            "timestamp": order.shipped_at,
            "status": "Completed",
            "icon": "truck",
        })

    # Delivered
    if order.delivered_at:
        timeline.append({
            "event": "Order Delivered",
            "timestamp": order.delivered_at,
            "status": "Completed",
            "icon": "package",
        })

    # Completed
    if order.completed_at:
        timeline.append({
            "event": "Order Completed",
            "timestamp": order.completed_at,
            "status": "Completed",
            "icon": "award",
        })

    return {
        "success": True,
        "timeline": timeline,
        "events": events,
        "current_status": order.status,
    }


@frappe.whitelist()
def request_order_cancellation(
    order_name: Optional[str] = None,
    order_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Request cancellation of an order.

    Args:
        order_name: Frappe document name
        order_id: Customer-facing order ID
        reason: Cancellation reason

    Returns:
        dict: Cancellation request status

    Example:
        POST /api/method/tr_tradehub.api.v1.order.request_order_cancellation
        {
            "order_id": "TRH-XXXXX",
            "reason": "Changed my mind"
        }
    """
    if not order_name and not order_id:
        frappe.throw(_("Either order_name or order_id is required"))

    if order_id and not order_name:
        order_name = frappe.db.get_value(
            "Marketplace Order", {"order_id": order_id}, "name"
        )

    if not order_name:
        return {"success": False, "message": _("Order not found")}

    order = frappe.get_doc("Marketplace Order", order_name)

    # Permission check - only buyer can request cancellation
    if order.buyer != frappe.session.user:
        if not frappe.has_permission("Marketplace Order", "write"):
            return {"success": False, "message": _("Not permitted to cancel this order")}

    # Check if cancellation is possible
    if order.status in ["Shipped", "In Transit", "Delivered", "Completed", "Cancelled"]:
        return {
            "success": False,
            "message": _("Order cannot be cancelled in {0} status").format(order.status),
        }

    order.request_cancellation(reason=reason)

    _log_order_event(
        "cancellation_requested",
        order_name=order_name,
        details={"reason": reason},
    )

    return {
        "success": True,
        "message": _("Cancellation request submitted"),
        "order_status": order.status,
    }


@frappe.whitelist()
def track_order(
    order_name: Optional[str] = None,
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get tracking information for an order.

    Args:
        order_name: Frappe document name
        order_id: Customer-facing order ID

    Returns:
        dict: Tracking information by seller/sub-order

    Example:
        GET /api/method/tr_tradehub.api.v1.order.track_order?order_id=TRH-XXXXX
    """
    if not order_name and not order_id:
        frappe.throw(_("Either order_name or order_id is required"))

    if order_id and not order_name:
        order_name = frappe.db.get_value(
            "Marketplace Order", {"order_id": order_id}, "name"
        )

    if not order_name:
        return {"success": False, "message": _("Order not found")}

    order = frappe.get_doc("Marketplace Order", order_name)

    # Permission check
    if order.buyer != frappe.session.user:
        if not frappe.has_permission("Marketplace Order", "read"):
            return {"success": False, "message": _("Not permitted to view this order")}

    # Get sub orders with tracking info
    sub_orders = frappe.get_all(
        "Sub Order",
        filters={"marketplace_order": order_name},
        fields=[
            "name", "sub_order_id", "seller", "status", "fulfillment_status",
            "carrier", "tracking_number", "tracking_url",
            "shipped_at", "estimated_delivery_date", "delivered_at"
        ],
    )

    # Add seller names and generate tracking URLs
    tracking_info = []
    for so in sub_orders:
        so["seller_name"] = frappe.db.get_value(
            "Seller Profile", so["seller"], "seller_name"
        )

        # Generate tracking URL if not set
        if so.get("tracking_number") and so.get("carrier") and not so.get("tracking_url"):
            sub_order_doc = frappe.get_doc("Sub Order", so["name"])
            so["tracking_url"] = sub_order_doc.generate_tracking_url()

        tracking_info.append({
            "sub_order_id": so["sub_order_id"],
            "seller": so["seller"],
            "seller_name": so["seller_name"],
            "status": so["status"],
            "fulfillment_status": so["fulfillment_status"],
            "carrier": so["carrier"],
            "tracking_number": so["tracking_number"],
            "tracking_url": so["tracking_url"],
            "shipped_at": so["shipped_at"],
            "estimated_delivery": so["estimated_delivery_date"],
            "delivered_at": so["delivered_at"],
        })

    return {
        "success": True,
        "order_id": order.order_id,
        "order_status": order.status,
        "fulfillment_status": order.fulfillment_status,
        "tracking": tracking_info,
    }


# =============================================================================
# SUB ORDER ENDPOINTS (Seller)
# =============================================================================


@frappe.whitelist()
def get_seller_orders(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get sub orders for the current seller.

    Args:
        status: Filter by status (optional)
        page: Page number (default: 1)
        page_size: Results per page (default: 20)

    Returns:
        dict: Sub orders with pagination

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_seller_orders
        GET /api/method/tr_tradehub.api.v1.order.get_seller_orders?status=Pending
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to view seller orders"))

    from tr_tradehub.tr_tradehub.doctype.sub_order.sub_order import get_seller_sub_orders

    result = get_seller_sub_orders(
        seller=seller,
        status=status,
        page=cint(page),
        page_size=cint(page_size),
    )

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    return {
        "success": True,
        "sub_orders": result.get("sub_orders", []),
        "total": result.get("total", 0),
        "page": result.get("page", 1),
        "page_size": result.get("page_size", 20),
        "total_pages": result.get("total_pages", 1),
    }


@frappe.whitelist()
def get_sub_order(
    sub_order_name: Optional[str] = None,
    sub_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get sub order details.

    Args:
        sub_order_name: Frappe document name
        sub_order_id: Customer-facing sub order ID

    Returns:
        dict: Sub order details

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_sub_order?sub_order_id=SUB-XXXXX
    """
    from tr_tradehub.tr_tradehub.doctype.sub_order.sub_order import get_sub_order as _get_sub_order

    result = _get_sub_order(
        sub_order_name=sub_order_name,
        sub_order_id=sub_order_id,
    )

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    return {
        "success": True,
        "sub_order": result,
    }


@frappe.whitelist()
def update_sub_order_status(
    sub_order_name: str,
    action: str,
    carrier: Optional[str] = None,
    tracking_number: Optional[str] = None,
    tracking_url: Optional[str] = None,
    reason: Optional[str] = None,
    delivery_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update sub order status (seller action).

    Args:
        sub_order_name: Sub Order name
        action: Action to perform (accept, process, pack, ship, deliver, complete, cancel, hold)
        carrier: Shipping carrier (for ship action)
        tracking_number: Tracking number (for ship action)
        tracking_url: Tracking URL (optional, for ship action)
        reason: Reason (for cancel/hold actions)
        delivery_date: Delivery date (for deliver action)

    Returns:
        dict: Updated status

    Example:
        POST /api/method/tr_tradehub.api.v1.order.update_sub_order_status
        {
            "sub_order_name": "SUB-XXXXX",
            "action": "ship",
            "carrier": "Yurtici Kargo",
            "tracking_number": "1234567890"
        }
    """
    check_rate_limit("order_status_update")

    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to update sub orders"))

    from tr_tradehub.tr_tradehub.doctype.sub_order.sub_order import update_sub_order_status as _update_status

    result = _update_status(
        sub_order_name=sub_order_name,
        action=action,
        carrier=carrier,
        tracking_number=tracking_number,
        tracking_url=tracking_url,
        reason=reason,
        delivery_date=delivery_date,
    )

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    _log_order_event(
        f"sub_order_{action}",
        sub_order_name=sub_order_name,
        details={
            "action": action,
            "carrier": carrier,
            "tracking_number": tracking_number,
        },
    )

    return {
        "success": True,
        "message": result.get("message"),
        "status": result.get("sub_order_status"),
        "fulfillment_status": result.get("fulfillment_status"),
    }


@frappe.whitelist()
def add_tracking_info(
    sub_order_name: str,
    carrier: str,
    tracking_number: str,
    tracking_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add tracking information to a sub order (seller action).

    This also marks the sub order as shipped.

    Args:
        sub_order_name: Sub Order name
        carrier: Shipping carrier name
        tracking_number: Tracking number
        tracking_url: Tracking URL (optional, will be generated if not provided)

    Returns:
        dict: Updated tracking info

    Example:
        POST /api/method/tr_tradehub.api.v1.order.add_tracking_info
        {
            "sub_order_name": "SUB-XXXXX",
            "carrier": "Yurtici Kargo",
            "tracking_number": "1234567890"
        }
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to add tracking"))

    if not carrier:
        frappe.throw(_("Carrier is required"))

    if not tracking_number:
        frappe.throw(_("Tracking number is required"))

    from tr_tradehub.tr_tradehub.doctype.sub_order.sub_order import add_tracking

    result = add_tracking(
        sub_order_name=sub_order_name,
        carrier=carrier,
        tracking_number=tracking_number,
        tracking_url=tracking_url,
    )

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    _log_order_event(
        "tracking_added",
        sub_order_name=sub_order_name,
        details={
            "carrier": carrier,
            "tracking_number": tracking_number,
        },
    )

    return {
        "success": True,
        "message": _("Tracking information added"),
        "tracking": result.get("tracking"),
    }


@frappe.whitelist()
def get_pending_seller_orders() -> Dict[str, Any]:
    """
    Get pending orders requiring seller action.

    Returns:
        dict: Pending sub orders grouped by action required

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_pending_seller_orders
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to view pending orders"))

    # Get counts by status
    pending_acceptance = frappe.db.count(
        "Sub Order",
        filters={"seller": seller, "status": "Pending"}
    )

    awaiting_shipment = frappe.db.count(
        "Sub Order",
        filters={"seller": seller, "status": ["in", ["Accepted", "Processing", "Packed"]]}
    )

    pending_delivery_confirmation = frappe.db.count(
        "Sub Order",
        filters={"seller": seller, "status": ["in", ["Shipped", "In Transit", "Out for Delivery"]]}
    )

    pending_return = frappe.db.count(
        "Sub Order",
        filters={"seller": seller, "return_requested": 1, "return_status": "Pending"}
    )

    # Get most urgent orders
    urgent_orders = frappe.get_all(
        "Sub Order",
        filters={
            "seller": seller,
            "status": ["in", ["Pending", "Accepted", "Processing"]],
        },
        fields=[
            "name", "sub_order_id", "status", "order_date",
            "grand_total", "buyer_name", "currency"
        ],
        order_by="order_date ASC",
        limit=10,
    )

    return {
        "success": True,
        "pending_acceptance": pending_acceptance,
        "awaiting_shipment": awaiting_shipment,
        "pending_delivery_confirmation": pending_delivery_confirmation,
        "pending_return": pending_return,
        "total_requiring_action": pending_acceptance + awaiting_shipment,
        "urgent_orders": urgent_orders,
    }


# =============================================================================
# ORDER STATISTICS ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_buyer_order_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get order statistics for the current buyer.

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        dict: Order statistics

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_buyer_order_statistics?days=90
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to view statistics"))

    from_date = add_days(nowdate(), -cint(days))

    # Get order statistics
    stats = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as order_count,
            SUM(grand_total) as total_value
        FROM `tabMarketplace Order`
        WHERE buyer = %(buyer)s
        AND order_date >= %(from_date)s
        AND docstatus != 2
        GROUP BY status
    """, {"buyer": user, "from_date": from_date}, as_dict=True)

    status_breakdown = {s.status: {"count": s.order_count, "value": flt(s.total_value)} for s in stats}

    total_orders = sum(s.order_count for s in stats)
    total_spent = sum(flt(s.total_value) for s in stats)

    return {
        "success": True,
        "period_days": cint(days),
        "total_orders": total_orders,
        "total_spent": total_spent,
        "status_breakdown": status_breakdown,
        "average_order_value": total_spent / total_orders if total_orders > 0 else 0,
    }


@frappe.whitelist()
def get_seller_order_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get order statistics for the current seller.

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        dict: Order statistics

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_seller_order_statistics?days=90
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller to view seller statistics"))

    from tr_tradehub.tr_tradehub.doctype.sub_order.sub_order import get_sub_order_statistics

    result = get_sub_order_statistics(seller=seller, days=cint(days))

    return {
        "success": True,
        **result,
    }


@frappe.whitelist()
def get_cart_statistics() -> Dict[str, Any]:
    """
    Get cart statistics (admin only).

    Returns:
        dict: Cart statistics

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_cart_statistics
    """
    if not frappe.has_permission("Cart", "read"):
        frappe.throw(_("Not permitted to view cart statistics"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import get_cart_statistics as _get_cart_stats

    result = _get_cart_stats()

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    return {
        "success": True,
        **result,
    }


@frappe.whitelist()
def get_order_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get platform-wide order statistics (admin only).

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        dict: Order statistics

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_order_statistics?days=90
    """
    if not frappe.has_permission("Marketplace Order", "read"):
        frappe.throw(_("Not permitted to view order statistics"))

    from tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order import get_order_statistics as _get_stats

    result = _get_stats(days=cint(days))

    return {
        "success": True,
        **result,
    }


# =============================================================================
# ABANDONED CART ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_abandoned_carts(
    days: int = 7,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get abandoned carts for recovery (admin/seller).

    Args:
        days: Days since abandoned (default: 7)
        page: Page number (default: 1)
        page_size: Results per page (default: 20)

    Returns:
        dict: Abandoned carts list

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_abandoned_carts?days=3
    """
    if not frappe.has_permission("Cart", "read"):
        frappe.throw(_("Not permitted to view abandoned carts"))

    from tr_tradehub.tr_tradehub.doctype.cart.cart import get_abandoned_carts as _get_abandoned

    result = _get_abandoned(days=cint(days), page=cint(page), page_size=cint(page_size))

    if "error" in result:
        return {"success": False, "message": result.get("error")}

    return {
        "success": True,
        **result,
    }


@frappe.whitelist()
def send_cart_recovery_email(cart_id: str) -> Dict[str, Any]:
    """
    Send cart recovery email to buyer (admin/marketing).

    Args:
        cart_id: Cart ID

    Returns:
        dict: Result

    Example:
        POST /api/method/tr_tradehub.api.v1.order.send_cart_recovery_email
        {"cart_id": "CART-XXXXX"}
    """
    if not frappe.has_permission("Cart", "write"):
        frappe.throw(_("Not permitted to send recovery emails"))

    if not cart_id:
        frappe.throw(_("Cart ID is required"))

    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    if cart.status != "Abandoned":
        return {"success": False, "message": _("Cart is not abandoned")}

    if not cart.buyer:
        return {"success": False, "message": _("Cart has no buyer email")}

    if cart.recovery_email_sent:
        return {"success": False, "message": _("Recovery email already sent")}

    # Get buyer email
    buyer_email = frappe.db.get_value("User", cart.buyer, "email")
    buyer_name = frappe.db.get_value("User", cart.buyer, ["first_name", "full_name"], as_dict=True)

    if not buyer_email:
        return {"success": False, "message": _("Buyer email not found")}

    # Send recovery email
    try:
        recovery_url = frappe.utils.get_url(f"/cart/recover?id={cart.cart_id}")

        frappe.sendmail(
            recipients=buyer_email,
            subject=_("You left items in your cart - TR-TradeHub"),
            template="cart_recovery",
            args={
                "first_name": buyer_name.get("first_name", "Customer"),
                "cart_total": cart.grand_total,
                "currency": cart.currency,
                "item_count": len(cart.items),
                "recovery_link": recovery_url,
            },
            now=True,
        )

        cart.db_set("recovery_email_sent", 1)
        cart.db_set("recovery_email_sent_at", now_datetime())

        return {
            "success": True,
            "message": _("Recovery email sent to {0}").format(buyer_email),
        }

    except Exception as e:
        frappe.log_error(f"Cart recovery email error: {str(e)}", "Order API Error")
        return {"success": False, "message": _("Failed to send recovery email")}


# =============================================================================
# SHIPPING CARRIERS REFERENCE
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_available_carriers() -> Dict[str, Any]:
    """
    Get list of available shipping carriers (primarily Turkish).

    Returns:
        dict: List of carriers with tracking URL patterns

    Example:
        GET /api/method/tr_tradehub.api.v1.order.get_available_carriers
    """
    carriers = [
        {
            "name": "Yurtici Kargo",
            "code": "yurtici",
            "tracking_url_pattern": "https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "Aras Kargo",
            "code": "aras",
            "tracking_url_pattern": "https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "MNG Kargo",
            "code": "mng",
            "tracking_url_pattern": "https://www.mngkargo.com.tr/gonderi-takip/?no={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "SuratKargo",
            "code": "surat",
            "tracking_url_pattern": "https://www.suratkargo.com.tr/gonderi-takip?takipNo={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "PTT Kargo",
            "code": "ptt",
            "tracking_url_pattern": "https://gonderitakip.ptt.gov.tr/?barkod={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "Hepsijet",
            "code": "hepsijet",
            "tracking_url_pattern": "https://www.hepsijet.com/gonderi-takip?no={tracking_number}",
            "country": "Turkey",
        },
        {
            "name": "Trendyol Express",
            "code": "trendyol_express",
            "tracking_url_pattern": None,
            "country": "Turkey",
        },
        {
            "name": "UPS",
            "code": "ups",
            "tracking_url_pattern": "https://www.ups.com/track?tracknum={tracking_number}",
            "country": "International",
        },
        {
            "name": "DHL",
            "code": "dhl",
            "tracking_url_pattern": "https://www.dhl.com/tr-en/home/tracking.html?tracking-id={tracking_number}",
            "country": "International",
        },
        {
            "name": "FedEx",
            "code": "fedex",
            "tracking_url_pattern": "https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
            "country": "International",
        },
    ]

    return {
        "success": True,
        "carriers": carriers,
        "default_carrier": "Yurtici Kargo",
    }


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
Public API Endpoints:

Cart Management:
- get_cart: Get cart details
- get_or_create_cart: Get or create cart
- add_to_cart: Add item to cart
- update_cart_item: Update cart item quantity
- remove_from_cart: Remove item from cart
- clear_cart: Clear all cart items
- apply_coupon: Apply coupon to cart
- remove_coupon: Remove coupon from cart
- get_cart_summary: Get cart summary with seller grouping

Checkout:
- start_checkout: Start checkout process
- cancel_checkout: Cancel checkout
- complete_checkout: Complete checkout and create order

Order Management (Buyer):
- get_order: Get order details
- get_my_orders: Get buyer's orders
- get_order_timeline: Get order event history
- request_order_cancellation: Request order cancellation
- track_order: Get tracking information

Sub Order Management (Seller):
- get_seller_orders: Get seller's sub orders
- get_sub_order: Get sub order details
- update_sub_order_status: Update sub order status
- add_tracking_info: Add tracking to sub order
- get_pending_seller_orders: Get orders requiring action

Statistics:
- get_buyer_order_statistics: Buyer order stats
- get_seller_order_statistics: Seller order stats
- get_cart_statistics: Cart conversion stats
- get_order_statistics: Platform order stats

Cart Recovery:
- get_abandoned_carts: Get abandoned carts
- send_cart_recovery_email: Send recovery email

Reference:
- get_available_carriers: Get shipping carriers list
"""
