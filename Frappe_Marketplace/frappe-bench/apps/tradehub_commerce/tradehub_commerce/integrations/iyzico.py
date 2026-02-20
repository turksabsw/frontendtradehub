# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""iyzico Payment Gateway Integration for TradeHub Commerce

iyzico is a leading Turkish payment gateway that supports:
- Credit/Debit card payments
- 3D Secure authentication
- Installment payments (up to 12 months)
- Checkout form integration
- Marketplace payment splitting
- BKM Express integration

This module provides methods to:
- Initialize checkout form
- Process payment callbacks
- Handle refunds and cancellations
- Query payment status
- Manage installment options
"""

import hashlib
import base64
import json
import random
import string

import frappe
from frappe import _
from frappe.utils import cint, flt, now


class IyzicoIntegration:
    """iyzico Payment Gateway Integration Class.

    Handles all iyzico API interactions for payment processing.
    """

    # iyzico API endpoints
    SANDBOX_URL = "https://sandbox-api.iyzipay.com"
    PRODUCTION_URL = "https://api.iyzipay.com"
    CHECKOUT_ENDPOINT = "/payment/iyzipos/checkoutform/initialize/auth/ecom"
    REFUND_ENDPOINT = "/payment/refund"
    CANCEL_ENDPOINT = "/payment/cancel"
    STATUS_ENDPOINT = "/payment/iyzipos/checkoutform/auth/ecom/detail"
    INSTALLMENT_ENDPOINT = "/payment/iyzipos/installment"

    def __init__(self):
        """Initialize iyzico integration with credentials from settings."""
        self.settings = self._get_settings()
        self.api_key = self.settings.get("iyzico_api_key", "")
        self.secret_key = self.settings.get("iyzico_secret_key", "")
        self.test_mode = self.settings.get("iyzico_test_mode", 1)
        self.base_url = self.SANDBOX_URL if self.test_mode else self.PRODUCTION_URL

    def _get_settings(self):
        """Get iyzico settings from the database.

        Returns:
            dict: iyzico configuration settings
        """
        try:
            # Try to get from Payment Method DocType
            if frappe.db.exists("Payment Method", {"provider": "iyzico"}):
                payment_method = frappe.get_doc("Payment Method", {"provider": "iyzico"})
                return {
                    "iyzico_api_key": payment_method.get("api_key", ""),
                    "iyzico_secret_key": payment_method.get("api_secret", ""),
                    "iyzico_test_mode": payment_method.get("test_mode", 1)
                }
        except Exception:
            pass

        # Return empty settings if not configured
        return {
            "iyzico_api_key": "",
            "iyzico_secret_key": "",
            "iyzico_test_mode": 1
        }

    def _generate_random_string(self, length=16):
        """Generate a random string for conversation ID.

        Args:
            length: Length of the random string

        Returns:
            str: Random alphanumeric string
        """
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))

    def _generate_authorization_header(self, request_body):
        """Generate authorization header for iyzico API.

        Args:
            request_body: JSON request body string

        Returns:
            str: Authorization header value
        """
        if not self.api_key or not self.secret_key:
            frappe.throw(_("iyzico API credentials are required"))

        random_header_value = self._generate_random_string()
        hash_string = f"{self.api_key}{random_header_value}{self.secret_key}{request_body}"
        hash_value = hashlib.sha1(hash_string.encode("utf-8")).digest()
        hash_base64 = base64.b64encode(hash_value).decode("utf-8")

        return f"IYZWS {self.api_key}:{hash_base64}"

    def _generate_pki_string(self, data):
        """Generate PKI string from request data for hash calculation.

        Args:
            data: Dictionary of request data

        Returns:
            str: PKI formatted string
        """
        pki_parts = []
        for key, value in data.items():
            if value is not None:
                if isinstance(value, (list, dict)):
                    pki_parts.append(f"{key}={json.dumps(value)}")
                else:
                    pki_parts.append(f"{key}={value}")
        return "[" + ",".join(pki_parts) + "]"

    def initialize_checkout(self, payment_intent, basket_items, buyer_info, billing_address, shipping_address=None):
        """Initialize iyzico checkout form.

        Args:
            payment_intent: Payment Intent document
            basket_items: List of items in the basket
            buyer_info: Dictionary containing buyer information
            billing_address: Billing address dictionary
            shipping_address: Shipping address dictionary (optional)

        Returns:
            dict: Response containing checkout form token and page URL
        """
        if not self.api_key:
            return {"success": False, "error": _("iyzico is not configured")}

        try:
            conversation_id = self._generate_random_string()

            # Prepare basket items in iyzico format
            iyzico_basket = []
            for item in basket_items:
                iyzico_basket.append({
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "category1": item.get("category", "General"),
                    "itemType": item.get("type", "PHYSICAL"),
                    "price": str(flt(item.get("price", 0), 2))
                })

            # Prepare buyer information
            iyzico_buyer = {
                "id": buyer_info.get("id", ""),
                "name": buyer_info.get("first_name", ""),
                "surname": buyer_info.get("last_name", ""),
                "gsmNumber": buyer_info.get("phone", ""),
                "email": buyer_info.get("email", ""),
                "identityNumber": buyer_info.get("identity_number", "11111111111"),
                "lastLoginDate": buyer_info.get("last_login", now()[:19].replace("T", " ")),
                "registrationDate": buyer_info.get("registration_date", now()[:19].replace("T", " ")),
                "registrationAddress": buyer_info.get("address", ""),
                "ip": buyer_info.get("ip_address", "127.0.0.1"),
                "city": buyer_info.get("city", ""),
                "country": buyer_info.get("country", "Turkey"),
                "zipCode": buyer_info.get("zip_code", "")
            }

            # Prepare billing address
            iyzico_billing = {
                "contactName": billing_address.get("name", ""),
                "city": billing_address.get("city", ""),
                "country": billing_address.get("country", "Turkey"),
                "address": billing_address.get("address", ""),
                "zipCode": billing_address.get("zip_code", "")
            }

            # Prepare shipping address (use billing if not provided)
            iyzico_shipping = {
                "contactName": (shipping_address or billing_address).get("name", ""),
                "city": (shipping_address or billing_address).get("city", ""),
                "country": (shipping_address or billing_address).get("country", "Turkey"),
                "address": (shipping_address or billing_address).get("address", ""),
                "zipCode": (shipping_address or billing_address).get("zip_code", "")
            }

            # Prepare request data
            request_data = {
                "locale": buyer_info.get("locale", "tr"),
                "conversationId": conversation_id,
                "price": str(flt(payment_intent.amount, 2)),
                "paidPrice": str(flt(payment_intent.amount, 2)),
                "currency": payment_intent.currency or "TRY",
                "basketId": payment_intent.name,
                "paymentGroup": "PRODUCT",
                "callbackUrl": buyer_info.get("callback_url", ""),
                "enabledInstallments": [1, 2, 3, 6, 9, 12],
                "buyer": iyzico_buyer,
                "shippingAddress": iyzico_shipping,
                "billingAddress": iyzico_billing,
                "basketItems": iyzico_basket
            }

            # In a real implementation, this would make an HTTP request to iyzico
            frappe.logger().info(
                f"iyzico checkout initialized for {payment_intent.name}"
            )

            # Update Payment Intent with conversation ID
            payment_intent.iyzico_conversation_id = conversation_id
            payment_intent.flags.ignore_validate = True
            payment_intent.save()

            return {
                "success": True,
                "conversation_id": conversation_id,
                "basket_id": payment_intent.name,
                "request_data": request_data
            }

        except Exception as e:
            frappe.log_error(
                f"iyzico checkout initialization failed: {str(e)}",
                "iyzico Integration Error"
            )
            return {"success": False, "error": str(e)}

    def process_callback(self, callback_data):
        """Process iyzico payment callback.

        Args:
            callback_data: Dictionary containing callback parameters from iyzico

        Returns:
            dict: Processing result with success status
        """
        try:
            token = callback_data.get("token")
            conversation_id = callback_data.get("conversationId")

            if not token:
                return {"success": False, "error": "Token is required"}

            # Prepare request to retrieve payment result
            request_data = {
                "locale": "tr",
                "conversationId": conversation_id,
                "token": token
            }

            # In a real implementation, this would make an HTTP request to iyzico
            # to retrieve the full payment result

            frappe.logger().info(
                f"iyzico callback received for conversation {conversation_id}"
            )

            # Find Payment Intent by conversation ID
            payment_intents = frappe.get_all(
                "Payment Intent",
                filters={"iyzico_conversation_id": conversation_id},
                limit=1
            )

            if not payment_intents:
                return {"success": False, "error": "Payment Intent not found"}

            payment_intent = frappe.get_doc("Payment Intent", payment_intents[0].name)

            # Update based on callback status
            status = callback_data.get("status", "")
            if status == "success":
                payment_intent.status = "Completed"
                payment_intent.payment_reference = callback_data.get("paymentId", "")
                payment_intent.completed_at = now()
            else:
                payment_intent.status = "Failed"
                payment_intent.failure_reason = callback_data.get("errorMessage", "")

            payment_intent.callback_data = json.dumps(callback_data)
            payment_intent.flags.ignore_validate = True
            payment_intent.save()

            return {
                "success": True,
                "status": payment_intent.status,
                "payment_intent": payment_intent.name
            }

        except Exception as e:
            frappe.log_error(
                f"iyzico callback processing failed: {str(e)}",
                "iyzico Integration Error"
            )
            return {"success": False, "error": str(e)}

    def process_refund(self, payment_intent, refund_amount=None, reason=None):
        """Process a refund through iyzico.

        Args:
            payment_intent: Payment Intent document to refund
            refund_amount: Amount to refund (defaults to full amount)
            reason: Reason for refund

        Returns:
            dict: Refund result with success status
        """
        if not self.api_key:
            return {"success": False, "error": _("iyzico is not configured")}

        try:
            conversation_id = self._generate_random_string()
            payment_id = payment_intent.payment_reference

            if not payment_id:
                return {"success": False, "error": "Payment reference not found"}

            amount = flt(refund_amount or payment_intent.amount, 2)

            # Prepare refund request
            request_data = {
                "locale": "tr",
                "conversationId": conversation_id,
                "paymentTransactionId": payment_id,
                "price": str(amount),
                "currency": payment_intent.currency or "TRY",
                "ip": "127.0.0.1"
            }

            # In a real implementation, this would make an HTTP request to iyzico
            frappe.logger().info(
                f"iyzico refund request prepared for {payment_intent.name}: {amount} TRY"
            )

            # Update Payment Intent status
            payment_intent.status = "Refund Pending"
            payment_intent.refund_amount = amount
            payment_intent.refund_reason = reason
            payment_intent.refund_requested_at = now()
            payment_intent.refund_conversation_id = conversation_id
            payment_intent.flags.ignore_validate = True
            payment_intent.save()

            return {
                "success": True,
                "conversation_id": conversation_id,
                "refund_amount": amount,
                "request_data": request_data
            }

        except Exception as e:
            frappe.log_error(
                f"iyzico refund failed: {str(e)}",
                "iyzico Integration Error"
            )
            return {"success": False, "error": str(e)}

    def cancel_payment(self, payment_intent, reason=None):
        """Cancel a payment through iyzico.

        Args:
            payment_intent: Payment Intent document to cancel
            reason: Reason for cancellation

        Returns:
            dict: Cancellation result with success status
        """
        if not self.api_key:
            return {"success": False, "error": _("iyzico is not configured")}

        try:
            conversation_id = self._generate_random_string()
            payment_id = payment_intent.payment_reference

            if not payment_id:
                return {"success": False, "error": "Payment reference not found"}

            # Prepare cancel request
            request_data = {
                "locale": "tr",
                "conversationId": conversation_id,
                "paymentId": payment_id,
                "ip": "127.0.0.1"
            }

            # In a real implementation, this would make an HTTP request to iyzico
            frappe.logger().info(
                f"iyzico cancel request prepared for {payment_intent.name}"
            )

            # Update Payment Intent status
            payment_intent.status = "Cancelled"
            payment_intent.cancellation_reason = reason
            payment_intent.cancelled_at = now()
            payment_intent.flags.ignore_validate = True
            payment_intent.save()

            return {
                "success": True,
                "conversation_id": conversation_id,
                "request_data": request_data
            }

        except Exception as e:
            frappe.log_error(
                f"iyzico cancellation failed: {str(e)}",
                "iyzico Integration Error"
            )
            return {"success": False, "error": str(e)}

    def get_installment_info(self, bin_number, price):
        """Get installment options for a card BIN.

        Args:
            bin_number: First 6 digits of the card number
            price: Total price for the payment

        Returns:
            dict: Available installment options
        """
        if not self.api_key:
            return {"success": False, "error": _("iyzico is not configured")}

        try:
            conversation_id = self._generate_random_string()

            # Prepare installment inquiry request
            request_data = {
                "locale": "tr",
                "conversationId": conversation_id,
                "binNumber": bin_number,
                "price": str(flt(price, 2))
            }

            # In a real implementation, this would make an HTTP request to iyzico
            frappe.logger().info(
                f"iyzico installment inquiry for BIN {bin_number[:6]}***"
            )

            # Return mock installment options for development
            return {
                "success": True,
                "conversation_id": conversation_id,
                "installment_options": [
                    {"installment": 1, "total_price": price, "installment_price": price},
                    {"installment": 2, "total_price": price * 1.02, "installment_price": (price * 1.02) / 2},
                    {"installment": 3, "total_price": price * 1.04, "installment_price": (price * 1.04) / 3},
                    {"installment": 6, "total_price": price * 1.08, "installment_price": (price * 1.08) / 6},
                    {"installment": 9, "total_price": price * 1.12, "installment_price": (price * 1.12) / 9},
                    {"installment": 12, "total_price": price * 1.16, "installment_price": (price * 1.16) / 12}
                ],
                "request_data": request_data
            }

        except Exception as e:
            frappe.log_error(
                f"iyzico installment inquiry failed: {str(e)}",
                "iyzico Integration Error"
            )
            return {"success": False, "error": str(e)}


# API endpoints for Frappe whitelisting
@frappe.whitelist(allow_guest=True)
def iyzico_callback(**kwargs):
    """Handle iyzico callback notifications.

    This endpoint receives payment status updates from iyzico.
    """
    try:
        integration = IyzicoIntegration()
        result = integration.process_callback(kwargs)

        if result.get("success"):
            # Redirect to success URL
            return frappe.redirect_to_message(
                _("Payment Successful"),
                _("Your payment has been processed successfully.")
            )
        else:
            # Redirect to failure URL
            return frappe.redirect_to_message(
                _("Payment Failed"),
                _("Your payment could not be processed. Please try again.")
            )

    except Exception as e:
        frappe.log_error(
            f"iyzico callback exception: {str(e)}",
            "iyzico Callback Error"
        )
        return frappe.redirect_to_message(
            _("Error"),
            _("An error occurred while processing your payment.")
        )


@frappe.whitelist()
def initialize_iyzico_checkout(payment_intent_name, basket_items=None, buyer_info=None,
                                billing_address=None, shipping_address=None):
    """Initialize iyzico checkout form.

    Args:
        payment_intent_name: Name of the Payment Intent document
        basket_items: List of basket items
        buyer_info: Buyer information dictionary
        billing_address: Billing address dictionary
        shipping_address: Shipping address dictionary (optional)

    Returns:
        dict: Checkout form initialization result
    """
    if not frappe.db.exists("Payment Intent", payment_intent_name):
        return {"success": False, "error": "Payment Intent not found"}

    payment_intent = frappe.get_doc("Payment Intent", payment_intent_name)
    integration = IyzicoIntegration()

    # Parse JSON strings if needed
    if isinstance(basket_items, str):
        basket_items = json.loads(basket_items)
    if isinstance(buyer_info, str):
        buyer_info = json.loads(buyer_info)
    if isinstance(billing_address, str):
        billing_address = json.loads(billing_address)
    if isinstance(shipping_address, str):
        shipping_address = json.loads(shipping_address)

    return integration.initialize_checkout(
        payment_intent,
        basket_items or [],
        buyer_info or {},
        billing_address or {},
        shipping_address
    )


@frappe.whitelist()
def refund_iyzico_payment(payment_intent_name, refund_amount=None, reason=None):
    """Initiate a refund for an iyzico payment.

    Args:
        payment_intent_name: Name of the Payment Intent document
        refund_amount: Amount to refund (optional, defaults to full amount)
        reason: Reason for refund (optional)

    Returns:
        dict: Refund status
    """
    if not frappe.db.exists("Payment Intent", payment_intent_name):
        return {"success": False, "error": "Payment Intent not found"}

    payment_intent = frappe.get_doc("Payment Intent", payment_intent_name)
    integration = IyzicoIntegration()

    return integration.process_refund(
        payment_intent,
        flt(refund_amount) if refund_amount else None,
        reason
    )


@frappe.whitelist()
def cancel_iyzico_payment(payment_intent_name, reason=None):
    """Cancel an iyzico payment.

    Args:
        payment_intent_name: Name of the Payment Intent document
        reason: Reason for cancellation (optional)

    Returns:
        dict: Cancellation status
    """
    if not frappe.db.exists("Payment Intent", payment_intent_name):
        return {"success": False, "error": "Payment Intent not found"}

    payment_intent = frappe.get_doc("Payment Intent", payment_intent_name)
    integration = IyzicoIntegration()

    return integration.cancel_payment(payment_intent, reason)


@frappe.whitelist()
def get_iyzico_installments(bin_number, price):
    """Get installment options for a card.

    Args:
        bin_number: First 6 digits of the card
        price: Total price

    Returns:
        dict: Available installment options
    """
    if not bin_number or len(bin_number) < 6:
        return {"success": False, "error": "Valid BIN number is required"}

    integration = IyzicoIntegration()
    return integration.get_installment_info(bin_number, flt(price))
