# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
PayTR Payment Gateway Integration for TR-TradeHub Marketplace

PayTR is a Turkish payment gateway supporting:
- Credit/Debit card payments
- 3D Secure authentication (iframe-based)
- Installment payments (taksit)
- Virtual POS
- Refunds

IMPORTANT: PayTR does NOT have an official Python SDK.
This module implements the Direct API integration using requests library
with HMAC-SHA256 authentication.

API Documentation: https://dev.paytr.com/
Direct API Integration Guide: https://dev.paytr.com/iframe-api

Configuration (site_config.json):
{
    "paytr_merchant_id": "your-merchant-id",
    "paytr_merchant_key": "your-merchant-key",
    "paytr_merchant_salt": "your-merchant-salt",
    "paytr_base_url": "https://www.paytr.com",
    "paytr_test_mode": 0  # 1 for test, 0 for production
}
"""

import json
import hashlib
import hmac
import base64
import requests
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime, get_url


# =============================================================================
# EXCEPTIONS
# =============================================================================


class PayTRError(Exception):
    """Base exception for PayTR integration errors."""

    def __init__(
        self,
        message: str,
        error_code: str = None,
        reason: str = None,
        merchant_oid: str = None,
    ):
        self.message = message
        self.error_code = error_code
        self.reason = reason
        self.merchant_oid = merchant_oid
        super().__init__(self.message)

    def to_dict(self) -> Dict:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "reason": self.reason,
            "merchant_oid": self.merchant_oid,
        }


class PayTRAuthenticationError(PayTRError):
    """Authentication/credential errors."""
    pass


class PayTRValidationError(PayTRError):
    """Request validation errors."""
    pass


class PayTRPaymentError(PayTRError):
    """Payment processing errors."""
    pass


class PayTRCallbackError(PayTRError):
    """Callback verification errors."""
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================


def get_paytr_config() -> Dict[str, str]:
    """
    Get PayTR configuration from site_config or TR TradeHub Settings.

    Returns:
        dict: Configuration with merchant_id, merchant_key, merchant_salt, base_url

    Raises:
        PayTRError: If configuration is missing
    """
    # Try site_config first
    merchant_id = frappe.conf.get("paytr_merchant_id")
    merchant_key = frappe.conf.get("paytr_merchant_key")
    merchant_salt = frappe.conf.get("paytr_merchant_salt")
    base_url = frappe.conf.get("paytr_base_url", "https://www.paytr.com")
    test_mode = cint(frappe.conf.get("paytr_test_mode", 0))

    # Fall back to TR TradeHub Settings DocType
    if not merchant_id or not merchant_key or not merchant_salt:
        if frappe.db.exists("DocType", "TR TradeHub Settings"):
            settings = frappe.get_single("TR TradeHub Settings")
            merchant_id = merchant_id or settings.get("paytr_merchant_id")
            merchant_key = merchant_key or settings.get_password("paytr_merchant_key")
            merchant_salt = merchant_salt or settings.get_password("paytr_merchant_salt")
            base_url = settings.get("paytr_base_url") or base_url
            test_mode = cint(settings.get("paytr_test_mode", test_mode))

    if not merchant_id or not merchant_key or not merchant_salt:
        raise PayTRError(
            _("PayTR API credentials not configured. "
              "Please set paytr_merchant_id, paytr_merchant_key, and "
              "paytr_merchant_salt in site_config.json")
        )

    return {
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "merchant_salt": merchant_salt,
        "base_url": base_url.rstrip("/"),
        "test_mode": test_mode,
    }


# =============================================================================
# CLIENT CLASS
# =============================================================================


class PayTRClient:
    """
    PayTR Direct API Client for TR-TradeHub.

    Implements PayTR Direct API with HMAC-SHA256 authentication.

    Provides methods for:
    - iFrame token generation for payments
    - Direct card payments
    - Refunds
    - Payment status queries
    - Callback verification
    - Installment queries
    """

    # API Endpoints
    ENDPOINT_IFRAME_TOKEN = "/odeme/api/get-token"
    ENDPOINT_DIRECT_PAYMENT = "/odeme"
    ENDPOINT_REFUND = "/odeme/iade"
    ENDPOINT_STATUS = "/odeme/durum-sorgu"
    ENDPOINT_BIN_INQUIRY = "/odeme/api/bin-detail"
    ENDPOINT_INSTALLMENT = "/odeme/api/taksit-tablosu"

    # Request timeout in seconds
    REQUEST_TIMEOUT = 30

    def __init__(self, config: Dict[str, str] = None):
        """
        Initialize PayTR client.

        Args:
            config: Optional config dict with merchant_id, merchant_key, etc.
        """
        self.config = config or get_paytr_config()
        self.merchant_id = self.config["merchant_id"]
        self.merchant_key = self.config["merchant_key"]
        self.merchant_salt = self.config["merchant_salt"]
        self.base_url = self.config["base_url"]
        self.test_mode = self.config["test_mode"]

    def _generate_hash(self, data: str) -> str:
        """
        Generate HMAC-SHA256 hash for PayTR authentication.

        Args:
            data: String data to hash

        Returns:
            str: Base64 encoded HMAC-SHA256 hash
        """
        hash_str = data + self.merchant_salt
        signature = hmac.new(
            self.merchant_key.encode("utf-8"),
            hash_str.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _format_amount(self, amount: float) -> int:
        """
        Format amount for PayTR (in kuruş, no decimal).

        Args:
            amount: Amount in TRY

        Returns:
            int: Amount in kuruş (1 TRY = 100 kuruş)
        """
        return int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)

    def _generate_merchant_oid(self, prefix: str = "TR") -> str:
        """Generate unique merchant order ID."""
        import secrets
        import time
        timestamp = int(time.time())
        random_part = secrets.token_hex(4).upper()
        return f"{prefix}{timestamp}{random_part}"

    def _make_request(
        self,
        endpoint: str,
        data: Dict,
        method: str = "POST",
    ) -> Dict:
        """
        Make HTTP request to PayTR API.

        Args:
            endpoint: API endpoint path
            data: Request data
            method: HTTP method

        Returns:
            dict: Response data

        Raises:
            PayTRError: If request fails
        """
        url = f"{self.base_url}{endpoint}"

        try:
            if method == "POST":
                response = requests.post(
                    url,
                    data=data,
                    timeout=self.REQUEST_TIMEOUT,
                )
            else:
                response = requests.get(
                    url,
                    params=data,
                    timeout=self.REQUEST_TIMEOUT,
                )

            # Check HTTP status
            if response.status_code != 200:
                frappe.log_error(
                    f"PayTR API error: {response.status_code} - {response.text}",
                    "PayTR API Error"
                )
                raise PayTRError(
                    _("PayTR API request failed with status {0}").format(response.status_code)
                )

            # Parse response
            result = response.json()

            # Check for API error
            if result.get("status") == "failed" or result.get("status") == "error":
                error_reason = result.get("reason", "Unknown error")
                frappe.log_error(
                    f"PayTR API error: {error_reason}",
                    "PayTR API Error"
                )
                raise PayTRPaymentError(
                    error_reason,
                    reason=error_reason,
                )

            return result

        except requests.exceptions.Timeout:
            raise PayTRError(_("PayTR API request timed out"))
        except requests.exceptions.RequestException as e:
            frappe.log_error(
                f"PayTR request error: {str(e)}",
                "PayTR Request Error"
            )
            raise PayTRError(_("PayTR API request failed: {0}").format(str(e)))
        except json.JSONDecodeError:
            raise PayTRError(_("Invalid response from PayTR API"))

    # =========================================================================
    # IFRAME TOKEN METHODS
    # =========================================================================

    def create_iframe_token(
        self,
        payment_intent: str,
        amount: float,
        currency: str = "TL",
        email: str = None,
        user_name: str = None,
        user_address: str = None,
        user_phone: str = None,
        basket_items: List[Dict] = None,
        installment_count: int = 0,
        no_installment: int = 0,
        max_installment: int = 0,
        user_ip: str = None,
        merchant_ok_url: str = None,
        merchant_fail_url: str = None,
        timeout_limit: int = 30,
        debug_on: int = 0,
        lang: str = "tr",
        card_type: str = None,
    ) -> Dict:
        """
        Generate iFrame token for PayTR checkout page.

        This is the recommended integration method. Returns a token
        that can be used to render PayTR's payment iFrame.

        Args:
            payment_intent: TR-TradeHub Payment Intent ID (used as merchant_oid)
            amount: Payment amount in TRY
            currency: Currency code (TL, EUR, USD, GBP, RUB)
            email: Customer email
            user_name: Customer full name
            user_address: Customer address
            user_phone: Customer phone
            basket_items: List of items [{name, price, quantity}]
            installment_count: Default installment count (0 = show all)
            no_installment: 1 = disable installments
            max_installment: Maximum installment count (0 = no limit)
            user_ip: Customer IP address
            merchant_ok_url: Success redirect URL
            merchant_fail_url: Failure redirect URL
            timeout_limit: Session timeout in minutes
            debug_on: 1 = enable debug mode
            lang: Language (tr, en)
            card_type: Limit to card type (card, troy)

        Returns:
            dict: Token response with iframe token
        """
        merchant_oid = payment_intent

        # Set default URLs
        if not merchant_ok_url:
            merchant_ok_url = get_url(
                f"/api/method/tr_tradehub.api.v1.payment.paytr_success"
                f"?payment_intent={payment_intent}"
            )

        if not merchant_fail_url:
            merchant_fail_url = get_url(
                f"/api/method/tr_tradehub.api.v1.payment.paytr_fail"
                f"?payment_intent={payment_intent}"
            )

        # Get user IP
        if not user_ip:
            try:
                user_ip = frappe.request.remote_addr if frappe.request else "127.0.0.1"
            except Exception:
                user_ip = "127.0.0.1"

        # Build basket string (required by PayTR)
        # Format: base64(json([["Product Name", "Price", Quantity], ...]))
        if basket_items:
            basket_array = []
            for item in basket_items:
                basket_array.append([
                    item.get("name", "Product")[:50],
                    str(self._format_amount(item.get("price", 0))),
                    cint(item.get("quantity", 1)),
                ])
        else:
            # Default single item for total amount
            basket_array = [["Order", str(self._format_amount(amount)), 1]]

        basket_str = base64.b64encode(json.dumps(basket_array).encode("utf-8")).decode("utf-8")

        # Format amount (in kuruş)
        payment_amount = str(self._format_amount(amount))

        # Build hash string
        # Hash = base64(hmac_sha256(merchant_id + user_ip + merchant_oid + email +
        #              payment_amount + basket + no_installment + max_installment +
        #              currency + test_mode + merchant_salt))
        hash_str = (
            f"{self.merchant_id}{user_ip}{merchant_oid}{email or 'customer@example.com'}"
            f"{payment_amount}{basket_str}{no_installment}{max_installment}"
            f"{currency}{self.test_mode}"
        )
        paytr_token = self._generate_hash(hash_str)

        # Build request data
        data = {
            "merchant_id": self.merchant_id,
            "user_ip": user_ip,
            "merchant_oid": merchant_oid,
            "email": email or "customer@example.com",
            "payment_amount": payment_amount,
            "paytr_token": paytr_token,
            "user_basket": basket_str,
            "debug_on": debug_on,
            "no_installment": no_installment,
            "max_installment": max_installment,
            "user_name": user_name or "Customer",
            "user_address": user_address or "Address not provided",
            "user_phone": user_phone or "5000000000",
            "merchant_ok_url": merchant_ok_url,
            "merchant_fail_url": merchant_fail_url,
            "timeout_limit": timeout_limit,
            "currency": currency,
            "test_mode": self.test_mode,
            "lang": lang,
        }

        # Optional parameters
        if installment_count:
            data["installment_count"] = installment_count

        if card_type:
            data["card_type"] = card_type

        try:
            result = self._make_request(self.ENDPOINT_IFRAME_TOKEN, data)

            if result.get("status") == "success":
                self._log_payment_event(
                    payment_intent,
                    "iframe_token_created",
                    {"merchant_oid": merchant_oid}
                )

                return {
                    "success": True,
                    "token": result.get("token"),
                    "merchant_oid": merchant_oid,
                    "iframe_url": f"{self.base_url}/odeme/guvenli/{result.get('token')}",
                }
            else:
                raise PayTRPaymentError(
                    result.get("reason", "Failed to generate token"),
                    reason=result.get("reason"),
                    merchant_oid=merchant_oid,
                )

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR token error: {str(e)}",
                "PayTR Token Error"
            )
            raise PayTRPaymentError(_("Failed to create payment token: {0}").format(str(e)))

    # =========================================================================
    # DIRECT PAYMENT METHODS
    # =========================================================================

    def create_payment(
        self,
        payment_intent: str,
        card_number: str,
        card_expiry_month: str,
        card_expiry_year: str,
        card_cvc: str,
        card_holder_name: str,
        amount: float,
        currency: str = "TL",
        installment: int = 1,
        buyer_info: Dict = None,
        basket_items: List[Dict] = None,
        use_3d_secure: bool = True,
        callback_url: str = None,
    ) -> Dict:
        """
        Create a direct card payment.

        Note: Direct API requires additional PayTR approval.
        For most use cases, use create_iframe_token() instead.

        Args:
            payment_intent: TR-TradeHub Payment Intent ID
            card_number: Card number (16 digits)
            card_expiry_month: Expiry month (01-12)
            card_expiry_year: Expiry year (2 or 4 digits)
            card_cvc: CVV/CVC code
            card_holder_name: Name on card
            amount: Payment amount
            currency: Currency code
            installment: Number of installments
            buyer_info: Buyer details dict
            basket_items: Basket items
            use_3d_secure: Enable 3D Secure (recommended)
            callback_url: 3D Secure callback URL

        Returns:
            dict: Payment result or 3D redirect URL
        """
        merchant_oid = payment_intent
        buyer = buyer_info or {}

        # Get user IP
        try:
            user_ip = frappe.request.remote_addr if frappe.request else "127.0.0.1"
        except Exception:
            user_ip = "127.0.0.1"

        # Build basket
        if basket_items:
            basket_array = []
            for item in basket_items:
                basket_array.append([
                    item.get("name", "Product")[:50],
                    str(self._format_amount(item.get("price", 0))),
                    cint(item.get("quantity", 1)),
                ])
        else:
            basket_array = [["Order", str(self._format_amount(amount)), 1]]

        basket_str = base64.b64encode(json.dumps(basket_array).encode("utf-8")).decode("utf-8")

        # Format card expiry
        expiry_month = str(card_expiry_month).zfill(2)
        expiry_year = str(card_expiry_year)
        if len(expiry_year) == 4:
            expiry_year = expiry_year[2:]  # Convert 2024 to 24

        # Format amount
        payment_amount = str(self._format_amount(amount))

        # Build hash
        hash_str = (
            f"{self.merchant_id}{user_ip}{merchant_oid}{buyer.get('email', 'customer@example.com')}"
            f"{payment_amount}{basket_str}0{installment if installment > 1 else 0}"
            f"{currency}{self.test_mode}"
        )
        paytr_token = self._generate_hash(hash_str)

        # Build callback URL for 3D Secure
        if not callback_url:
            callback_url = get_url(
                f"/api/method/tr_tradehub.api.v1.payment.paytr_callback"
            )

        # Build request data
        data = {
            "merchant_id": self.merchant_id,
            "user_ip": user_ip,
            "merchant_oid": merchant_oid,
            "email": buyer.get("email", "customer@example.com"),
            "payment_amount": payment_amount,
            "paytr_token": paytr_token,
            "user_basket": basket_str,
            "debug_on": 0,
            "no_installment": 0 if installment > 1 else 1,
            "max_installment": installment,
            "user_name": buyer.get("name", card_holder_name),
            "user_address": buyer.get("address", "Not provided"),
            "user_phone": buyer.get("phone", "5000000000"),
            "merchant_ok_url": callback_url,
            "merchant_fail_url": callback_url,
            "currency": currency,
            "test_mode": self.test_mode,
            "non_3d": 0 if use_3d_secure else 1,
            "cc_owner": card_holder_name,
            "card_number": card_number,
            "expiry_month": expiry_month,
            "expiry_year": expiry_year,
            "cvv": card_cvc,
        }

        if installment > 1:
            data["installment_count"] = installment

        try:
            result = self._make_request(self.ENDPOINT_DIRECT_PAYMENT, data)

            if result.get("status") == "success":
                # Check if 3D Secure redirect is required
                if result.get("3d_secure_url"):
                    self._log_payment_event(
                        payment_intent,
                        "3d_secure_redirect",
                        {"merchant_oid": merchant_oid}
                    )

                    return {
                        "success": True,
                        "requires_3d_secure": True,
                        "redirect_url": result.get("3d_secure_url"),
                        "merchant_oid": merchant_oid,
                    }
                else:
                    # Direct payment completed
                    self._log_payment_event(
                        payment_intent,
                        "payment_completed",
                        {
                            "merchant_oid": merchant_oid,
                            "status": "success",
                        }
                    )

                    return {
                        "success": True,
                        "requires_3d_secure": False,
                        "merchant_oid": merchant_oid,
                        "status": "success",
                        "raw_response": result,
                    }
            else:
                raise PayTRPaymentError(
                    result.get("reason", "Payment failed"),
                    reason=result.get("reason"),
                    merchant_oid=merchant_oid,
                )

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR payment error: {str(e)}",
                "PayTR Payment Error"
            )
            raise PayTRPaymentError(_("Payment failed: {0}").format(str(e)))

    # =========================================================================
    # REFUND METHODS
    # =========================================================================

    def refund_payment(
        self,
        merchant_oid: str,
        amount: float,
        reason: str = None,
        reference: str = None,
    ) -> Dict:
        """
        Refund a payment (partial or full).

        Args:
            merchant_oid: Original payment merchant_oid
            amount: Refund amount
            reason: Refund reason (optional)
            reference: Reference ID for tracking (optional)

        Returns:
            dict: Refund result
        """
        # Format amount
        refund_amount = str(self._format_amount(amount))

        # Build hash
        # Hash = base64(hmac_sha256(merchant_id + merchant_oid + return_amount + merchant_salt))
        hash_str = f"{self.merchant_id}{merchant_oid}{refund_amount}"
        paytr_token = self._generate_hash(hash_str)

        # Build request
        data = {
            "merchant_id": self.merchant_id,
            "merchant_oid": merchant_oid,
            "return_amount": refund_amount,
            "paytr_token": paytr_token,
        }

        if reference:
            data["reference_no"] = reference

        try:
            result = self._make_request(self.ENDPOINT_REFUND, data)

            if result.get("status") == "success":
                self._log_payment_event(
                    merchant_oid,
                    "refund_processed",
                    {
                        "merchant_oid": merchant_oid,
                        "amount": amount,
                        "is_test": result.get("is_test"),
                    }
                )

                return {
                    "success": True,
                    "merchant_oid": merchant_oid,
                    "refund_amount": amount,
                    "is_test": result.get("is_test"),
                    "raw_response": result,
                }
            else:
                raise PayTRPaymentError(
                    result.get("err_msg", "Refund failed"),
                    reason=result.get("err_msg"),
                    merchant_oid=merchant_oid,
                )

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR refund error: {str(e)}",
                "PayTR Refund Error"
            )
            raise PayTRPaymentError(_("Refund failed: {0}").format(str(e)))

    # =========================================================================
    # STATUS QUERY METHODS
    # =========================================================================

    def get_payment_status(self, merchant_oid: str) -> Dict:
        """
        Get payment status by merchant order ID.

        Args:
            merchant_oid: Merchant order ID

        Returns:
            dict: Payment status details
        """
        # Build hash
        hash_str = f"{self.merchant_id}{merchant_oid}"
        paytr_token = self._generate_hash(hash_str)

        data = {
            "merchant_id": self.merchant_id,
            "merchant_oid": merchant_oid,
            "paytr_token": paytr_token,
        }

        try:
            result = self._make_request(self.ENDPOINT_STATUS, data)

            # Map PayTR status to standard status
            status_map = {
                "Başarılı": "success",
                "Başarısız": "failed",
                "Bekliyor": "pending",
            }

            payment_status = result.get("payment_status", "unknown")
            normalized_status = status_map.get(payment_status, payment_status.lower())

            return {
                "success": True,
                "merchant_oid": merchant_oid,
                "payment_status": normalized_status,
                "payment_status_raw": payment_status,
                "payment_amount": flt(result.get("payment_amount", 0)) / 100,  # Convert from kuruş
                "currency": result.get("currency"),
                "payment_type": result.get("payment_type"),
                "returns": result.get("returns", []),  # Refund history
                "raw_response": result,
            }

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR status error: {str(e)}",
                "PayTR Status Error"
            )
            raise PayTRPaymentError(_("Failed to get payment status: {0}").format(str(e)))

    # =========================================================================
    # BIN & INSTALLMENT QUERIES
    # =========================================================================

    def get_bin_details(self, bin_number: str) -> Dict:
        """
        Get card BIN details (bank, card type, etc.).

        Args:
            bin_number: First 6-8 digits of card number

        Returns:
            dict: BIN details
        """
        bin_number = str(bin_number)[:8]

        # Build hash
        hash_str = f"{self.merchant_id}{bin_number}"
        paytr_token = self._generate_hash(hash_str)

        data = {
            "merchant_id": self.merchant_id,
            "bin_number": bin_number,
            "paytr_token": paytr_token,
        }

        try:
            result = self._make_request(self.ENDPOINT_BIN_INQUIRY, data)

            return {
                "success": True,
                "bin_number": bin_number,
                "bank": result.get("bank"),
                "card_type": result.get("card_type"),  # credit, debit
                "card_brand": result.get("card_brand"),  # VISA, MASTERCARD, etc.
                "card_family": result.get("card_family"),  # Bonus, Maximum, etc.
                "is_commercial": result.get("is_commercial"),
                "is_prepaid": result.get("is_prepaid"),
                "raw_response": result,
            }

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR BIN error: {str(e)}",
                "PayTR BIN Error"
            )
            raise PayTRPaymentError(_("Failed to get BIN details: {0}").format(str(e)))

    def get_installment_rates(self, amount: float = None) -> Dict:
        """
        Get available installment rates.

        Args:
            amount: Optional amount to calculate installment totals

        Returns:
            dict: Installment rates by bank/card
        """
        # Build hash
        hash_str = f"{self.merchant_id}"
        paytr_token = self._generate_hash(hash_str)

        data = {
            "merchant_id": self.merchant_id,
            "paytr_token": paytr_token,
        }

        if amount:
            data["payment_amount"] = str(self._format_amount(amount))

        try:
            result = self._make_request(self.ENDPOINT_INSTALLMENT, data)

            # Parse installment table
            installments = []
            for bank_data in result.get("taksit_oranlari", []):
                bank_info = {
                    "bank": bank_data.get("banka"),
                    "card_family": bank_data.get("kart_tipi"),
                    "rates": [],
                }

                for rate in bank_data.get("oranlar", []):
                    bank_info["rates"].append({
                        "installment_count": rate.get("taksit"),
                        "rate": flt(rate.get("oran")),
                        "total_amount": flt(rate.get("toplam_tutar")) / 100 if rate.get("toplam_tutar") else None,
                        "installment_amount": flt(rate.get("taksit_tutari")) / 100 if rate.get("taksit_tutari") else None,
                    })

                installments.append(bank_info)

            return {
                "success": True,
                "installments": installments,
                "raw_response": result,
            }

        except PayTRError:
            raise
        except Exception as e:
            frappe.log_error(
                f"PayTR installment error: {str(e)}",
                "PayTR Installment Error"
            )
            raise PayTRPaymentError(_("Failed to get installment rates: {0}").format(str(e)))

    # =========================================================================
    # CALLBACK VERIFICATION
    # =========================================================================

    def verify_callback(
        self,
        merchant_oid: str,
        status: str,
        total_amount: str,
        hash_value: str,
    ) -> bool:
        """
        Verify PayTR callback/notification signature.

        PayTR sends POST data to merchant_ok_url/merchant_fail_url
        with hash for verification.

        Args:
            merchant_oid: Order ID from callback
            status: Payment status from callback
            total_amount: Amount from callback
            hash_value: Hash from callback for verification

        Returns:
            bool: True if signature is valid
        """
        # PayTR callback hash:
        # hash = base64(hmac_sha256(merchant_oid + merchant_salt + status + total_amount))
        hash_str = f"{merchant_oid}{self.merchant_salt}{status}{total_amount}"
        computed_hash = base64.b64encode(
            hmac.new(
                self.merchant_key.encode("utf-8"),
                hash_str.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")

        return hmac.compare_digest(computed_hash, hash_value)

    def parse_callback(self, post_data: Dict) -> Dict:
        """
        Parse and validate PayTR callback data.

        Args:
            post_data: POST data from PayTR callback

        Returns:
            dict: Parsed callback data

        Raises:
            PayTRCallbackError: If verification fails
        """
        merchant_oid = post_data.get("merchant_oid")
        status = post_data.get("status")
        total_amount = post_data.get("total_amount")
        hash_value = post_data.get("hash")

        # Verify hash
        if not self.verify_callback(merchant_oid, status, total_amount, hash_value):
            raise PayTRCallbackError(
                _("Invalid callback signature"),
                merchant_oid=merchant_oid,
            )

        return {
            "merchant_oid": merchant_oid,
            "status": status,  # "success" or "failed"
            "total_amount": flt(total_amount) / 100,
            "currency": post_data.get("currency"),
            "payment_type": post_data.get("payment_type"),
            "installment_count": cint(post_data.get("installment_count", 1)),
            "failed_reason_code": post_data.get("failed_reason_code"),
            "failed_reason_msg": post_data.get("failed_reason_msg"),
            "test_mode": cint(post_data.get("test_mode", 0)),
        }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _log_payment_event(self, payment_ref: str, event_type: str, details: Dict):
        """Log payment event for audit trail."""
        try:
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"PayTR {event_type}",
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


def create_iframe_token(**kwargs) -> Dict:
    """Convenience function to create iFrame payment token."""
    client = PayTRClient()
    return client.create_iframe_token(**kwargs)


def create_payment(**kwargs) -> Dict:
    """Convenience function to create a payment."""
    client = PayTRClient()
    return client.create_payment(**kwargs)


def refund_payment(
    merchant_oid: str,
    amount: float,
    reason: str = None,
) -> Dict:
    """Convenience function to refund a payment."""
    client = PayTRClient()
    return client.refund_payment(
        merchant_oid=merchant_oid,
        amount=amount,
        reason=reason,
    )


def get_payment_status(merchant_oid: str) -> Dict:
    """Convenience function to get payment status."""
    client = PayTRClient()
    return client.get_payment_status(merchant_oid)


def verify_callback(
    merchant_oid: str,
    status: str,
    total_amount: str,
    hash_value: str,
) -> bool:
    """Convenience function to verify callback signature."""
    client = PayTRClient()
    return client.verify_callback(merchant_oid, status, total_amount, hash_value)


def get_bin_details(bin_number: str) -> Dict:
    """Convenience function to get BIN details."""
    client = PayTRClient()
    return client.get_bin_details(bin_number)


def get_installment_rates(amount: float = None) -> Dict:
    """Convenience function to get installment rates."""
    client = PayTRClient()
    return client.get_installment_rates(amount)


# =============================================================================
# FRAPPE API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_iframe_url(
    payment_intent: str,
    amount: float,
    email: str = None,
    user_name: str = None,
) -> Dict:
    """
    API endpoint to generate PayTR iFrame URL.

    Args:
        payment_intent: Payment Intent name
        amount: Payment amount
        email: Customer email
        user_name: Customer name

    Returns:
        dict: iFrame token and URL
    """
    try:
        # Get Payment Intent details
        if frappe.db.exists("Payment Intent", payment_intent):
            pi = frappe.get_doc("Payment Intent", payment_intent)
            email = email or pi.billing_email
            user_name = user_name or pi.billing_name
            amount = flt(amount) or flt(pi.amount)

        result = create_iframe_token(
            payment_intent=payment_intent,
            amount=amount,
            email=email,
            user_name=user_name,
        )
        return result

    except PayTRError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "PayTR Get iFrame API")
        frappe.throw(_("Failed to create payment form"))


@frappe.whitelist(allow_guest=True)
def handle_callback():
    """
    API endpoint for PayTR payment callback.

    PayTR sends POST request with payment result.
    Must respond with "OK" on success.

    Returns:
        str: "OK" on success
    """
    try:
        post_data = frappe.form_dict

        client = PayTRClient()
        callback_data = client.parse_callback(post_data)

        merchant_oid = callback_data["merchant_oid"]
        status = callback_data["status"]

        # Find and update Payment Intent
        payment_intent = frappe.db.get_value(
            "Payment Intent",
            {"intent_id": merchant_oid},
            "name"
        ) or merchant_oid

        if frappe.db.exists("Payment Intent", payment_intent):
            if status == "success":
                frappe.db.set_value(
                    "Payment Intent",
                    payment_intent,
                    {
                        "status": "Paid",
                        "gateway_response": json.dumps(callback_data),
                        "paid_at": now_datetime(),
                    }
                )
            else:
                frappe.db.set_value(
                    "Payment Intent",
                    payment_intent,
                    {
                        "status": "Failed",
                        "failure_code": callback_data.get("failed_reason_code"),
                        "failure_message": callback_data.get("failed_reason_msg"),
                        "gateway_response": json.dumps(callback_data),
                    }
                )

            frappe.db.commit()

        # PayTR expects "OK" response
        frappe.response["type"] = "text"
        return "OK"

    except PayTRCallbackError as e:
        frappe.log_error(
            f"PayTR callback verification failed: {str(e)}",
            "PayTR Callback Error"
        )
        frappe.response["http_status_code"] = 400
        return "FAIL"
    except Exception as e:
        frappe.log_error(str(e), "PayTR Callback Error")
        frappe.response["http_status_code"] = 500
        return "ERROR"


@frappe.whitelist()
def get_installments(amount: float) -> Dict:
    """
    API endpoint to get installment options.

    Args:
        amount: Payment amount

    Returns:
        dict: Installment rates
    """
    try:
        return get_installment_rates(flt(amount))
    except PayTRError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "PayTR Get Installments API")
        frappe.throw(_("Failed to get installment options"))


@frappe.whitelist()
def get_card_info(bin_number: str) -> Dict:
    """
    API endpoint to get card BIN information.

    Args:
        bin_number: First 6-8 digits of card

    Returns:
        dict: BIN details (bank, card type, etc.)
    """
    try:
        return get_bin_details(bin_number)
    except PayTRError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "PayTR Get Card Info API")
        frappe.throw(_("Failed to get card information"))
