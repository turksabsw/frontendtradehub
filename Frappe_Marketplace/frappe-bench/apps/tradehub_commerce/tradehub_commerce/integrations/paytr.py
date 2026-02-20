# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""PayTR Payment Gateway Integration for TradeHub Commerce

PayTR is a popular Turkish payment gateway that supports:
- Credit/Debit card payments
- 3D Secure authentication
- Installment payments
- Virtual POS integration
- Payment form (iframe) integration

This module provides methods to:
- Create payment tokens
- Process payment callbacks
- Handle refunds
- Query transaction status
"""

import hashlib
import hmac
import base64
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now


class PayTRIntegration:
    """PayTR Payment Gateway Integration Class.

    Handles all PayTR API interactions for payment processing.
    """

    # PayTR API endpoints
    API_BASE_URL = "https://www.paytr.com"
    TOKEN_ENDPOINT = "/odeme/api/get-token"
    REFUND_ENDPOINT = "/odeme/iade"
    STATUS_ENDPOINT = "/odeme/durum"

    def __init__(self):
        """Initialize PayTR integration with credentials from settings."""
        self.settings = self._get_settings()
        self.merchant_id = self.settings.get("paytr_merchant_id", "")
        self.merchant_key = self.settings.get("paytr_merchant_key", "")
        self.merchant_salt = self.settings.get("paytr_merchant_salt", "")
        self.test_mode = self.settings.get("paytr_test_mode", 1)

    def _get_settings(self):
        """Get PayTR settings from the database.

        Returns:
            dict: PayTR configuration settings
        """
        try:
            # Try to get from Payment Method DocType
            if frappe.db.exists("Payment Method", {"provider": "PayTR"}):
                payment_method = frappe.get_doc("Payment Method", {"provider": "PayTR"})
                return {
                    "paytr_merchant_id": payment_method.get("merchant_id", ""),
                    "paytr_merchant_key": payment_method.get("api_key", ""),
                    "paytr_merchant_salt": payment_method.get("api_secret", ""),
                    "paytr_test_mode": payment_method.get("test_mode", 1)
                }
        except Exception:
            pass

        # Return empty settings if not configured
        return {
            "paytr_merchant_id": "",
            "paytr_merchant_key": "",
            "paytr_merchant_salt": "",
            "paytr_test_mode": 1
        }

    def _generate_hash(self, data_string):
        """Generate HMAC hash for PayTR API authentication.

        Args:
            data_string: The data string to hash

        Returns:
            str: Base64 encoded HMAC-SHA256 hash
        """
        if not self.merchant_key or not self.merchant_salt:
            frappe.throw(_("PayTR merchant key and salt are required"))

        hash_str = data_string + self.merchant_salt
        token = hmac.new(
            self.merchant_key.encode("utf-8"),
            hash_str.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(token).decode("utf-8")

    def create_payment_token(self, payment_intent, basket_items, user_info):
        """Create a payment token for PayTR iframe integration.

        Args:
            payment_intent: Payment Intent document
            basket_items: List of items in the basket
            user_info: Dictionary containing user information

        Returns:
            dict: Response containing token or error
        """
        if not self.merchant_id:
            return {"success": False, "error": _("PayTR is not configured")}

        try:
            # Prepare basket as JSON array
            basket_json = json.dumps(basket_items)
            basket_encoded = base64.b64encode(basket_json.encode("utf-8")).decode("utf-8")

            # Prepare payment data
            merchant_oid = payment_intent.name
            user_ip = user_info.get("ip_address", "127.0.0.1")
            email = user_info.get("email", "")
            payment_amount = cint(flt(payment_intent.amount) * 100)  # Convert to kuruş
            currency = payment_intent.currency or "TL"
            no_installment = user_info.get("no_installment", 0)
            max_installment = user_info.get("max_installment", 0)
            test_mode = cint(self.test_mode)

            # Generate hash
            hash_string = (
                f"{self.merchant_id}{user_ip}{merchant_oid}{email}"
                f"{payment_amount}{basket_encoded}{no_installment}"
                f"{max_installment}{currency}{test_mode}"
            )
            paytr_token = self._generate_hash(hash_string)

            # Prepare request data
            request_data = {
                "merchant_id": self.merchant_id,
                "user_ip": user_ip,
                "merchant_oid": merchant_oid,
                "email": email,
                "payment_amount": payment_amount,
                "paytr_token": paytr_token,
                "user_basket": basket_encoded,
                "debug_on": 1 if test_mode else 0,
                "no_installment": no_installment,
                "max_installment": max_installment,
                "user_name": user_info.get("name", ""),
                "user_address": user_info.get("address", ""),
                "user_phone": user_info.get("phone", ""),
                "merchant_ok_url": user_info.get("success_url", ""),
                "merchant_fail_url": user_info.get("fail_url", ""),
                "timeout_limit": 30,
                "currency": currency,
                "test_mode": test_mode,
                "lang": user_info.get("lang", "tr")
            }

            # In a real implementation, this would make an HTTP request to PayTR
            # For now, we return the prepared data for mock testing
            frappe.logger().info(
                f"PayTR payment token request prepared for {merchant_oid}"
            )

            return {
                "success": True,
                "merchant_oid": merchant_oid,
                "request_data": request_data
            }

        except Exception as e:
            frappe.log_error(
                f"PayTR token creation failed: {str(e)}",
                "PayTR Integration Error"
            )
            return {"success": False, "error": str(e)}

    def process_callback(self, callback_data):
        """Process PayTR payment callback notification.

        Args:
            callback_data: Dictionary containing callback parameters from PayTR

        Returns:
            dict: Processing result with success status
        """
        try:
            merchant_oid = callback_data.get("merchant_oid")
            status = callback_data.get("status")
            total_amount = callback_data.get("total_amount")
            hash_value = callback_data.get("hash")

            # Verify callback hash
            hash_str = f"{merchant_oid}{self.merchant_salt}{status}{total_amount}"
            expected_hash = base64.b64encode(
                hashlib.sha256(hash_str.encode("utf-8")).digest()
            ).decode("utf-8")

            if hash_value != expected_hash:
                frappe.log_error(
                    f"PayTR callback hash mismatch for {merchant_oid}",
                    "PayTR Security Error"
                )
                return {"success": False, "error": "Hash verification failed"}

            # Update Payment Intent
            if frappe.db.exists("Payment Intent", merchant_oid):
                payment_intent = frappe.get_doc("Payment Intent", merchant_oid)

                if status == "success":
                    payment_intent.status = "Completed"
                    payment_intent.payment_reference = callback_data.get("payment_id")
                    payment_intent.completed_at = now()
                else:
                    payment_intent.status = "Failed"
                    payment_intent.failure_reason = callback_data.get("failed_reason_msg", "")

                payment_intent.callback_data = json.dumps(callback_data)
                payment_intent.flags.ignore_validate = True
                payment_intent.save()

                frappe.logger().info(
                    f"PayTR callback processed for {merchant_oid}: {status}"
                )

                return {"success": True, "status": status}

            return {"success": False, "error": "Payment Intent not found"}

        except Exception as e:
            frappe.log_error(
                f"PayTR callback processing failed: {str(e)}",
                "PayTR Integration Error"
            )
            return {"success": False, "error": str(e)}

    def process_refund(self, payment_intent, refund_amount=None, reason=None):
        """Process a refund through PayTR.

        Args:
            payment_intent: Payment Intent document to refund
            refund_amount: Amount to refund (defaults to full amount)
            reason: Reason for refund

        Returns:
            dict: Refund result with success status
        """
        if not self.merchant_id:
            return {"success": False, "error": _("PayTR is not configured")}

        try:
            merchant_oid = payment_intent.name
            amount = cint(flt(refund_amount or payment_intent.amount) * 100)

            # Generate refund hash
            hash_string = f"{self.merchant_id}{merchant_oid}{amount}"
            refund_token = self._generate_hash(hash_string)

            # Prepare refund request
            refund_data = {
                "merchant_id": self.merchant_id,
                "merchant_oid": merchant_oid,
                "return_amount": amount,
                "paytr_token": refund_token
            }

            # In a real implementation, this would make an HTTP request to PayTR
            frappe.logger().info(
                f"PayTR refund request prepared for {merchant_oid}: {amount} kuruş"
            )

            # Update Payment Intent status
            payment_intent.status = "Refund Pending"
            payment_intent.refund_amount = refund_amount or payment_intent.amount
            payment_intent.refund_reason = reason
            payment_intent.refund_requested_at = now()
            payment_intent.flags.ignore_validate = True
            payment_intent.save()

            return {
                "success": True,
                "merchant_oid": merchant_oid,
                "refund_amount": amount,
                "refund_data": refund_data
            }

        except Exception as e:
            frappe.log_error(
                f"PayTR refund failed: {str(e)}",
                "PayTR Integration Error"
            )
            return {"success": False, "error": str(e)}

    def get_transaction_status(self, merchant_oid):
        """Query the status of a transaction from PayTR.

        Args:
            merchant_oid: The unique order ID

        Returns:
            dict: Transaction status information
        """
        if not self.merchant_id:
            return {"success": False, "error": _("PayTR is not configured")}

        try:
            # Generate status query hash
            hash_string = f"{self.merchant_id}{merchant_oid}"
            status_token = self._generate_hash(hash_string)

            # Prepare status request
            status_data = {
                "merchant_id": self.merchant_id,
                "merchant_oid": merchant_oid,
                "paytr_token": status_token
            }

            # In a real implementation, this would make an HTTP request to PayTR
            frappe.logger().info(
                f"PayTR status query prepared for {merchant_oid}"
            )

            return {
                "success": True,
                "merchant_oid": merchant_oid,
                "status_data": status_data
            }

        except Exception as e:
            frappe.log_error(
                f"PayTR status query failed: {str(e)}",
                "PayTR Integration Error"
            )
            return {"success": False, "error": str(e)}


# API endpoints for Frappe whitelisting
@frappe.whitelist(allow_guest=True)
def paytr_callback(**kwargs):
    """Handle PayTR callback notifications.

    This endpoint receives payment status updates from PayTR.
    """
    try:
        integration = PayTRIntegration()
        result = integration.process_callback(kwargs)

        if result.get("success"):
            return "OK"
        else:
            frappe.log_error(
                f"PayTR callback failed: {result.get('error')}",
                "PayTR Callback Error"
            )
            return "FAIL"

    except Exception as e:
        frappe.log_error(
            f"PayTR callback exception: {str(e)}",
            "PayTR Callback Error"
        )
        return "FAIL"


@frappe.whitelist()
def create_paytr_payment(payment_intent_name, basket_items=None, user_info=None):
    """Create a PayTR payment session.

    Args:
        payment_intent_name: Name of the Payment Intent document
        basket_items: List of basket items (optional)
        user_info: User information dictionary (optional)

    Returns:
        dict: Payment token and iframe URL
    """
    if not frappe.db.exists("Payment Intent", payment_intent_name):
        return {"success": False, "error": "Payment Intent not found"}

    payment_intent = frappe.get_doc("Payment Intent", payment_intent_name)
    integration = PayTRIntegration()

    # Parse JSON strings if needed
    if isinstance(basket_items, str):
        basket_items = json.loads(basket_items)
    if isinstance(user_info, str):
        user_info = json.loads(user_info)

    return integration.create_payment_token(
        payment_intent,
        basket_items or [],
        user_info or {}
    )


@frappe.whitelist()
def refund_paytr_payment(payment_intent_name, refund_amount=None, reason=None):
    """Initiate a refund for a PayTR payment.

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
    integration = PayTRIntegration()

    return integration.process_refund(
        payment_intent,
        flt(refund_amount) if refund_amount else None,
        reason
    )
