# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Payment & Escrow API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Payment initiation and processing
- Payment gateway integration (iyzico, PayTR)
- 3D Secure authentication flows
- Turkish installment payments (taksit)
- Escrow management (hold, release, dispute)
- Seller balance and payout management
- Refund processing
- Transaction history and analytics
- Payment webhook handling

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.payment.<function_name>

All endpoints follow Frappe conventions and patterns.
"""

import json
import secrets
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
    "payment_create": {"limit": 10, "window": 300},  # 10 per 5 min
    "payment_process": {"limit": 10, "window": 300},  # 10 per 5 min
    "installment_query": {"limit": 30, "window": 60},  # 30 per minute
    "refund_request": {"limit": 5, "window": 300},  # 5 per 5 min
    "payout_request": {"limit": 5, "window": 600},  # 5 per 10 min
    "balance_query": {"limit": 60, "window": 60},  # 60 per minute
    "webhook": {"limit": 100, "window": 60},  # 100 per minute (for gateway callbacks)
}

# Supported payment gateways
SUPPORTED_GATEWAYS = ["iyzico", "paytr", "stripe"]

# Supported payment methods
PAYMENT_METHODS = [
    "Credit Card",
    "Debit Card",
    "Bank Transfer",
    "iyzico Wallet",
    "BKM Express",
    "Cash on Delivery",
]

# Maximum installment counts by card type
MAX_INSTALLMENTS = {
    "default": 12,
    "debit": 1,  # Debit cards don't support installments
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

    cache_key = f"rate_limit:payment:{action}:{identifier}"

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


def _log_payment_event(
    event_type: str,
    payment_intent: Optional[str] = None,
    escrow_account: Optional[str] = None,
    order_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "Info",
) -> None:
    """Log payment-related events for audit trail."""
    try:
        ip_address = None
        user_agent = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
                user_agent = str(frappe.request.user_agent)[:500]
        except Exception:
            pass

        # Log to activity log
        frappe.get_doc({
            "doctype": "Activity Log",
            "user": frappe.session.user,
            "subject": f"Payment Event: {event_type}",
            "content": json.dumps({
                "event_type": event_type,
                "payment_intent": payment_intent,
                "escrow_account": escrow_account,
                "order_name": order_name,
                "details": details,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "severity": severity,
            }),
            "reference_doctype": "Payment Intent" if payment_intent else "Escrow Account" if escrow_account else None,
            "reference_name": payment_intent or escrow_account,
        }).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Payment event logging error: {str(e)}", "Payment API")


def _validate_amount(amount: float, currency: str = "TRY") -> float:
    """
    Validate and normalize payment amount.

    Args:
        amount: Payment amount
        currency: Currency code

    Returns:
        float: Validated amount

    Raises:
        frappe.ValidationError: If amount is invalid
    """
    amount = flt(amount, 2)

    if amount <= 0:
        frappe.throw(_("Payment amount must be greater than 0"))

    # Minimum amounts by currency
    min_amounts = {
        "TRY": 1.00,
        "USD": 0.50,
        "EUR": 0.50,
    }

    min_amount = min_amounts.get(currency, 0.01)
    if amount < min_amount:
        frappe.throw(
            _("Minimum payment amount for {0} is {1}").format(currency, min_amount)
        )

    # Maximum amount (for security)
    max_amount = 1000000  # 1 million
    if amount > max_amount:
        frappe.throw(_("Payment amount exceeds maximum allowed"))

    return amount


def _format_currency(amount: float, currency: str = "TRY") -> str:
    """Format amount as currency string."""
    currency_symbols = {
        "TRY": "₺",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
    }
    symbol = currency_symbols.get(currency, currency)
    return f"{symbol}{flt(amount, 2):,.2f}"


def _get_gateway_client(gateway: str):
    """
    Get payment gateway client.

    Args:
        gateway: Gateway name (iyzico, paytr, stripe)

    Returns:
        Gateway client instance

    Raises:
        frappe.ValidationError: If gateway is not supported
    """
    if gateway not in SUPPORTED_GATEWAYS:
        frappe.throw(_("Payment gateway {0} is not supported").format(gateway))

    if gateway == "iyzico":
        from tr_tradehub.integrations.iyzico import IyzicoClient
        return IyzicoClient()
    elif gateway == "paytr":
        from tr_tradehub.integrations.paytr import PayTRClient
        return PayTRClient()
    elif gateway == "stripe":
        # Placeholder for Stripe integration
        frappe.throw(_("Stripe integration is not yet implemented"))

    return None


# =============================================================================
# PAYMENT INITIATION
# =============================================================================


@frappe.whitelist()
def create_payment_intent(
    order_name: str = None,
    amount: float = None,
    currency: str = "TRY",
    payment_method: str = "Credit Card",
    gateway: str = "iyzico",
    buyer_info: Dict = None,
    billing_address: Dict = None,
    metadata: Dict = None,
) -> Dict[str, Any]:
    """
    Create a new payment intent for an order or direct payment.

    Args:
        order_name: Marketplace Order name (optional for direct payments)
        amount: Payment amount (required if no order)
        currency: Currency code (default: TRY)
        payment_method: Payment method
        gateway: Payment gateway to use
        buyer_info: Buyer information (name, email, phone)
        billing_address: Billing address details
        metadata: Additional metadata

    Returns:
        dict: Payment intent details including intent_id
    """
    check_rate_limit("payment_create")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to create a payment"))

    # Get amount from order if provided
    if order_name:
        if not frappe.db.exists("Marketplace Order", order_name):
            frappe.throw(_("Order {0} not found").format(order_name))

        order = frappe.get_doc("Marketplace Order", order_name)

        # Validate order belongs to user
        if order.buyer != user:
            frappe.throw(_("You are not authorized to pay for this order"))

        # Validate order status
        if order.payment_status == "Paid":
            frappe.throw(_("This order has already been paid"))

        if order.status in ["Cancelled", "Refunded"]:
            frappe.throw(_("Cannot create payment for {0} order").format(order.status))

        amount = flt(order.grand_total)
        currency = order.currency or "TRY"

    if not amount:
        frappe.throw(_("Payment amount is required"))

    # Validate amount
    amount = _validate_amount(amount, currency)

    # Validate gateway
    if gateway not in SUPPORTED_GATEWAYS:
        frappe.throw(_("Payment gateway {0} is not supported").format(gateway))

    # Get buyer info
    if not buyer_info:
        buyer_doc = frappe.get_doc("User", user)
        buyer_info = {
            "name": buyer_doc.full_name,
            "email": buyer_doc.email,
            "phone": buyer_doc.mobile_no or buyer_doc.phone,
            "ip_address": frappe.request.remote_addr if frappe.request else None,
        }

    # Create payment intent
    try:
        payment_intent = frappe.get_doc({
            "doctype": "Payment Intent",
            "marketplace_order": order_name,
            "buyer": user,
            "buyer_type": "User",
            "amount": amount,
            "currency": currency,
            "payment_method": payment_method,
            "payment_gateway": gateway,
            "status": "Created",
            "billing_name": buyer_info.get("name"),
            "billing_email": buyer_info.get("email"),
            "billing_phone": buyer_info.get("phone"),
            "ip_address": buyer_info.get("ip_address"),
            "metadata": json.dumps(metadata or {}),
        })

        # Add billing address if provided
        if billing_address:
            payment_intent.billing_address = billing_address.get("address")
            payment_intent.billing_city = billing_address.get("city")
            payment_intent.billing_state = billing_address.get("state")
            payment_intent.billing_country = billing_address.get("country", "Turkey")
            payment_intent.billing_zip_code = billing_address.get("zip_code")

        payment_intent.insert()

        _log_payment_event(
            "Payment Intent Created",
            payment_intent=payment_intent.name,
            order_name=order_name,
            details={"amount": amount, "gateway": gateway},
        )

        return {
            "success": True,
            "intent_id": payment_intent.intent_id,
            "payment_intent_name": payment_intent.name,
            "amount": amount,
            "formatted_amount": _format_currency(amount, currency),
            "currency": currency,
            "status": payment_intent.status,
            "expires_at": str(payment_intent.expires_at),
        }

    except Exception as e:
        frappe.log_error(str(e), "Create Payment Intent Error")
        frappe.throw(_("Failed to create payment intent: {0}").format(str(e)))


@frappe.whitelist()
def get_payment_intent(intent_id: str) -> Dict[str, Any]:
    """
    Get payment intent details.

    Args:
        intent_id: Payment intent ID or name

    Returns:
        dict: Payment intent details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find by intent_id or name
    filters = {"intent_id": intent_id}
    if not frappe.db.exists("Payment Intent", filters):
        filters = {"name": intent_id}

    if not frappe.db.exists("Payment Intent", filters):
        frappe.throw(_("Payment intent not found"))

    intent = frappe.get_doc("Payment Intent", filters)

    # Validate access
    if intent.buyer != user and not frappe.has_permission("Payment Intent", "read"):
        frappe.throw(_("You are not authorized to view this payment"))

    return {
        "intent_id": intent.intent_id,
        "name": intent.name,
        "order": intent.marketplace_order,
        "amount": flt(intent.amount),
        "formatted_amount": _format_currency(intent.amount, intent.currency),
        "currency": intent.currency,
        "status": intent.status,
        "payment_method": intent.payment_method,
        "payment_gateway": intent.payment_gateway,
        "requires_3d_secure": cint(intent.requires_3d_secure),
        "has_installments": cint(intent.has_installments),
        "installment_count": cint(intent.installment_count),
        "created_at": str(intent.created_at),
        "expires_at": str(intent.expires_at) if intent.expires_at else None,
        "paid_at": str(intent.paid_at) if intent.paid_at else None,
        "gateway_transaction_id": intent.gateway_transaction_id,
        "last_error": intent.last_error,
    }


@frappe.whitelist()
def cancel_payment_intent(intent_id: str, reason: str = None) -> Dict[str, Any]:
    """
    Cancel a payment intent.

    Args:
        intent_id: Payment intent ID or name
        reason: Cancellation reason

    Returns:
        dict: Updated payment intent status
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find payment intent
    filters = {"intent_id": intent_id}
    if not frappe.db.exists("Payment Intent", filters):
        filters = {"name": intent_id}

    if not frappe.db.exists("Payment Intent", filters):
        frappe.throw(_("Payment intent not found"))

    intent = frappe.get_doc("Payment Intent", filters)

    # Validate access
    if intent.buyer != user and not frappe.has_permission("Payment Intent", "write"):
        frappe.throw(_("You are not authorized to cancel this payment"))

    # Validate status
    if intent.status in ["Paid", "Captured", "Refunded"]:
        frappe.throw(_("Cannot cancel a {0} payment").format(intent.status))

    # Cancel
    intent.db_set("status", "Cancelled")
    intent.db_set("cancellation_reason", reason)
    intent.db_set("cancelled_at", now_datetime())
    intent.clear_cache()

    _log_payment_event(
        "Payment Intent Cancelled",
        payment_intent=intent.name,
        details={"reason": reason},
    )

    return {
        "success": True,
        "intent_id": intent.intent_id,
        "status": "Cancelled",
        "message": _("Payment has been cancelled"),
    }


# =============================================================================
# PAYMENT PROCESSING
# =============================================================================


@frappe.whitelist()
def process_card_payment(
    intent_id: str,
    card_holder_name: str,
    card_number: str,
    expiry_month: str,
    expiry_year: str,
    cvv: str,
    installments: int = 1,
    use_3d_secure: bool = True,
    save_card: bool = False,
) -> Dict[str, Any]:
    """
    Process a card payment for a payment intent.

    Args:
        intent_id: Payment intent ID
        card_holder_name: Name on card
        card_number: Full card number
        expiry_month: Card expiry month (MM)
        expiry_year: Card expiry year (YY or YYYY)
        cvv: Card CVV/CVC
        installments: Number of installments (default: 1)
        use_3d_secure: Whether to use 3D Secure (default: True)
        save_card: Whether to save card for future use

    Returns:
        dict: Payment result with redirect URL for 3D Secure if required
    """
    check_rate_limit("payment_process")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Get payment intent
    filters = {"intent_id": intent_id}
    if not frappe.db.exists("Payment Intent", filters):
        filters = {"name": intent_id}

    if not frappe.db.exists("Payment Intent", filters):
        frappe.throw(_("Payment intent not found"))

    intent = frappe.get_doc("Payment Intent", filters)

    # Validate access
    if intent.buyer != user:
        frappe.throw(_("You are not authorized to pay for this"))

    # Validate status
    if intent.status not in ["Created", "Pending", "Failed"]:
        frappe.throw(_("Cannot process payment in {0} status").format(intent.status))

    # Check expiration
    if intent.expires_at and get_datetime(intent.expires_at) < now_datetime():
        intent.db_set("status", "Expired")
        frappe.throw(_("Payment intent has expired. Please create a new one."))

    # Validate card data
    card_number = card_number.replace(" ", "").replace("-", "")
    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        frappe.throw(_("Invalid card number"))

    if not cvv.isdigit() or len(cvv) < 3 or len(cvv) > 4:
        frappe.throw(_("Invalid CVV"))

    # Validate installments
    installments = cint(installments)
    if installments < 1:
        installments = 1
    elif installments > MAX_INSTALLMENTS["default"]:
        frappe.throw(_("Maximum {0} installments allowed").format(MAX_INSTALLMENTS["default"]))

    # Start processing
    intent.start_processing()

    try:
        gateway = _get_gateway_client(intent.payment_gateway)

        # Prepare card data (masked for security)
        card_data = {
            "holder_name": card_holder_name,
            "number": card_number,
            "expiry_month": expiry_month,
            "expiry_year": expiry_year if len(expiry_year) == 4 else f"20{expiry_year}",
            "cvv": cvv,
        }

        # Prepare buyer data
        buyer_data = {
            "id": user,
            "name": intent.billing_name,
            "email": intent.billing_email,
            "phone": intent.billing_phone,
            "ip": intent.ip_address,
            "address": intent.billing_address,
            "city": intent.billing_city,
            "country": intent.billing_country or "Turkey",
        }

        # Prepare order/basket items
        basket_items = []
        if intent.marketplace_order:
            order = frappe.get_doc("Marketplace Order", intent.marketplace_order)
            for item in order.items:
                basket_items.append({
                    "id": item.listing or item.name,
                    "name": item.item_name,
                    "category": item.category or "General",
                    "price": flt(item.rate),
                    "quantity": cint(item.qty),
                })
        else:
            # Single item for direct payments
            basket_items.append({
                "id": intent.name,
                "name": "Payment",
                "category": "General",
                "price": flt(intent.amount),
                "quantity": 1,
            })

        # Set installment info on intent
        if installments > 1:
            intent.db_set("has_installments", 1)
            intent.db_set("installment_count", installments)

        # Process based on 3D Secure requirement
        if use_3d_secure:
            # Initialize 3D Secure payment
            callback_url = frappe.utils.get_url(
                f"/api/method/tr_tradehub.api.v1.payment.handle_3d_secure_callback?intent_id={intent.name}"
            )

            result = gateway.create_3d_secure_payment(
                conversation_id=intent.name,
                amount=flt(intent.amount),
                currency=intent.currency,
                installments=installments,
                card=card_data,
                buyer=buyer_data,
                basket_items=basket_items,
                callback_url=callback_url,
            )

            intent.db_set("status", "Requires Action")
            intent.db_set("requires_3d_secure", 1)
            intent.db_set("three_d_status", "Initiated")
            intent.db_set("three_d_html_content", result.get("html_content"))
            intent.clear_cache()

            _log_payment_event(
                "3D Secure Initiated",
                payment_intent=intent.name,
                details={"installments": installments},
            )

            return {
                "success": True,
                "requires_3d_secure": True,
                "redirect_url": result.get("redirect_url"),
                "html_content": result.get("html_content"),
                "intent_id": intent.intent_id,
                "status": "Requires Action",
            }

        else:
            # Direct payment (non-3D Secure)
            result = gateway.create_payment(
                conversation_id=intent.name,
                amount=flt(intent.amount),
                currency=intent.currency,
                installments=installments,
                card=card_data,
                buyer=buyer_data,
                basket_items=basket_items,
            )

            if result.get("status") == "success":
                intent.mark_paid(
                    payment_id=result.get("payment_id"),
                    reference=result.get("payment_transaction_id"),
                )

                # Create escrow if order exists
                if intent.marketplace_order:
                    _create_escrow_for_order(intent)

                _log_payment_event(
                    "Payment Successful",
                    payment_intent=intent.name,
                    order_name=intent.marketplace_order,
                    details=result,
                )

                return {
                    "success": True,
                    "requires_3d_secure": False,
                    "intent_id": intent.intent_id,
                    "status": "Paid",
                    "transaction_id": result.get("payment_id"),
                    "message": _("Payment successful"),
                }
            else:
                intent.mark_failed(
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message"),
                )

                _log_payment_event(
                    "Payment Failed",
                    payment_intent=intent.name,
                    details=result,
                    severity="Warning",
                )

                return {
                    "success": False,
                    "intent_id": intent.intent_id,
                    "status": "Failed",
                    "error_code": result.get("error_code"),
                    "error_message": result.get("error_message"),
                }

    except Exception as e:
        intent.mark_failed(error_message=str(e))
        frappe.log_error(str(e), "Payment Processing Error")

        _log_payment_event(
            "Payment Error",
            payment_intent=intent.name,
            details={"error": str(e)},
            severity="Error",
        )

        frappe.throw(_("Payment processing failed: {0}").format(str(e)))


@frappe.whitelist(allow_guest=True)
def handle_3d_secure_callback(intent_id: str = None, **kwargs) -> str:
    """
    Handle 3D Secure callback from payment gateway.

    This endpoint is called by the payment gateway after 3D Secure authentication.

    Args:
        intent_id: Payment intent ID
        **kwargs: Callback parameters from gateway

    Returns:
        str: HTML redirect to success/failure page
    """
    check_rate_limit("webhook", identifier="3d_secure_callback")

    if not intent_id:
        intent_id = kwargs.get("conversationId") or kwargs.get("conversation_id")

    if not intent_id:
        return _render_payment_result(False, _("Invalid callback: Missing payment reference"))

    try:
        # Find payment intent
        filters = {"name": intent_id}
        if not frappe.db.exists("Payment Intent", filters):
            filters = {"intent_id": intent_id}

        if not frappe.db.exists("Payment Intent", filters):
            return _render_payment_result(False, _("Payment not found"))

        intent = frappe.get_doc("Payment Intent", filters)

        # Get gateway and verify callback
        gateway = _get_gateway_client(intent.payment_gateway)

        result = gateway.complete_3d_secure(
            conversation_id=intent.name,
            callback_data=kwargs,
        )

        if result.get("status") == "success":
            intent.db_set("three_d_status", "Successful")
            intent.mark_paid(
                payment_id=result.get("payment_id"),
                reference=result.get("payment_transaction_id"),
            )

            # Store card info (masked)
            if result.get("card_last_four"):
                intent.db_set("card_last_four", result.get("card_last_four"))
                intent.db_set("card_type", result.get("card_type"))
                intent.db_set("card_association", result.get("card_association"))

            # Create escrow if order exists
            if intent.marketplace_order:
                _create_escrow_for_order(intent)

            _log_payment_event(
                "3D Secure Payment Successful",
                payment_intent=intent.name,
                order_name=intent.marketplace_order,
                details=result,
            )

            # Redirect to success page
            success_url = frappe.utils.get_url(
                f"/marketplace/payment-success?order={intent.marketplace_order}&intent={intent.intent_id}"
            )
            return _render_redirect(success_url)

        else:
            intent.db_set("three_d_status", "Failed")
            intent.mark_failed(
                error_code=result.get("error_code"),
                error_message=result.get("error_message"),
            )

            _log_payment_event(
                "3D Secure Payment Failed",
                payment_intent=intent.name,
                details=result,
                severity="Warning",
            )

            # Redirect to failure page
            failure_url = frappe.utils.get_url(
                f"/marketplace/payment-failed?intent={intent.intent_id}&error={result.get('error_code', 'unknown')}"
            )
            return _render_redirect(failure_url)

    except Exception as e:
        frappe.log_error(str(e), "3D Secure Callback Error")
        return _render_payment_result(False, _("Payment verification failed"))


def _render_payment_result(success: bool, message: str) -> str:
    """Render HTML payment result page."""
    status = "success" if success else "error"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Payment {status.title()}</title>
        <style>
            body {{ font-family: sans-serif; text-align: center; padding: 50px; }}
            .{status} {{ color: {"green" if success else "red"}; }}
        </style>
    </head>
    <body>
        <h1 class="{status}">Payment {status.title()}</h1>
        <p>{message}</p>
        <script>
            setTimeout(function() {{
                window.location.href = '/marketplace';
            }}, 3000);
        </script>
    </body>
    </html>
    """


def _render_redirect(url: str) -> str:
    """Render HTML redirect page."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="0;url={url}">
        <title>Redirecting...</title>
    </head>
    <body>
        <p>Redirecting... <a href="{url}">Click here</a> if not redirected.</p>
    </body>
    </html>
    """


def _create_escrow_for_order(intent):
    """Create escrow accounts for order sub-orders."""
    if not intent.marketplace_order:
        return

    order = frappe.get_doc("Marketplace Order", intent.marketplace_order)

    # Get sub-orders
    sub_orders = frappe.get_all(
        "Sub Order",
        filters={"marketplace_order": order.name},
        fields=["name", "seller", "total", "commission_amount", "platform_fee"]
    )

    for sub_order in sub_orders:
        # Create escrow account for each sub-order
        escrow = frappe.get_doc({
            "doctype": "Escrow Account",
            "marketplace_order": order.name,
            "sub_order": sub_order.name,
            "payment_intent": intent.name,
            "seller": sub_order.seller,
            "buyer": order.buyer,
            "total_amount": flt(sub_order.total),
            "commission_amount": flt(sub_order.commission_amount),
            "platform_fee": flt(sub_order.platform_fee),
            "status": "Funds Held",
            "currency": intent.currency,
            "auto_release_enabled": 1,
            "auto_release_days": 7,  # Default 7 days after delivery
        })
        escrow.insert(ignore_permissions=True)

        # Update sub-order escrow reference
        frappe.db.set_value("Sub Order", sub_order.name, "escrow_account", escrow.name)

        # Add pending balance to seller
        _add_seller_pending_balance(sub_order.seller, escrow)


def _add_seller_pending_balance(seller: str, escrow):
    """Add escrow amount to seller's pending balance."""
    if not frappe.db.exists("Seller Balance", {"seller": seller}):
        # Create seller balance record
        balance = frappe.get_doc({
            "doctype": "Seller Balance",
            "seller": seller,
            "currency": escrow.currency,
            "available_balance": 0,
            "pending_balance": 0,
            "held_balance": 0,
        })
        balance.insert(ignore_permissions=True)

    balance = frappe.get_doc("Seller Balance", {"seller": seller})
    balance.add_earnings(
        amount=flt(escrow.net_amount_to_seller),
        order_name=escrow.sub_order,
        description=f"Order payment held in escrow: {escrow.name}"
    )


# =============================================================================
# INSTALLMENT OPTIONS
# =============================================================================


@frappe.whitelist()
def get_installment_options(
    amount: float,
    card_bin: str = None,
    gateway: str = "iyzico",
) -> Dict[str, Any]:
    """
    Get available installment options for a payment amount.

    Args:
        amount: Payment amount
        card_bin: First 6 digits of card (optional)
        gateway: Payment gateway

    Returns:
        dict: Available installment options with costs
    """
    check_rate_limit("installment_query")

    amount = flt(amount, 2)
    if amount <= 0:
        frappe.throw(_("Invalid amount"))

    try:
        gateway_client = _get_gateway_client(gateway)

        if card_bin:
            # Get installment options for specific card
            result = gateway_client.get_installment_info(
                price=amount,
                bin_number=card_bin,
            )

            installment_options = []
            for option in result.get("installment_details", []):
                installment_options.append({
                    "count": option.get("installment_number", 1),
                    "monthly_amount": option.get("installment_price"),
                    "total_amount": option.get("total_price"),
                    "interest_rate": option.get("installment_interest_rate", 0),
                    "formatted_monthly": _format_currency(option.get("installment_price")),
                    "formatted_total": _format_currency(option.get("total_price")),
                })

            return {
                "success": True,
                "base_amount": amount,
                "card_type": result.get("card_type"),
                "card_association": result.get("card_association"),
                "bank_name": result.get("bank_name"),
                "options": installment_options,
            }

        else:
            # Get general installment options
            options = []
            for i in [1, 2, 3, 4, 5, 6, 9, 12]:
                # Estimate interest rate (varies by card/bank)
                if i == 1:
                    interest = 0
                elif i <= 3:
                    interest = 0.015 * i  # ~1.5% per month
                elif i <= 6:
                    interest = 0.018 * i  # ~1.8% per month
                else:
                    interest = 0.02 * i  # ~2% per month

                total = amount * (1 + interest)
                monthly = total / i

                options.append({
                    "count": i,
                    "monthly_amount": flt(monthly, 2),
                    "total_amount": flt(total, 2),
                    "interest_rate": flt(interest * 100, 2),
                    "formatted_monthly": _format_currency(monthly),
                    "formatted_total": _format_currency(total),
                    "estimated": True,
                })

            return {
                "success": True,
                "base_amount": amount,
                "options": options,
                "note": _("Actual rates may vary by card and bank. Enter card number for exact rates."),
            }

    except Exception as e:
        frappe.log_error(str(e), "Get Installment Options Error")
        frappe.throw(_("Failed to get installment options"))


@frappe.whitelist()
def get_bin_info(card_bin: str, gateway: str = "iyzico") -> Dict[str, Any]:
    """
    Get card BIN (Bank Identification Number) information.

    Args:
        card_bin: First 6-8 digits of card number
        gateway: Payment gateway

    Returns:
        dict: Card information (bank, type, etc.)
    """
    check_rate_limit("installment_query")

    # Clean and validate BIN
    card_bin = card_bin.replace(" ", "").replace("-", "")
    if not card_bin.isdigit() or len(card_bin) < 6:
        frappe.throw(_("Invalid card BIN. Must be at least 6 digits."))

    card_bin = card_bin[:8]  # Use first 8 digits

    try:
        gateway_client = _get_gateway_client(gateway)
        result = gateway_client.get_bin_info(card_bin)

        return {
            "success": True,
            "bin": card_bin[:6] + "**",  # Mask for security
            "bank_name": result.get("bank_name"),
            "bank_code": result.get("bank_code"),
            "card_type": result.get("card_type"),  # Credit/Debit
            "card_association": result.get("card_association"),  # Visa/Mastercard/Troy
            "card_family": result.get("card_family"),
            "commercial": result.get("commercial", 0),
        }

    except Exception as e:
        frappe.log_error(str(e), "Get BIN Info Error")
        return {
            "success": False,
            "error": _("Could not retrieve card information"),
        }


# =============================================================================
# ESCROW MANAGEMENT
# =============================================================================


@frappe.whitelist()
def get_escrow_account(escrow_id: str) -> Dict[str, Any]:
    """
    Get escrow account details.

    Args:
        escrow_id: Escrow account ID or name

    Returns:
        dict: Escrow account details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find escrow
    filters = {"escrow_id": escrow_id}
    if not frappe.db.exists("Escrow Account", filters):
        filters = {"name": escrow_id}

    if not frappe.db.exists("Escrow Account", filters):
        frappe.throw(_("Escrow account not found"))

    escrow = frappe.get_doc("Escrow Account", filters)

    # Validate access - buyer or seller can view
    seller = get_current_seller()
    if escrow.buyer != user and escrow.seller != seller:
        if not frappe.has_permission("Escrow Account", "read"):
            frappe.throw(_("You are not authorized to view this escrow"))

    return {
        "escrow_id": escrow.escrow_id,
        "name": escrow.name,
        "order": escrow.marketplace_order,
        "sub_order": escrow.sub_order,
        "status": escrow.status,
        "total_amount": flt(escrow.total_amount),
        "held_amount": flt(escrow.held_amount),
        "released_amount": flt(escrow.released_amount),
        "refunded_amount": flt(escrow.refunded_amount),
        "net_amount_to_seller": flt(escrow.net_amount_to_seller),
        "currency": escrow.currency,
        "formatted_total": _format_currency(escrow.total_amount, escrow.currency),
        "formatted_held": _format_currency(escrow.held_amount, escrow.currency),
        "auto_release_enabled": cint(escrow.auto_release_enabled),
        "auto_release_days": cint(escrow.auto_release_days),
        "scheduled_release_date": str(escrow.scheduled_release_date) if escrow.scheduled_release_date else None,
        "delivery_confirmed_at": str(escrow.delivery_confirmed_at) if escrow.delivery_confirmed_at else None,
        "dispute_status": escrow.dispute_status,
        "created_at": str(escrow.created_at),
    }


@frappe.whitelist()
def confirm_delivery(escrow_id: str) -> Dict[str, Any]:
    """
    Confirm delivery and trigger escrow release (buyer action).

    Args:
        escrow_id: Escrow account ID or name

    Returns:
        dict: Updated escrow status
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find escrow
    filters = {"escrow_id": escrow_id}
    if not frappe.db.exists("Escrow Account", filters):
        filters = {"name": escrow_id}

    if not frappe.db.exists("Escrow Account", filters):
        frappe.throw(_("Escrow account not found"))

    escrow = frappe.get_doc("Escrow Account", filters)

    # Validate - only buyer can confirm
    if escrow.buyer != user:
        frappe.throw(_("Only the buyer can confirm delivery"))

    # Validate status
    if escrow.status not in ["Funds Held", "Partially Released"]:
        frappe.throw(_("Cannot confirm delivery for {0} escrow").format(escrow.status))

    # Confirm delivery
    escrow.confirm_delivery()

    # Release funds after confirmation (may have delay)
    escrow.approve_release()

    _log_payment_event(
        "Delivery Confirmed",
        escrow_account=escrow.name,
        order_name=escrow.sub_order,
        details={"released_amount": flt(escrow.held_amount)},
    )

    return {
        "success": True,
        "escrow_id": escrow.escrow_id,
        "status": escrow.status,
        "message": _("Delivery confirmed. Funds will be released to the seller."),
    }


@frappe.whitelist()
def open_escrow_dispute(
    escrow_id: str,
    reason: str,
    description: str = None,
    evidence: List[str] = None,
) -> Dict[str, Any]:
    """
    Open a dispute for an escrow account (buyer action).

    Args:
        escrow_id: Escrow account ID or name
        reason: Dispute reason code
        description: Detailed description
        evidence: List of file URLs as evidence

    Returns:
        dict: Dispute details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find escrow
    filters = {"escrow_id": escrow_id}
    if not frappe.db.exists("Escrow Account", filters):
        filters = {"name": escrow_id}

    if not frappe.db.exists("Escrow Account", filters):
        frappe.throw(_("Escrow account not found"))

    escrow = frappe.get_doc("Escrow Account", filters)

    # Validate - only buyer can open dispute
    if escrow.buyer != user:
        frappe.throw(_("Only the buyer can open a dispute"))

    # Validate status
    if escrow.status not in ["Funds Held", "Partially Released"]:
        frappe.throw(_("Cannot dispute {0} escrow").format(escrow.status))

    # Validate reason
    valid_reasons = [
        "Item Not Received",
        "Item Not As Described",
        "Item Damaged",
        "Wrong Item Received",
        "Quality Issue",
        "Counterfeit Item",
        "Other",
    ]
    if reason not in valid_reasons:
        frappe.throw(_("Invalid dispute reason"))

    # Open dispute
    escrow.open_dispute()
    escrow.db_set("dispute_reason", reason)
    escrow.db_set("dispute_description", description)
    escrow.db_set("dispute_opened_by", user)
    escrow.db_set("dispute_opened_at", now_datetime())

    if evidence:
        escrow.db_set("dispute_evidence", json.dumps(evidence))

    escrow.clear_cache()

    _log_payment_event(
        "Dispute Opened",
        escrow_account=escrow.name,
        order_name=escrow.sub_order,
        details={"reason": reason},
        severity="Warning",
    )

    return {
        "success": True,
        "escrow_id": escrow.escrow_id,
        "status": escrow.status,
        "dispute_status": "Opened",
        "message": _("Dispute has been opened. Our team will review and respond within 48 hours."),
    }


@frappe.whitelist()
def get_my_escrow_accounts(
    role: str = "buyer",
    status: str = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get escrow accounts for the current user.

    Args:
        role: "buyer" or "seller"
        status: Filter by status
        page: Page number
        page_size: Items per page

    Returns:
        dict: List of escrow accounts with pagination
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    filters = {}

    if role == "seller":
        seller = get_current_seller()
        if not seller:
            frappe.throw(_("You must be a seller"))
        filters["seller"] = seller
    else:
        filters["buyer"] = user

    if status:
        filters["status"] = status

    # Get total count
    total = frappe.db.count("Escrow Account", filters)

    # Get paginated results
    escrows = frappe.get_all(
        "Escrow Account",
        filters=filters,
        fields=[
            "name", "escrow_id", "marketplace_order", "sub_order",
            "status", "total_amount", "held_amount", "released_amount",
            "currency", "created_at", "scheduled_release_date",
            "dispute_status"
        ],
        order_by="created_at desc",
        start=(page - 1) * page_size,
        page_length=page_size,
    )

    return {
        "escrows": escrows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# =============================================================================
# SELLER BALANCE & PAYOUTS
# =============================================================================


@frappe.whitelist()
def get_seller_balance() -> Dict[str, Any]:
    """
    Get current seller's balance summary.

    Returns:
        dict: Balance details including available, pending, held amounts
    """
    check_rate_limit("balance_query")

    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    if not frappe.db.exists("Seller Balance", {"seller": seller}):
        # Create balance record if not exists
        balance = frappe.get_doc({
            "doctype": "Seller Balance",
            "seller": seller,
            "currency": "TRY",
            "available_balance": 0,
            "pending_balance": 0,
            "held_balance": 0,
        })
        balance.insert(ignore_permissions=True)

    balance = frappe.get_doc("Seller Balance", {"seller": seller})

    return {
        "seller": seller,
        "currency": balance.currency,
        "available_balance": flt(balance.available_balance),
        "pending_balance": flt(balance.pending_balance),
        "held_balance": flt(balance.held_balance),
        "reserved_balance": flt(balance.reserved_balance),
        "total_balance": flt(balance.total_balance),
        "formatted_available": _format_currency(balance.available_balance, balance.currency),
        "formatted_pending": _format_currency(balance.pending_balance, balance.currency),
        "formatted_held": _format_currency(balance.held_balance, balance.currency),
        "formatted_total": _format_currency(balance.total_balance, balance.currency),
        "lifetime_earnings": flt(balance.lifetime_earnings),
        "lifetime_payouts": flt(balance.lifetime_payouts),
        "lifetime_refunds": flt(balance.lifetime_refunds),
        "payout_frequency": balance.payout_frequency,
        "next_payout_date": str(balance.next_payout_date) if balance.next_payout_date else None,
        "minimum_payout_threshold": flt(balance.minimum_payout_threshold),
        "can_request_payout": flt(balance.available_balance) >= flt(balance.minimum_payout_threshold),
        "last_updated": str(balance.last_updated) if balance.last_updated else None,
    }


@frappe.whitelist()
def get_balance_transactions(
    page: int = 1,
    page_size: int = 20,
    transaction_type: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """
    Get seller's balance transaction history.

    Args:
        page: Page number
        page_size: Items per page
        transaction_type: Filter by type (Earnings, Payout, Refund, etc.)
        start_date: Start date filter
        end_date: End date filter

    Returns:
        dict: Transaction list with pagination
    """
    check_rate_limit("balance_query")

    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    if not frappe.db.exists("Seller Balance", {"seller": seller}):
        return {
            "transactions": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
        }

    balance = frappe.get_doc("Seller Balance", {"seller": seller})

    # Parse recent transactions from JSON
    transactions = json.loads(balance.recent_transactions or "[]")

    # Apply filters
    if transaction_type:
        transactions = [t for t in transactions if t.get("type") == transaction_type]

    if start_date:
        start = getdate(start_date)
        transactions = [t for t in transactions if getdate(t.get("date", "2000-01-01")) >= start]

    if end_date:
        end = getdate(end_date)
        transactions = [t for t in transactions if getdate(t.get("date", "2099-12-31")) <= end]

    # Sort by date descending
    transactions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Paginate
    total = len(transactions)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated = transactions[start_idx:end_idx]

    return {
        "transactions": paginated,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@frappe.whitelist()
def request_payout(
    amount: float = None,
    payout_method: str = "Bank Transfer",
) -> Dict[str, Any]:
    """
    Request a payout of available balance.

    Args:
        amount: Amount to withdraw (defaults to full available balance)
        payout_method: Payout method (Bank Transfer, etc.)

    Returns:
        dict: Payout request details
    """
    check_rate_limit("payout_request")

    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    if not frappe.db.exists("Seller Balance", {"seller": seller}):
        frappe.throw(_("No balance record found"))

    balance = frappe.get_doc("Seller Balance", {"seller": seller})

    # Validate IBAN is set
    if not balance.iban:
        frappe.throw(_("Please add your bank account (IBAN) before requesting a payout"))

    # Determine payout amount
    if amount:
        amount = flt(amount, 2)
        if amount <= 0:
            frappe.throw(_("Invalid payout amount"))
        if amount > flt(balance.available_balance):
            frappe.throw(_("Requested amount exceeds available balance"))
    else:
        amount = flt(balance.available_balance)

    # Check minimum threshold
    min_threshold = flt(balance.minimum_payout_threshold) or 100
    if amount < min_threshold:
        frappe.throw(
            _("Minimum payout amount is {0}").format(_format_currency(min_threshold, balance.currency))
        )

    # Check if there's already a pending payout
    pending = frappe.db.exists(
        "Seller Payout",
        {"seller": seller, "status": ["in", ["Pending", "Processing"]]}
    )
    if pending:
        frappe.throw(_("You already have a pending payout request"))

    # Create payout request
    try:
        payout = frappe.get_doc({
            "doctype": "Seller Payout",
            "seller": seller,
            "seller_balance": balance.name,
            "amount": amount,
            "currency": balance.currency,
            "payout_method": payout_method,
            "bank_account": balance.iban,
            "bank_name": balance.bank_name,
            "account_holder_name": balance.account_holder_name,
            "status": "Pending",
            "requested_at": now_datetime(),
        })
        payout.insert()

        # Reserve the amount
        balance.reserve_for_payout(amount, payout.name)

        _log_payment_event(
            "Payout Requested",
            details={
                "seller": seller,
                "amount": amount,
                "payout_id": payout.name,
            },
        )

        return {
            "success": True,
            "payout_id": payout.name,
            "amount": amount,
            "formatted_amount": _format_currency(amount, balance.currency),
            "status": "Pending",
            "estimated_arrival": str(add_days(nowdate(), 3)),
            "message": _("Payout request submitted. Funds will be transferred within 1-3 business days."),
        }

    except Exception as e:
        frappe.log_error(str(e), "Payout Request Error")
        frappe.throw(_("Failed to create payout request"))


@frappe.whitelist()
def get_payout_history(
    page: int = 1,
    page_size: int = 20,
    status: str = None,
) -> Dict[str, Any]:
    """
    Get seller's payout history.

    Args:
        page: Page number
        page_size: Items per page
        status: Filter by status

    Returns:
        dict: Payout list with pagination
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    filters = {"seller": seller}
    if status:
        filters["status"] = status

    # Check if Seller Payout DocType exists
    if not frappe.db.exists("DocType", "Seller Payout"):
        return {
            "payouts": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "message": _("Payout history not available"),
        }

    total = frappe.db.count("Seller Payout", filters)

    payouts = frappe.get_all(
        "Seller Payout",
        filters=filters,
        fields=[
            "name", "amount", "currency", "status",
            "payout_method", "bank_account", "bank_name",
            "requested_at", "processed_at", "completed_at",
            "failure_reason", "reference_number"
        ],
        order_by="requested_at desc",
        start=(page - 1) * page_size,
        page_length=page_size,
    )

    # Format amounts
    for payout in payouts:
        payout["formatted_amount"] = _format_currency(payout["amount"], payout["currency"])

    return {
        "payouts": payouts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@frappe.whitelist()
def update_payout_settings(
    iban: str = None,
    bank_name: str = None,
    account_holder_name: str = None,
    payout_frequency: str = None,
    minimum_threshold: float = None,
) -> Dict[str, Any]:
    """
    Update seller's payout settings.

    Args:
        iban: Bank IBAN
        bank_name: Bank name
        account_holder_name: Account holder name
        payout_frequency: Payout frequency (Weekly, Biweekly, Monthly)
        minimum_threshold: Minimum payout threshold

    Returns:
        dict: Updated settings
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    if not frappe.db.exists("Seller Balance", {"seller": seller}):
        # Create balance record
        balance = frappe.get_doc({
            "doctype": "Seller Balance",
            "seller": seller,
            "currency": "TRY",
        })
        balance.insert(ignore_permissions=True)
    else:
        balance = frappe.get_doc("Seller Balance", {"seller": seller})

    # Update fields
    if iban is not None:
        # Validate Turkish IBAN
        iban = iban.replace(" ", "").upper()
        if not iban.startswith("TR") or len(iban) != 26:
            frappe.throw(_("Invalid Turkish IBAN. Must be 26 characters starting with TR."))
        balance.iban = iban

    if bank_name is not None:
        balance.bank_name = bank_name

    if account_holder_name is not None:
        balance.account_holder_name = account_holder_name

    if payout_frequency is not None:
        if payout_frequency not in ["Weekly", "Biweekly", "Monthly", "On Demand"]:
            frappe.throw(_("Invalid payout frequency"))
        balance.payout_frequency = payout_frequency

    if minimum_threshold is not None:
        min_threshold = flt(minimum_threshold)
        if min_threshold < 0:
            frappe.throw(_("Minimum threshold cannot be negative"))
        balance.minimum_payout_threshold = min_threshold

    balance.save()

    return {
        "success": True,
        "iban": balance.iban,
        "bank_name": balance.bank_name,
        "account_holder_name": balance.account_holder_name,
        "payout_frequency": balance.payout_frequency,
        "minimum_payout_threshold": flt(balance.minimum_payout_threshold),
        "message": _("Payout settings updated successfully"),
    }


# =============================================================================
# REFUNDS
# =============================================================================


@frappe.whitelist()
def request_refund(
    order_name: str = None,
    sub_order_name: str = None,
    payment_intent_id: str = None,
    amount: float = None,
    reason: str = None,
    description: str = None,
) -> Dict[str, Any]:
    """
    Request a refund for a payment.

    Args:
        order_name: Marketplace Order name
        sub_order_name: Sub Order name (for partial refunds)
        payment_intent_id: Payment Intent ID (alternative to order)
        amount: Refund amount (defaults to full amount)
        reason: Refund reason
        description: Detailed description

    Returns:
        dict: Refund request details
    """
    check_rate_limit("refund_request")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find the payment
    intent = None
    if payment_intent_id:
        filters = {"intent_id": payment_intent_id}
        if not frappe.db.exists("Payment Intent", filters):
            filters = {"name": payment_intent_id}
        if frappe.db.exists("Payment Intent", filters):
            intent = frappe.get_doc("Payment Intent", filters)
    elif order_name:
        intent = frappe.db.get_value(
            "Payment Intent",
            {"marketplace_order": order_name, "status": "Paid"},
            "name"
        )
        if intent:
            intent = frappe.get_doc("Payment Intent", intent)

    if not intent:
        frappe.throw(_("No paid payment found for refund"))

    # Validate - only buyer or admin can request refund
    if intent.buyer != user and not frappe.has_permission("Payment Intent", "write"):
        frappe.throw(_("You are not authorized to request a refund"))

    # Validate status
    if intent.status not in ["Paid", "Captured", "Partially Refunded"]:
        frappe.throw(_("Cannot refund {0} payment").format(intent.status))

    # Calculate refund amount
    max_refundable = flt(intent.amount) - flt(intent.refunded_amount or 0)
    if amount:
        amount = flt(amount, 2)
        if amount <= 0:
            frappe.throw(_("Invalid refund amount"))
        if amount > max_refundable:
            frappe.throw(
                _("Refund amount cannot exceed {0}").format(_format_currency(max_refundable, intent.currency))
            )
    else:
        amount = max_refundable

    # Validate reason
    valid_reasons = [
        "Duplicate Payment",
        "Fraudulent",
        "Customer Request",
        "Order Cancelled",
        "Item Not Received",
        "Item Not As Described",
        "Quality Issue",
        "Other",
    ]
    if reason and reason not in valid_reasons:
        frappe.throw(_("Invalid refund reason"))

    try:
        # Process refund via gateway
        gateway = _get_gateway_client(intent.payment_gateway)

        result = gateway.create_refund(
            conversation_id=f"{intent.name}_refund_{secrets.token_hex(4)}",
            payment_id=intent.gateway_payment_id,
            amount=amount,
        )

        if result.get("status") == "success":
            # Update payment intent
            new_refunded = flt(intent.refunded_amount or 0) + amount
            intent.db_set("refunded_amount", new_refunded)

            if new_refunded >= flt(intent.amount):
                intent.db_set("status", "Refunded")
            else:
                intent.db_set("status", "Partially Refunded")

            intent.db_set("refund_reason", reason)
            intent.db_set("last_refund_at", now_datetime())
            intent.clear_cache()

            # Update escrow if exists
            if sub_order_name:
                escrow = frappe.db.get_value("Escrow Account", {"sub_order": sub_order_name})
                if escrow:
                    escrow_doc = frappe.get_doc("Escrow Account", escrow)
                    escrow_doc.refund_funds(amount)

            _log_payment_event(
                "Refund Processed",
                payment_intent=intent.name,
                order_name=intent.marketplace_order,
                details={"amount": amount, "reason": reason},
            )

            return {
                "success": True,
                "refund_id": result.get("refund_id"),
                "amount": amount,
                "formatted_amount": _format_currency(amount, intent.currency),
                "payment_status": intent.status,
                "total_refunded": new_refunded,
                "message": _("Refund of {0} processed successfully").format(
                    _format_currency(amount, intent.currency)
                ),
            }

        else:
            _log_payment_event(
                "Refund Failed",
                payment_intent=intent.name,
                details=result,
                severity="Warning",
            )

            return {
                "success": False,
                "error_code": result.get("error_code"),
                "error_message": result.get("error_message"),
            }

    except Exception as e:
        frappe.log_error(str(e), "Refund Processing Error")
        frappe.throw(_("Refund processing failed: {0}").format(str(e)))


@frappe.whitelist()
def get_refund_status(payment_intent_id: str) -> Dict[str, Any]:
    """
    Get refund status for a payment.

    Args:
        payment_intent_id: Payment Intent ID

    Returns:
        dict: Refund status details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Find payment
    filters = {"intent_id": payment_intent_id}
    if not frappe.db.exists("Payment Intent", filters):
        filters = {"name": payment_intent_id}

    if not frappe.db.exists("Payment Intent", filters):
        frappe.throw(_("Payment not found"))

    intent = frappe.get_doc("Payment Intent", filters)

    # Validate access
    if intent.buyer != user and not frappe.has_permission("Payment Intent", "read"):
        frappe.throw(_("You are not authorized to view this payment"))

    return {
        "payment_intent_id": intent.intent_id,
        "payment_status": intent.status,
        "original_amount": flt(intent.amount),
        "refunded_amount": flt(intent.refunded_amount or 0),
        "remaining_amount": flt(intent.amount) - flt(intent.refunded_amount or 0),
        "formatted_original": _format_currency(intent.amount, intent.currency),
        "formatted_refunded": _format_currency(intent.refunded_amount or 0, intent.currency),
        "refund_reason": intent.refund_reason,
        "last_refund_at": str(intent.last_refund_at) if intent.last_refund_at else None,
        "is_fully_refunded": intent.status == "Refunded",
    }


# =============================================================================
# WEBHOOKS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def webhook_iyzico(**kwargs) -> Dict[str, Any]:
    """
    Handle iyzico webhook notifications.

    Returns:
        dict: Webhook processing result
    """
    check_rate_limit("webhook", identifier="iyzico_webhook")

    try:
        from tr_tradehub.integrations.iyzico import IyzicoClient

        client = IyzicoClient()

        # Verify webhook signature
        if not client.verify_webhook_signature(kwargs):
            frappe.log_error("Invalid iyzico webhook signature", "Webhook Error")
            return {"status": "error", "message": "Invalid signature"}

        event_type = kwargs.get("iyziEventType")
        payment_id = kwargs.get("paymentId")
        conversation_id = kwargs.get("paymentConversationId")

        _log_payment_event(
            f"Webhook: {event_type}",
            payment_intent=conversation_id,
            details=kwargs,
        )

        # Handle different event types
        if event_type == "CREDIT_CARD_PAYMENT":
            # Payment completed
            if conversation_id:
                intent = frappe.db.get_value("Payment Intent", {"name": conversation_id})
                if intent:
                    intent_doc = frappe.get_doc("Payment Intent", intent)
                    if kwargs.get("status") == "SUCCESS":
                        intent_doc.mark_paid(payment_id=payment_id)
                    else:
                        intent_doc.mark_failed(
                            error_code=kwargs.get("errorCode"),
                            error_message=kwargs.get("errorMessage"),
                        )

        elif event_type == "REFUND":
            # Refund notification
            if payment_id:
                intent = frappe.db.get_value(
                    "Payment Intent",
                    {"gateway_payment_id": payment_id}
                )
                if intent:
                    # Update refund status
                    pass

        return {"status": "success"}

    except Exception as e:
        frappe.log_error(str(e), "iyzico Webhook Error")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def webhook_paytr(**kwargs) -> str:
    """
    Handle PayTR webhook notifications.

    Returns:
        str: "OK" on success
    """
    check_rate_limit("webhook", identifier="paytr_webhook")

    try:
        from tr_tradehub.integrations.paytr import PayTRClient

        client = PayTRClient()

        # Verify callback signature
        if not client.verify_callback_signature(kwargs):
            frappe.log_error("Invalid PayTR callback signature", "Webhook Error")
            return "INVALID_SIGNATURE"

        merchant_oid = kwargs.get("merchant_oid")
        status = kwargs.get("status")

        _log_payment_event(
            f"PayTR Callback: {status}",
            payment_intent=merchant_oid,
            details=kwargs,
        )

        if merchant_oid:
            intent = frappe.db.get_value("Payment Intent", {"name": merchant_oid})
            if intent:
                intent_doc = frappe.get_doc("Payment Intent", intent)

                if status == "success":
                    intent_doc.mark_paid(
                        payment_id=kwargs.get("payment_id"),
                        reference=kwargs.get("transaction_id"),
                    )

                    # Create escrow if order exists
                    if intent_doc.marketplace_order:
                        _create_escrow_for_order(intent_doc)

                else:
                    intent_doc.mark_failed(
                        error_code=kwargs.get("failed_reason_code"),
                        error_message=kwargs.get("failed_reason_msg"),
                    )

        return "OK"

    except Exception as e:
        frappe.log_error(str(e), "PayTR Webhook Error")
        return "ERROR"


# =============================================================================
# STATISTICS & REPORTING
# =============================================================================


@frappe.whitelist()
def get_payment_statistics(
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """
    Get payment statistics for the current user.

    Args:
        start_date: Start date filter
        end_date: End date filter

    Returns:
        dict: Payment statistics
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    filters = {"buyer": user}

    if start_date:
        filters["created_at"] = [">=", start_date]
    if end_date:
        if "created_at" in filters:
            filters["created_at"] = ["between", [start_date, end_date]]
        else:
            filters["created_at"] = ["<=", end_date]

    # Get payment stats
    payments = frappe.get_all(
        "Payment Intent",
        filters=filters,
        fields=["status", "amount", "currency", "created_at"]
    )

    total_paid = sum(flt(p["amount"]) for p in payments if p["status"] == "Paid")
    total_pending = sum(flt(p["amount"]) for p in payments if p["status"] in ["Created", "Pending", "Processing"])
    total_failed = sum(flt(p["amount"]) for p in payments if p["status"] == "Failed")

    status_counts = {}
    for p in payments:
        status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1

    return {
        "total_payments": len(payments),
        "total_paid": total_paid,
        "total_pending": total_pending,
        "total_failed": total_failed,
        "formatted_paid": _format_currency(total_paid),
        "formatted_pending": _format_currency(total_pending),
        "status_breakdown": status_counts,
    }


@frappe.whitelist()
def get_seller_payment_statistics(
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """
    Get payment statistics for the current seller.

    Args:
        start_date: Start date filter
        end_date: End date filter

    Returns:
        dict: Seller payment statistics
    """
    seller = get_current_seller()
    if not seller:
        frappe.throw(_("You must be a seller"))

    # Get escrow stats
    filters = {"seller": seller}
    if start_date:
        filters["created_at"] = [">=", start_date]
    if end_date:
        if "created_at" in filters:
            filters["created_at"] = ["between", [start_date, end_date]]
        else:
            filters["created_at"] = ["<=", end_date]

    escrows = frappe.get_all(
        "Escrow Account",
        filters=filters,
        fields=["status", "total_amount", "released_amount", "refunded_amount", "net_amount_to_seller"]
    )

    total_sales = sum(flt(e["total_amount"]) for e in escrows)
    total_released = sum(flt(e["released_amount"]) for e in escrows)
    total_pending = sum(flt(e["total_amount"]) - flt(e["released_amount"]) - flt(e["refunded_amount"])
                       for e in escrows if e["status"] in ["Funds Held", "Partially Released"])
    total_refunded = sum(flt(e["refunded_amount"]) for e in escrows)
    total_net = sum(flt(e["net_amount_to_seller"]) for e in escrows if e["status"] == "Released")

    status_counts = {}
    for e in escrows:
        status_counts[e["status"]] = status_counts.get(e["status"], 0) + 1

    # Get balance info
    balance_info = {}
    if frappe.db.exists("Seller Balance", {"seller": seller}):
        balance = frappe.get_doc("Seller Balance", {"seller": seller})
        balance_info = {
            "available_balance": flt(balance.available_balance),
            "pending_balance": flt(balance.pending_balance),
            "held_balance": flt(balance.held_balance),
        }

    return {
        "total_orders": len(escrows),
        "total_sales": total_sales,
        "total_released": total_released,
        "total_pending": total_pending,
        "total_refunded": total_refunded,
        "total_net_earnings": total_net,
        "formatted_sales": _format_currency(total_sales),
        "formatted_released": _format_currency(total_released),
        "formatted_pending": _format_currency(total_pending),
        "formatted_net": _format_currency(total_net),
        "escrow_status_breakdown": status_counts,
        "balance": balance_info,
    }


@frappe.whitelist()
def get_commission_breakdown(order_name: str) -> Dict[str, Any]:
    """
    Get commission breakdown for an order.

    Args:
        order_name: Marketplace Order or Sub Order name

    Returns:
        dict: Commission breakdown details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in"))

    # Try as sub-order first
    if frappe.db.exists("Sub Order", order_name):
        sub_order = frappe.get_doc("Sub Order", order_name)

        # Validate access
        seller = get_current_seller()
        if sub_order.seller != seller:
            order = frappe.get_doc("Marketplace Order", sub_order.marketplace_order)
            if order.buyer != user:
                frappe.throw(_("You are not authorized to view this"))

        return {
            "order_name": sub_order.name,
            "order_type": "Sub Order",
            "subtotal": flt(sub_order.subtotal),
            "shipping": flt(sub_order.shipping_amount),
            "tax": flt(sub_order.tax_amount),
            "total": flt(sub_order.total),
            "commission_rate": flt(sub_order.commission_rate),
            "commission_amount": flt(sub_order.commission_amount),
            "platform_fee": flt(sub_order.platform_fee),
            "processing_fee": flt(sub_order.processing_fee or 0),
            "total_fees": flt(sub_order.commission_amount) + flt(sub_order.platform_fee) + flt(sub_order.processing_fee or 0),
            "net_to_seller": flt(sub_order.total) - flt(sub_order.commission_amount) - flt(sub_order.platform_fee),
            "currency": sub_order.currency or "TRY",
        }

    # Try as marketplace order
    if frappe.db.exists("Marketplace Order", order_name):
        order = frappe.get_doc("Marketplace Order", order_name)

        # Validate access
        if order.buyer != user and not frappe.has_permission("Marketplace Order", "read"):
            frappe.throw(_("You are not authorized to view this"))

        # Get all sub-orders
        sub_orders = frappe.get_all(
            "Sub Order",
            filters={"marketplace_order": order.name},
            fields=["name", "seller", "total", "commission_amount", "platform_fee"]
        )

        total_commission = sum(flt(s["commission_amount"]) for s in sub_orders)
        total_platform_fee = sum(flt(s["platform_fee"]) for s in sub_orders)

        return {
            "order_name": order.name,
            "order_type": "Marketplace Order",
            "grand_total": flt(order.grand_total),
            "total_commission": total_commission,
            "total_platform_fee": total_platform_fee,
            "sub_orders_count": len(sub_orders),
            "sub_order_breakdown": sub_orders,
            "currency": order.currency or "TRY",
        }

    frappe.throw(_("Order not found"))
