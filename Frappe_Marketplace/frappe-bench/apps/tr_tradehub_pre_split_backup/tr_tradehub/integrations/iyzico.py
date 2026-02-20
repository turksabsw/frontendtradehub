# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
iyzico Payment Gateway Integration for TR-TradeHub Marketplace

iyzico is a leading Turkish payment gateway supporting:
- Credit/Debit card payments
- 3D Secure authentication
- Installment payments (taksit)
- Marketplace split payments
- Refunds and cancellations

This module uses the official iyzipay Python SDK (pip install iyzipay)

API Documentation: https://dev.iyzipay.com/
SDK Repository: https://github.com/iyzico/iyzipay-python

Configuration (site_config.json):
{
    "iyzico_api_key": "sandbox-xxxxx or production key",
    "iyzico_secret_key": "sandbox-xxxxx or production key",
    "iyzico_base_url": "https://sandbox-api.iyzipay.com",  # sandbox
    # or "https://api.iyzipay.com" for production
}
"""

import json
import hashlib
import base64
import hmac
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime, get_url


# =============================================================================
# EXCEPTIONS
# =============================================================================


class IyzicoError(Exception):
    """Base exception for iyzico integration errors."""

    def __init__(
        self,
        message: str,
        error_code: str = None,
        error_group: str = None,
        error_message: str = None,
        conversation_id: str = None,
    ):
        self.message = message
        self.error_code = error_code
        self.error_group = error_group
        self.error_message = error_message
        self.conversation_id = conversation_id
        super().__init__(self.message)

    def to_dict(self) -> Dict:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "error_group": self.error_group,
            "error_message": self.error_message,
            "conversation_id": self.conversation_id,
        }


class IyzicoAuthenticationError(IyzicoError):
    """Authentication/credential errors."""
    pass


class IyzicoValidationError(IyzicoError):
    """Request validation errors."""
    pass


class IyzicoPaymentError(IyzicoError):
    """Payment processing errors."""
    pass


class Iyzico3DSecureError(IyzicoError):
    """3D Secure authentication errors."""
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================


def get_iyzico_config() -> Dict[str, str]:
    """
    Get iyzico configuration from site_config or TR TradeHub Settings.

    Returns:
        dict: Configuration with api_key, secret_key, base_url

    Raises:
        IyzicoError: If configuration is missing
    """
    # Try site_config first
    api_key = frappe.conf.get("iyzico_api_key")
    secret_key = frappe.conf.get("iyzico_secret_key")
    base_url = frappe.conf.get("iyzico_base_url", "https://sandbox-api.iyzipay.com")

    # Fall back to TR TradeHub Settings DocType
    if not api_key or not secret_key:
        if frappe.db.exists("DocType", "TR TradeHub Settings"):
            settings = frappe.get_single("TR TradeHub Settings")
            api_key = api_key or settings.get("iyzico_api_key")
            secret_key = secret_key or settings.get_password("iyzico_secret_key")
            base_url = settings.get("iyzico_base_url") or base_url

    if not api_key or not secret_key:
        raise IyzicoError(
            _("iyzico API credentials not configured. "
              "Please set iyzico_api_key and iyzico_secret_key in site_config.json")
        )

    return {
        "api_key": api_key,
        "secret_key": secret_key,
        "base_url": base_url.rstrip("/"),
    }


# =============================================================================
# CLIENT CLASS
# =============================================================================


class IyzicoClient:
    """
    iyzico API Client for TR-TradeHub.

    Provides methods for:
    - Card payments (direct and 3D Secure)
    - Installment queries
    - Refunds and cancellations
    - Payment queries
    - Webhook verification
    """

    def __init__(self, config: Dict[str, str] = None):
        """
        Initialize iyzico client.

        Args:
            config: Optional config dict with api_key, secret_key, base_url
        """
        self.config = config or get_iyzico_config()
        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.base_url = self.config["base_url"]

        # Try to import iyzipay SDK
        try:
            import iyzipay
            self.iyzipay = iyzipay
            self.options = {
                "api_key": self.api_key,
                "secret_key": self.secret_key,
                "base_url": self.base_url,
            }
        except ImportError:
            self.iyzipay = None
            self.options = None
            frappe.log_error(
                "iyzipay SDK not installed. Run: bench pip install iyzipay",
                "iyzico Integration"
            )

    def _ensure_sdk(self):
        """Ensure iyzipay SDK is available."""
        if not self.iyzipay:
            raise IyzicoError(
                _("iyzipay SDK not installed. Please run: bench pip install iyzipay")
            )

    def _handle_response(self, response: Any, operation: str) -> Dict:
        """
        Handle iyzico API response.

        Args:
            response: iyzipay response object
            operation: Operation name for logging

        Returns:
            dict: Response data

        Raises:
            IyzicoError: If response indicates error
        """
        try:
            if hasattr(response, "read"):
                result = response.read().decode("utf-8")
                data = json.loads(result)
            elif isinstance(response, dict):
                data = response
            else:
                data = json.loads(str(response))
        except (json.JSONDecodeError, AttributeError) as e:
            frappe.log_error(
                f"iyzico response parse error: {str(e)}",
                f"iyzico {operation}"
            )
            raise IyzicoError(_("Failed to parse iyzico response"))

        # Check for error status
        status = data.get("status")
        if status == "failure":
            error_code = data.get("errorCode")
            error_message = data.get("errorMessage")
            error_group = data.get("errorGroup")
            conversation_id = data.get("conversationId")

            # Log error
            frappe.log_error(
                f"iyzico {operation} failed: {error_code} - {error_message}",
                f"iyzico {operation} Error"
            )

            # Determine error type
            if error_group == "NOT_SUFFICIENT_FUNDS":
                raise IyzicoPaymentError(
                    _("Insufficient funds"),
                    error_code=error_code,
                    error_group=error_group,
                    error_message=error_message,
                    conversation_id=conversation_id,
                )
            elif error_group in ["AUTHENTICATION", "NOT_AUTHORIZED"]:
                raise IyzicoAuthenticationError(
                    _("Authentication failed"),
                    error_code=error_code,
                    error_group=error_group,
                    error_message=error_message,
                )
            elif error_group == "VALIDATION":
                raise IyzicoValidationError(
                    _("Validation error: {0}").format(error_message),
                    error_code=error_code,
                    error_group=error_group,
                    error_message=error_message,
                )
            else:
                raise IyzicoPaymentError(
                    error_message or _("Payment failed"),
                    error_code=error_code,
                    error_group=error_group,
                    error_message=error_message,
                    conversation_id=conversation_id,
                )

        return data

    def _format_price(self, amount: float) -> str:
        """Format price for iyzico (2 decimal places as string)."""
        return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _generate_conversation_id(self, prefix: str = "TR") -> str:
        """Generate unique conversation ID for request tracking."""
        import secrets
        return f"{prefix}{secrets.token_hex(8).upper()}"

    # =========================================================================
    # PAYMENT METHODS
    # =========================================================================

    def create_payment(
        self,
        payment_intent: str,
        card_holder_name: str,
        card_number: str,
        card_expiry_month: str,
        card_expiry_year: str,
        card_cvc: str,
        amount: float,
        currency: str = "TRY",
        installment: int = 1,
        buyer_info: Dict = None,
        shipping_address: Dict = None,
        billing_address: Dict = None,
        basket_items: List[Dict] = None,
        conversation_id: str = None,
    ) -> Dict:
        """
        Create a direct card payment (non-3D).

        Args:
            payment_intent: TR-TradeHub Payment Intent ID
            card_holder_name: Name on card
            card_number: Card number (will be masked in logs)
            card_expiry_month: Expiry month (01-12)
            card_expiry_year: Expiry year (4 digits)
            card_cvc: CVV/CVC code
            amount: Payment amount
            currency: Currency code (default TRY)
            installment: Number of installments (1 = no installment)
            buyer_info: Buyer details dict
            shipping_address: Shipping address dict
            billing_address: Billing address dict
            basket_items: List of item dicts
            conversation_id: Optional request tracking ID

        Returns:
            dict: Payment result with paymentId, status, etc.
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id()

        # Build payment card
        payment_card = {
            "cardHolderName": card_holder_name,
            "cardNumber": card_number,
            "expireMonth": str(card_expiry_month).zfill(2),
            "expireYear": str(card_expiry_year),
            "cvc": str(card_cvc),
            "registerCard": "0",  # Don't save card
        }

        # Build buyer
        buyer = self._build_buyer(buyer_info or {})

        # Build addresses
        shipping = self._build_address(shipping_address or billing_address or {}, "shipping")
        billing = self._build_address(billing_address or shipping_address or {}, "billing")

        # Build basket items
        items = self._build_basket_items(basket_items or [], amount)

        # Build request
        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "price": self._format_price(amount),
            "paidPrice": self._format_price(amount),
            "currency": currency,
            "installment": str(installment),
            "basketId": payment_intent,
            "paymentChannel": "WEB",
            "paymentGroup": "PRODUCT",
            "paymentCard": payment_card,
            "buyer": buyer,
            "shippingAddress": shipping,
            "billingAddress": billing,
            "basketItems": items,
        }

        # Make API call
        try:
            payment = self.iyzipay.Payment()
            response = payment.create(request, self.options)
            result = self._handle_response(response, "Create Payment")

            # Log success (without sensitive data)
            self._log_payment_event(
                payment_intent,
                "payment_created",
                {
                    "payment_id": result.get("paymentId"),
                    "status": result.get("status"),
                    "conversation_id": conversation_id,
                }
            )

            return {
                "success": True,
                "payment_id": result.get("paymentId"),
                "conversation_id": result.get("conversationId"),
                "status": result.get("status"),
                "price": result.get("price"),
                "paid_price": result.get("paidPrice"),
                "installment": result.get("installment"),
                "currency": result.get("currency"),
                "fraud_status": result.get("fraudStatus"),
                "card_type": result.get("cardType"),
                "card_association": result.get("cardAssociation"),
                "card_family": result.get("cardFamily"),
                "bin_number": result.get("binNumber"),
                "last_four_digits": result.get("lastFourDigits"),
                "transaction_items": result.get("itemTransactions", []),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico payment error: {str(e)}",
                "iyzico Create Payment"
            )
            raise IyzicoPaymentError(_("Payment processing failed: {0}").format(str(e)))

    def create_3d_payment(
        self,
        payment_intent: str,
        card_holder_name: str,
        card_number: str,
        card_expiry_month: str,
        card_expiry_year: str,
        card_cvc: str,
        amount: float,
        currency: str = "TRY",
        installment: int = 1,
        buyer_info: Dict = None,
        shipping_address: Dict = None,
        billing_address: Dict = None,
        basket_items: List[Dict] = None,
        callback_url: str = None,
        conversation_id: str = None,
    ) -> Dict:
        """
        Initialize 3D Secure payment.

        Args:
            payment_intent: TR-TradeHub Payment Intent ID
            card_holder_name: Name on card
            card_number: Card number
            card_expiry_month: Expiry month
            card_expiry_year: Expiry year
            card_cvc: CVV/CVC
            amount: Payment amount
            currency: Currency code
            installment: Number of installments
            buyer_info: Buyer details
            shipping_address: Shipping address
            billing_address: Billing address
            basket_items: Basket items
            callback_url: URL for 3D Secure callback
            conversation_id: Request tracking ID

        Returns:
            dict: 3D Secure initialization result with HTML content
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("3D")

        # Build callback URL
        if not callback_url:
            callback_url = get_url(
                f"/api/method/tr_tradehub.api.v1.payment.iyzico_3d_callback"
                f"?payment_intent={payment_intent}"
            )

        # Build payment card
        payment_card = {
            "cardHolderName": card_holder_name,
            "cardNumber": card_number,
            "expireMonth": str(card_expiry_month).zfill(2),
            "expireYear": str(card_expiry_year),
            "cvc": str(card_cvc),
            "registerCard": "0",
        }

        # Build buyer
        buyer = self._build_buyer(buyer_info or {})

        # Build addresses
        shipping = self._build_address(shipping_address or billing_address or {}, "shipping")
        billing = self._build_address(billing_address or shipping_address or {}, "billing")

        # Build basket items
        items = self._build_basket_items(basket_items or [], amount)

        # Build request
        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "price": self._format_price(amount),
            "paidPrice": self._format_price(amount),
            "currency": currency,
            "installment": str(installment),
            "basketId": payment_intent,
            "paymentChannel": "WEB",
            "paymentGroup": "PRODUCT",
            "callbackUrl": callback_url,
            "paymentCard": payment_card,
            "buyer": buyer,
            "shippingAddress": shipping,
            "billingAddress": billing,
            "basketItems": items,
        }

        try:
            three_d_initialize = self.iyzipay.ThreedsInitialize()
            response = three_d_initialize.create(request, self.options)
            result = self._handle_response(response, "3D Secure Initialize")

            # Log 3D initialization
            self._log_payment_event(
                payment_intent,
                "3d_secure_initialized",
                {
                    "conversation_id": conversation_id,
                    "status": result.get("status"),
                }
            )

            return {
                "success": True,
                "status": result.get("status"),
                "conversation_id": result.get("conversationId"),
                "three_d_html_content": result.get("threeDSHtmlContent"),
                "payment_id": result.get("paymentId"),
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico 3D init error: {str(e)}",
                "iyzico 3D Initialize"
            )
            raise Iyzico3DSecureError(_("3D Secure initialization failed: {0}").format(str(e)))

    def complete_3d_payment(self, payment_id: str, conversation_id: str = None) -> Dict:
        """
        Complete 3D Secure payment after bank authentication.

        Args:
            payment_id: Payment ID from 3D callback
            conversation_id: Conversation ID for tracking

        Returns:
            dict: Payment completion result
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("3DC")

        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "paymentId": payment_id,
        }

        try:
            three_d_auth = self.iyzipay.ThreedsPayment()
            response = three_d_auth.create(request, self.options)
            result = self._handle_response(response, "3D Secure Complete")

            self._log_payment_event(
                payment_id,
                "3d_secure_completed",
                {
                    "payment_id": result.get("paymentId"),
                    "status": result.get("status"),
                    "fraud_status": result.get("fraudStatus"),
                }
            )

            return {
                "success": True,
                "payment_id": result.get("paymentId"),
                "conversation_id": result.get("conversationId"),
                "status": result.get("status"),
                "price": result.get("price"),
                "paid_price": result.get("paidPrice"),
                "installment": result.get("installment"),
                "currency": result.get("currency"),
                "fraud_status": result.get("fraudStatus"),
                "card_type": result.get("cardType"),
                "card_association": result.get("cardAssociation"),
                "bin_number": result.get("binNumber"),
                "last_four_digits": result.get("lastFourDigits"),
                "transaction_items": result.get("itemTransactions", []),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico 3D complete error: {str(e)}",
                "iyzico 3D Complete"
            )
            raise Iyzico3DSecureError(_("3D Secure completion failed: {0}").format(str(e)))

    # =========================================================================
    # REFUND & CANCELLATION METHODS
    # =========================================================================

    def refund_payment(
        self,
        payment_id: str,
        payment_transaction_id: str,
        amount: float,
        currency: str = "TRY",
        reason: str = None,
        conversation_id: str = None,
    ) -> Dict:
        """
        Refund a payment (partial or full).

        Args:
            payment_id: iyzico payment ID
            payment_transaction_id: Transaction ID from itemTransactions
            amount: Refund amount
            currency: Currency code
            reason: Refund reason
            conversation_id: Request tracking ID

        Returns:
            dict: Refund result
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("REF")

        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "paymentTransactionId": payment_transaction_id,
            "price": self._format_price(amount),
            "currency": currency,
        }

        if reason:
            request["reason"] = reason

        try:
            refund = self.iyzipay.Refund()
            response = refund.create(request, self.options)
            result = self._handle_response(response, "Refund")

            self._log_payment_event(
                payment_id,
                "refund_processed",
                {
                    "payment_transaction_id": payment_transaction_id,
                    "amount": amount,
                    "status": result.get("status"),
                }
            )

            return {
                "success": True,
                "payment_id": result.get("paymentId"),
                "payment_transaction_id": result.get("paymentTransactionId"),
                "price": result.get("price"),
                "status": result.get("status"),
                "conversation_id": result.get("conversationId"),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico refund error: {str(e)}",
                "iyzico Refund"
            )
            raise IyzicoPaymentError(_("Refund failed: {0}").format(str(e)))

    def cancel_payment(
        self,
        payment_id: str,
        reason: str = None,
        conversation_id: str = None,
    ) -> Dict:
        """
        Cancel a payment (full refund before settlement).

        Args:
            payment_id: iyzico payment ID
            reason: Cancellation reason
            conversation_id: Request tracking ID

        Returns:
            dict: Cancellation result
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("CAN")

        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "paymentId": payment_id,
        }

        if reason:
            request["reason"] = reason

        try:
            cancel = self.iyzipay.Cancel()
            response = cancel.create(request, self.options)
            result = self._handle_response(response, "Cancel")

            self._log_payment_event(
                payment_id,
                "payment_cancelled",
                {
                    "payment_id": payment_id,
                    "status": result.get("status"),
                }
            )

            return {
                "success": True,
                "payment_id": result.get("paymentId"),
                "price": result.get("price"),
                "currency": result.get("currency"),
                "status": result.get("status"),
                "conversation_id": result.get("conversationId"),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico cancel error: {str(e)}",
                "iyzico Cancel"
            )
            raise IyzicoPaymentError(_("Cancellation failed: {0}").format(str(e)))

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_payment_details(self, payment_id: str, conversation_id: str = None) -> Dict:
        """
        Get payment details by payment ID.

        Args:
            payment_id: iyzico payment ID
            conversation_id: Request tracking ID

        Returns:
            dict: Payment details
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("QRY")

        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "paymentId": payment_id,
        }

        try:
            retrieve = self.iyzipay.PaymentRetrieve()
            response = retrieve.create(request, self.options)
            result = self._handle_response(response, "Payment Retrieve")

            return {
                "success": True,
                "payment_id": result.get("paymentId"),
                "status": result.get("status"),
                "price": result.get("price"),
                "paid_price": result.get("paidPrice"),
                "currency": result.get("currency"),
                "installment": result.get("installment"),
                "fraud_status": result.get("fraudStatus"),
                "card_type": result.get("cardType"),
                "card_association": result.get("cardAssociation"),
                "card_family": result.get("cardFamily"),
                "bin_number": result.get("binNumber"),
                "last_four_digits": result.get("lastFourDigits"),
                "transaction_items": result.get("itemTransactions", []),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico retrieve error: {str(e)}",
                "iyzico Retrieve"
            )
            raise IyzicoPaymentError(_("Failed to retrieve payment: {0}").format(str(e)))

    def get_installment_info(
        self,
        bin_number: str,
        amount: float,
        currency: str = "TRY",
        conversation_id: str = None,
    ) -> Dict:
        """
        Get installment options for a card BIN.

        Args:
            bin_number: First 6 digits of card number
            amount: Payment amount
            currency: Currency code
            conversation_id: Request tracking ID

        Returns:
            dict: Available installment options
        """
        self._ensure_sdk()

        conversation_id = conversation_id or self._generate_conversation_id("INS")

        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "binNumber": str(bin_number)[:6],
            "price": self._format_price(amount),
        }

        try:
            installment_info = self.iyzipay.InstallmentInfo()
            response = installment_info.create(request, self.options)
            result = self._handle_response(response, "Installment Info")

            # Parse installment details
            installments = []
            for detail in result.get("installmentDetails", []):
                for price in detail.get("installmentPrices", []):
                    installments.append({
                        "installment_number": price.get("installmentNumber"),
                        "total_price": price.get("totalPrice"),
                        "installment_price": price.get("installmentPrice"),
                        "card_type": detail.get("cardType"),
                        "card_association": detail.get("cardAssociation"),
                        "card_family_name": detail.get("cardFamilyName"),
                        "force_3ds": detail.get("force3ds"),
                    })

            return {
                "success": True,
                "bin_number": result.get("binNumber"),
                "price": result.get("price"),
                "installments": installments,
                "conversation_id": result.get("conversationId"),
                "raw_response": result,
            }

        except IyzicoError:
            raise
        except Exception as e:
            frappe.log_error(
                f"iyzico installment error: {str(e)}",
                "iyzico Installment Info"
            )
            raise IyzicoPaymentError(_("Failed to get installment info: {0}").format(str(e)))

    # =========================================================================
    # WEBHOOK METHODS
    # =========================================================================

    def verify_webhook_signature(
        self,
        payload: str,
        signature: str,
    ) -> bool:
        """
        Verify webhook callback signature.

        Args:
            payload: Raw webhook payload
            signature: Signature from X-IYZ-SIGNATURE header

        Returns:
            bool: True if signature is valid
        """
        if not signature:
            return False

        # iyzico webhook signature verification
        # Signature = Base64(SHA1(secretKey + iyziEventType + iyziReferenceCode + token))
        try:
            data = json.loads(payload)
            event_type = data.get("iyziEventType", "")
            reference_code = data.get("iyziReferenceCode", "")
            token = data.get("token", "")

            signature_string = f"{self.secret_key}{event_type}{reference_code}{token}"
            computed_signature = base64.b64encode(
                hashlib.sha1(signature_string.encode()).digest()
            ).decode()

            return hmac.compare_digest(computed_signature, signature)
        except Exception as e:
            frappe.log_error(
                f"Webhook signature verification error: {str(e)}",
                "iyzico Webhook"
            )
            return False

    def parse_webhook_payload(self, payload: str) -> Dict:
        """
        Parse and validate webhook payload.

        Args:
            payload: Raw webhook payload

        Returns:
            dict: Parsed webhook data
        """
        try:
            data = json.loads(payload)
            return {
                "event_type": data.get("iyziEventType"),
                "reference_code": data.get("iyziReferenceCode"),
                "payment_id": data.get("paymentId"),
                "payment_conversation_id": data.get("paymentConversationId"),
                "status": data.get("status"),
                "merchant_commission_rate": data.get("merchantCommissionRate"),
                "merchant_commission_rate_amount": data.get("merchantCommissionRateAmount"),
                "token": data.get("token"),
                "raw_data": data,
            }
        except json.JSONDecodeError as e:
            raise IyzicoError(_("Invalid webhook payload: {0}").format(str(e)))

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _build_buyer(self, info: Dict) -> Dict:
        """Build buyer object for iyzico request."""
        # Generate ID if not provided
        buyer_id = info.get("id") or info.get("email", "guest")[:50]

        return {
            "id": buyer_id,
            "name": info.get("first_name", "Guest"),
            "surname": info.get("last_name", "User"),
            "gsmNumber": info.get("phone", "+905000000000"),
            "email": info.get("email", "guest@example.com"),
            "identityNumber": info.get("identity_number", "11111111111"),  # TCKN
            "registrationAddress": info.get("address", "Not provided"),
            "ip": info.get("ip_address") or frappe.request.remote_addr if frappe.request else "127.0.0.1",
            "city": info.get("city", "Istanbul"),
            "country": info.get("country", "Turkey"),
            "zipCode": info.get("zip_code", "34000"),
        }

    def _build_address(self, info: Dict, address_type: str) -> Dict:
        """Build address object for iyzico request."""
        contact_name = info.get("contact_name") or info.get("name", "Guest User")

        return {
            "contactName": contact_name,
            "city": info.get("city", "Istanbul"),
            "country": info.get("country", "Turkey"),
            "address": info.get("address", info.get("address_line_1", "Not provided")),
            "zipCode": info.get("zip_code", info.get("postal_code", "34000")),
        }

    def _build_basket_items(self, items: List[Dict], total_amount: float) -> List[Dict]:
        """Build basket items for iyzico request."""
        if not items:
            # Create single item for total amount
            return [{
                "id": "ITEM001",
                "name": "Order",
                "category1": "General",
                "itemType": "PHYSICAL",
                "price": self._format_price(total_amount),
            }]

        basket_items = []
        for idx, item in enumerate(items):
            basket_items.append({
                "id": item.get("id", f"ITEM{idx + 1:03d}"),
                "name": item.get("name", "Product")[:50],
                "category1": item.get("category", "General")[:50],
                "category2": item.get("subcategory", "")[:50] or None,
                "itemType": item.get("item_type", "PHYSICAL"),  # PHYSICAL or VIRTUAL
                "price": self._format_price(item.get("price", 0)),
                "subMerchantKey": item.get("sub_merchant_key"),  # For marketplace
                "subMerchantPrice": self._format_price(item.get("sub_merchant_price", 0)) if item.get("sub_merchant_price") else None,
            })

        # Filter out None values
        for item in basket_items:
            item = {k: v for k, v in item.items() if v is not None}

        return basket_items

    def _log_payment_event(self, payment_ref: str, event_type: str, details: Dict):
        """Log payment event for audit trail."""
        try:
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"iyzico {event_type}",
                "content": json.dumps(details),
                "reference_doctype": "Payment Intent",
                "reference_name": payment_ref,
                "user": frappe.session.user or "System",
            }).insert(ignore_permissions=True)
        except Exception:
            pass  # Don't let logging errors affect payment flow


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_payment(**kwargs) -> Dict:
    """Convenience function to create a payment."""
    client = IyzicoClient()
    return client.create_payment(**kwargs)


def create_3d_payment(**kwargs) -> Dict:
    """Convenience function to create a 3D Secure payment."""
    client = IyzicoClient()
    return client.create_3d_payment(**kwargs)


def complete_3d_payment(payment_id: str, conversation_id: str = None) -> Dict:
    """Convenience function to complete 3D Secure payment."""
    client = IyzicoClient()
    return client.complete_3d_payment(payment_id, conversation_id)


def refund_payment(
    payment_id: str = None,
    payment_transaction_id: str = None,
    amount: float = None,
    currency: str = "TRY",
    reason: str = None,
) -> Dict:
    """Convenience function to refund a payment."""
    client = IyzicoClient()
    return client.refund_payment(
        payment_id=payment_id,
        payment_transaction_id=payment_transaction_id,
        amount=amount,
        currency=currency,
        reason=reason,
    )


def cancel_payment(payment_id: str, reason: str = None) -> Dict:
    """Convenience function to cancel a payment."""
    client = IyzicoClient()
    return client.cancel_payment(payment_id, reason)


def get_installment_info(bin_number: str, amount: float, currency: str = "TRY") -> Dict:
    """Convenience function to get installment options."""
    client = IyzicoClient()
    return client.get_installment_info(bin_number, amount, currency)


def verify_webhook(payload: str, signature: str) -> bool:
    """Convenience function to verify webhook signature."""
    client = IyzicoClient()
    return client.verify_webhook_signature(payload, signature)


def get_payment_details(payment_id: str) -> Dict:
    """Convenience function to get payment details."""
    client = IyzicoClient()
    return client.get_payment_details(payment_id)


# =============================================================================
# FRAPPE API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_installments(bin_number: str, amount: float) -> Dict:
    """
    API endpoint to get installment options.

    Args:
        bin_number: First 6 digits of card number
        amount: Payment amount

    Returns:
        dict: Available installment options
    """
    try:
        result = get_installment_info(bin_number, flt(amount))
        return result
    except IyzicoError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "iyzico Get Installments API")
        frappe.throw(_("Failed to get installment options"))


@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """
    API endpoint for iyzico webhook callbacks.

    Returns:
        dict: Webhook processing result
    """
    try:
        payload = frappe.request.get_data(as_text=True)
        signature = frappe.request.headers.get("X-IYZ-SIGNATURE", "")

        client = IyzicoClient()

        # Verify signature
        if not client.verify_webhook_signature(payload, signature):
            frappe.log_error(
                "Invalid webhook signature",
                "iyzico Webhook"
            )
            frappe.throw(_("Invalid webhook signature"), frappe.AuthenticationError)

        # Parse payload
        webhook_data = client.parse_webhook_payload(payload)

        # Process based on event type
        event_type = webhook_data.get("event_type")
        payment_id = webhook_data.get("payment_id")

        if event_type == "CREDIT_PAYMENT_SUCCESS":
            # Update Payment Intent status
            _update_payment_intent_from_webhook(payment_id, "Paid", webhook_data)

        elif event_type == "CREDIT_PAYMENT_FAILURE":
            _update_payment_intent_from_webhook(payment_id, "Failed", webhook_data)

        elif event_type == "REFUND_SUCCESS":
            _update_payment_intent_from_webhook(payment_id, "Refunded", webhook_data)

        frappe.log_error(
            f"iyzico webhook processed: {event_type} - {payment_id}",
            "iyzico Webhook Success"
        )

        return {"success": True, "event_type": event_type}

    except Exception as e:
        frappe.log_error(str(e), "iyzico Webhook Error")
        raise


def _update_payment_intent_from_webhook(
    payment_id: str,
    status: str,
    webhook_data: Dict,
):
    """Update Payment Intent based on webhook data."""
    try:
        # Find Payment Intent by gateway payment ID
        payment_intent = frappe.db.get_value(
            "Payment Intent",
            {"gateway_payment_id": payment_id},
            "name"
        )

        if payment_intent:
            frappe.db.set_value(
                "Payment Intent",
                payment_intent,
                {
                    "status": status,
                    "gateway_response": json.dumps(webhook_data.get("raw_data", {})),
                    "updated_at": now_datetime(),
                }
            )
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            f"Failed to update Payment Intent from webhook: {str(e)}",
            "iyzico Webhook"
        )
