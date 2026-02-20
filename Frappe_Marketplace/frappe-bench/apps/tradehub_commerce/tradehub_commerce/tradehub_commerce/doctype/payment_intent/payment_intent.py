# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, add_to_date, get_datetime, date_diff
)
import json
import hashlib
import hmac


class PaymentIntent(Document):
    """
    Payment Intent DocType for TR-TradeHub.

    Tracks the lifecycle of a payment from creation to completion.
    Supports:
    - Multiple payment gateways (iyzico, PayTR, Stripe)
    - 3D Secure authentication
    - Installment payments (Turkish taksit)
    - Escrow integration
    - ERPNext Payment Entry sync
    - Webhook handling
    - Fraud detection
    """

    def before_insert(self):
        """Set default values before creating a new payment intent."""
        # Generate unique intent ID
        if not self.intent_id:
            self.intent_id = self.generate_intent_id()

        # Set creation timestamp
        if not self.created_at:
            self.created_at = now_datetime()

        # Set default expiration (24 hours)
        if not self.expires_at:
            self.expires_at = add_to_date(now_datetime(), hours=24)

        # Set buyer details from user if not provided
        if self.buyer and not self.billing_name:
            self.set_buyer_details()

        # Initialize metadata
        if not self.metadata:
            self.metadata = "{}"

        # Set base amount if not set
        if not self.base_amount and self.amount:
            self.base_amount = flt(self.amount) * flt(self.exchange_rate or 1)

    def validate(self):
        """Validate payment intent data before saving."""
        self.validate_amount()
        self.validate_buyer()
        self.validate_status_transition()
        self.validate_card_details()
        self.validate_installments()
        self.calculate_net_amount()
        self.check_expiration()

    def on_update(self):
        """Actions after payment intent is updated."""
        # Clear cache
        self.clear_cache()

        # Update linked order if payment is complete
        if self.status in ["Paid", "Captured"] and self.marketplace_order:
            self.update_order_payment_status()

        # Sync to ERPNext if paid
        if self.status == "Paid" and self.erpnext_sync_status == "Not Synced":
            self.create_erpnext_payment_entry()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_intent_id(self):
        """Generate a unique payment intent identifier."""
        import secrets
        return f"pi_{secrets.token_hex(16)}"

    def set_buyer_details(self):
        """Set buyer details from user record."""
        if not self.buyer:
            return

        user = frappe.get_doc("User", self.buyer)
        if not self.billing_name:
            self.billing_name = user.full_name
        if not self.billing_email:
            self.billing_email = user.email
        if not self.billing_phone:
            self.billing_phone = user.mobile_no or user.phone

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_amount(self):
        """Validate payment amount."""
        if flt(self.amount) <= 0:
            frappe.throw(_("Payment amount must be greater than 0"))

        # Validate original amount if provided
        if self.original_amount and flt(self.original_amount) < flt(self.amount):
            frappe.throw(
                _("Original amount cannot be less than payment amount")
            )

    def validate_buyer(self):
        """Validate buyer information."""
        if not self.buyer:
            frappe.throw(_("Buyer is required"))

        # Guest payments may not have user record
        if self.buyer_type != "Guest":
            if not frappe.db.exists("User", self.buyer):
                frappe.throw(_("Buyer {0} does not exist").format(self.buyer))

    def validate_status_transition(self):
        """Validate payment status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Payment Intent", self.name, "status")

        # Define valid transitions
        valid_transitions = {
            "Created": ["Pending", "Processing", "Cancelled", "Expired"],
            "Pending": ["Processing", "Requires Action", "Failed", "Cancelled", "Expired"],
            "Processing": ["Requires Action", "Requires Capture", "Authorized", "Paid", "Captured", "Failed", "Cancelled"],
            "Requires Action": ["Processing", "Authorized", "Paid", "Failed", "Cancelled"],
            "Requires Capture": ["Captured", "Cancelled", "Expired"],
            "Authorized": ["Captured", "Paid", "Cancelled", "Expired"],
            "Captured": ["Paid", "Refunded", "Partially Refunded", "Disputed"],
            "Paid": ["Refunded", "Partially Refunded", "Disputed"],
            "Partially Paid": ["Paid", "Refunded", "Cancelled"],
            "Failed": ["Pending", "Processing", "Cancelled"],
            "Cancelled": [],
            "Expired": [],
            "Refunded": [],
            "Partially Refunded": ["Refunded"],
            "Disputed": ["Refunded", "Paid"]
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change payment status from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_card_details(self):
        """Validate card details if provided."""
        if self.payment_method in ["Credit Card", "Debit Card"]:
            if self.card_last_four and len(self.card_last_four) != 4:
                frappe.throw(_("Card last four digits must be exactly 4 digits"))

            if self.card_expiry_month:
                if not (1 <= cint(self.card_expiry_month) <= 12):
                    frappe.throw(_("Card expiry month must be between 1 and 12"))

            if self.card_expiry_year:
                current_year = getdate().year
                if cint(self.card_expiry_year) < current_year:
                    frappe.throw(_("Card has expired"))

    def validate_installments(self):
        """Validate installment details if enabled."""
        if self.has_installments:
            if cint(self.installment_count) < 2:
                frappe.throw(
                    _("Installment count must be at least 2")
                )

            if cint(self.installment_count) > 12:
                frappe.throw(
                    _("Maximum installment count is 12")
                )

            # Calculate installment total if not set
            if not self.installment_total:
                self.installment_total = (
                    flt(self.amount) + flt(self.installment_fee)
                )

            # Calculate per-installment amount
            if not self.installment_amount and flt(self.installment_total) > 0:
                self.installment_amount = (
                    flt(self.installment_total) / cint(self.installment_count)
                )

    def calculate_net_amount(self):
        """Calculate net amount after fees."""
        self.net_amount = flt(self.amount) - flt(self.fee_amount)

        # Update base amount with exchange rate
        if flt(self.exchange_rate) > 0:
            self.base_amount = flt(self.amount) * flt(self.exchange_rate)

    def check_expiration(self):
        """Check and update if payment intent has expired."""
        if self.status in ["Created", "Pending", "Processing"]:
            if self.expires_at and get_datetime(self.expires_at) < now_datetime():
                self.status = "Expired"

    # =================================================================
    # Payment Processing Methods
    # =================================================================

    def start_processing(self):
        """Mark payment as processing."""
        if self.status not in ["Created", "Pending", "Failed"]:
            frappe.throw(
                _("Cannot start processing from {0} status").format(self.status)
            )

        self.db_set("status", "Processing")
        self.db_set("processing_started_at", now_datetime())
        self.clear_cache()

    def require_action(self, action_type="3d_secure"):
        """Mark payment as requiring action (e.g., 3D Secure)."""
        if self.status not in ["Pending", "Processing"]:
            frappe.throw(
                _("Cannot require action from {0} status").format(self.status)
            )

        self.db_set("status", "Requires Action")

        if action_type == "3d_secure":
            self.db_set("requires_3d_secure", 1)
            self.db_set("three_d_status", "Initiated")

        self.clear_cache()

    def authorize(self, authorization_code=None, expires_hours=168):
        """
        Authorize payment (for capture later).

        Args:
            authorization_code: Authorization code from gateway
            expires_hours: Hours until authorization expires (default 7 days)
        """
        if self.status not in ["Processing", "Requires Action"]:
            frappe.throw(
                _("Cannot authorize from {0} status").format(self.status)
            )

        self.db_set("status", "Authorized")
        self.db_set("authorized_at", now_datetime())
        self.db_set("authorization_expires", add_to_date(now_datetime(), hours=expires_hours))

        if authorization_code:
            self.db_set("authorization_code", authorization_code)

        self.clear_cache()

    def capture(self, amount=None):
        """
        Capture authorized payment.

        Args:
            amount: Amount to capture (defaults to full amount)
        """
        if self.status not in ["Authorized", "Requires Capture"]:
            frappe.throw(
                _("Cannot capture from {0} status. Payment must be authorized first.").format(self.status)
            )

        capture_amount = flt(amount) if amount else flt(self.amount)

        if capture_amount > flt(self.amount):
            frappe.throw(_("Capture amount cannot exceed payment amount"))

        self.db_set("status", "Captured")
        self.db_set("captured_at", now_datetime())
        self.db_set("captured_amount", capture_amount)

        # If full capture, mark as paid
        if capture_amount >= flt(self.amount):
            self.mark_paid()
        else:
            # Partial capture
            self.db_set("status", "Partially Paid")

        self.clear_cache()

    def mark_paid(self, payment_id=None, reference=None):
        """
        Mark payment as successfully paid.

        Args:
            payment_id: Gateway payment ID
            reference: Additional reference
        """
        if self.status not in ["Processing", "Authorized", "Captured", "Requires Action"]:
            frappe.throw(
                _("Cannot mark as paid from {0} status").format(self.status)
            )

        self.db_set("status", "Paid")
        self.db_set("completed_at", now_datetime())

        if payment_id:
            self.db_set("gateway_payment_id", payment_id)

        if reference:
            self.db_set("gateway_reference", reference)

        # Update captured amount if not set
        if not self.captured_amount:
            self.db_set("captured_amount", self.amount)

        # Update order payment status
        if self.marketplace_order:
            self.update_order_payment_status()

        # Hold in escrow if enabled
        if self.escrow_enabled and self.escrow_account:
            self.hold_in_escrow()

        self.clear_cache()

    def mark_failed(self, error_code=None, error_message=None):
        """
        Mark payment as failed.

        Args:
            error_code: Gateway error code
            error_message: Error message
        """
        self.db_set("status", "Failed")
        self.db_set("failed_at", now_datetime())

        if error_code:
            self.db_set("gateway_error_code", error_code)

        if error_message:
            self.db_set("gateway_error_message", error_message)
            self.append_error_log(f"Payment failed: {error_message}")

        # Increment retry count
        self.db_set("retry_count", cint(self.retry_count) + 1)
        self.db_set("last_retry_at", now_datetime())

        self.clear_cache()

    def cancel(self, reason=None):
        """
        Cancel the payment intent.

        Args:
            reason: Cancellation reason
        """
        if self.status in ["Paid", "Captured", "Refunded"]:
            frappe.throw(
                _("Cannot cancel a completed payment. Use refund instead.")
            )

        self.db_set("status", "Cancelled")
        self.db_set("cancelled_at", now_datetime())

        if reason:
            self.db_set("internal_notes", f"Cancelled: {reason}\n{self.internal_notes or ''}")

        # Release any authorization holds
        # (Gateway-specific implementation would go here)

        self.clear_cache()

    # =================================================================
    # 3D Secure Methods
    # =================================================================

    def init_3d_secure(self, callback_url, html_content=None, version="2.0"):
        """
        Initialize 3D Secure authentication.

        Args:
            callback_url: URL to redirect after 3D authentication
            html_content: 3D Secure HTML form (for redirect)
            version: 3D Secure version
        """
        self.db_set("requires_3d_secure", 1)
        self.db_set("three_d_status", "Initiated")
        self.db_set("three_d_callback_url", callback_url)
        self.db_set("three_d_version", version)

        if html_content:
            self.db_set("three_d_html", html_content)

        self.db_set("status", "Requires Action")
        self.clear_cache()

    def complete_3d_secure(self, success=True, response=None):
        """
        Complete 3D Secure authentication.

        Args:
            success: Whether authentication succeeded
            response: Gateway response data
        """
        if success:
            self.db_set("three_d_status", "Authenticated")
            self.db_set("three_d_flow_completed", 1)
            # Continue with payment processing
            self.db_set("status", "Processing")
        else:
            self.db_set("three_d_status", "Failed")
            self.mark_failed("3D_SECURE_FAILED", "3D Secure authentication failed")

        if response:
            self.db_set("gateway_response", json.dumps(response))

        self.clear_cache()

    # =================================================================
    # Refund Methods
    # =================================================================

    def request_refund(self, amount=None, reason=None):
        """
        Request a refund for the payment.

        Args:
            amount: Amount to refund (defaults to full amount)
            reason: Refund reason
        """
        if self.status not in ["Paid", "Captured", "Partially Refunded"]:
            frappe.throw(
                _("Cannot refund a payment that has not been completed")
            )

        refund_amount = flt(amount) if amount else flt(self.amount)
        total_refunded = flt(self.refund_amount) + refund_amount

        if total_refunded > flt(self.amount):
            frappe.throw(_("Refund amount exceeds payment amount"))

        self.db_set("refund_status", "Requested")
        self.db_set("refund_amount", total_refunded)

        if reason:
            self.db_set("refund_reason", reason)

        self.clear_cache()

    def process_refund(self, gateway_refund_id=None):
        """
        Process the refund with gateway.

        Args:
            gateway_refund_id: Refund ID from gateway
        """
        self.db_set("refund_status", "Processing")

        if gateway_refund_id:
            self.db_set("refund_gateway_id", gateway_refund_id)

        self.clear_cache()

    def complete_refund(self, gateway_refund_id=None):
        """
        Mark refund as completed.

        Args:
            gateway_refund_id: Refund ID from gateway
        """
        self.db_set("refunded_at", now_datetime())

        if gateway_refund_id:
            self.db_set("refund_gateway_id", gateway_refund_id)

        # Update status based on refund amount
        if flt(self.refund_amount) >= flt(self.amount):
            self.db_set("status", "Refunded")
            self.db_set("refund_status", "Refunded")
        else:
            self.db_set("status", "Partially Refunded")
            self.db_set("refund_status", "Partially Refunded")

        # Update order refund status
        if self.marketplace_order:
            self.update_order_refund_status()

        self.clear_cache()

    def add_partial_refund(self, amount, reference=None, reason=None):
        """
        Add a partial refund record.

        Args:
            amount: Refund amount
            reference: Gateway reference
            reason: Refund reason
        """
        refunds = json.loads(self.partial_refunds or "[]")
        refunds.append({
            "amount": flt(amount),
            "reference": reference,
            "reason": reason,
            "timestamp": str(now_datetime())
        })

        self.db_set("partial_refunds", json.dumps(refunds))
        self.db_set("refund_amount", flt(self.refund_amount) + flt(amount))

        self.clear_cache()

    # =================================================================
    # Escrow Methods
    # =================================================================

    def hold_in_escrow(self):
        """Hold payment in escrow."""
        if not self.escrow_enabled:
            frappe.throw(_("Escrow is not enabled for this payment"))

        self.db_set("escrow_status", "Held")
        self.db_set("escrow_held_at", now_datetime())

        # Set default release date (7 days after delivery)
        if not self.escrow_release_date:
            self.db_set("escrow_release_date", add_days(nowdate(), 7))

        # Update escrow account if linked
        if self.escrow_account and frappe.db.exists("Escrow Account", self.escrow_account):
            escrow = frappe.get_doc("Escrow Account", self.escrow_account)
            escrow.db_set("held_amount", flt(escrow.held_amount) + flt(self.amount))

        self.clear_cache()

    def release_escrow(self):
        """Release funds from escrow."""
        if self.escrow_status != "Held":
            frappe.throw(_("No funds held in escrow"))

        self.db_set("escrow_status", "Released")
        self.db_set("escrow_released_at", now_datetime())

        # Update escrow account if linked
        if self.escrow_account and frappe.db.exists("Escrow Account", self.escrow_account):
            escrow = frappe.get_doc("Escrow Account", self.escrow_account)
            escrow.db_set("held_amount", flt(escrow.held_amount) - flt(self.amount))
            escrow.db_set("released_amount", flt(escrow.released_amount) + flt(self.amount))

        self.clear_cache()

    # =================================================================
    # ERPNext Integration Methods
    # =================================================================

    def create_erpnext_payment_entry(self):
        """Create a linked ERPNext Payment Entry."""
        if not frappe.db.exists("DocType", "Payment Entry"):
            frappe.log_error(
                "ERPNext Payment Entry DocType not found",
                "Payment Intent Sync Error"
            )
            self.db_set("erpnext_sync_status", "Failed")
            self.db_set("erpnext_sync_error", "Payment Entry DocType not found")
            return

        try:
            self.db_set("erpnext_sync_status", "Pending")

            # Get customer from order
            customer = None
            if self.marketplace_order:
                customer = frappe.db.get_value(
                    "Marketplace Order", self.marketplace_order, "erpnext_customer"
                )

            if not customer:
                # Try to find customer by email
                customer = frappe.db.get_value(
                    "Customer", {"email_id": self.billing_email}, "name"
                )

            if not customer:
                raise Exception("ERPNext Customer not found")

            # Create Payment Entry
            pe_data = {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "posting_date": nowdate(),
                "company": frappe.defaults.get_user_default("Company"),
                "mode_of_payment": self.get_mode_of_payment(),
                "paid_amount": flt(self.amount),
                "received_amount": flt(self.amount),
                "reference_no": self.intent_id,
                "reference_date": nowdate(),
                "remarks": f"Payment for {self.marketplace_order or 'Marketplace Payment'}"
            }

            # Get accounts
            pe_data["paid_to"] = self.get_payment_account()
            pe_data["paid_to_account_currency"] = self.currency

            payment_entry = frappe.get_doc(pe_data)
            payment_entry.flags.ignore_permissions = True
            payment_entry.insert()

            # Store reference
            self.db_set("erpnext_payment_entry", payment_entry.name)
            self.db_set("erpnext_sync_status", "Synced")

            frappe.msgprint(
                _("ERPNext Payment Entry {0} created").format(payment_entry.name)
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to create ERPNext Payment Entry for {self.name}: {str(e)}",
                "Payment Intent ERPNext Sync Error"
            )
            self.db_set("erpnext_sync_status", "Failed")
            self.db_set("erpnext_sync_error", str(e))

    def get_mode_of_payment(self):
        """Get ERPNext Mode of Payment based on payment method."""
        mode_mapping = {
            "Credit Card": "Credit Card",
            "Debit Card": "Debit Card",
            "Bank Transfer": "Bank Transfer",
            "Wallet": "Wire Transfer",
            "Cash on Delivery": "Cash"
        }
        mode_name = mode_mapping.get(self.payment_method, "Wire Transfer")

        # Check if mode exists, create if not
        if not frappe.db.exists("Mode of Payment", mode_name):
            return "Wire Transfer"  # Fallback

        return mode_name

    def get_payment_account(self):
        """Get the payment account for ERPNext."""
        # Try to get from payment gateway settings
        gateway_account_map = {
            "iyzico": "iyzico Account",
            "PayTR": "PayTR Account",
            "Stripe": "Stripe Account"
        }

        account_name = gateway_account_map.get(self.payment_gateway)
        if account_name:
            account = frappe.db.get_value("Account", {"account_name": account_name}, "name")
            if account:
                return account

        # Default to company's default receivable account
        company = frappe.defaults.get_user_default("Company")
        if company:
            return frappe.db.get_value(
                "Company", company, "default_receivable_account"
            )

        return None

    # =================================================================
    # Order Integration Methods
    # =================================================================

    def update_order_payment_status(self):
        """Update linked order's payment status."""
        if not self.marketplace_order:
            return

        try:
            order = frappe.get_doc("Marketplace Order", self.marketplace_order)

            if self.status == "Paid":
                order.record_payment(
                    amount=self.amount,
                    payment_reference=self.gateway_payment_id or self.intent_id,
                    payment_method=self.payment_method
                )
            elif self.status == "Failed":
                order.db_set("payment_status", "Failed")

        except Exception as e:
            frappe.log_error(
                f"Failed to update order payment status: {str(e)}",
                "Payment Intent Order Update Error"
            )

    def update_order_refund_status(self):
        """Update linked order's refund status."""
        if not self.marketplace_order:
            return

        try:
            order = frappe.get_doc("Marketplace Order", self.marketplace_order)
            order.process_refund(
                amount=self.refund_amount,
                reason=self.refund_reason,
                reference=self.refund_gateway_id
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to update order refund status: {str(e)}",
                "Payment Intent Order Refund Update Error"
            )

    # =================================================================
    # Webhook Methods
    # =================================================================

    def record_webhook(self, event_type, payload, verified=True):
        """
        Record a webhook event from payment gateway.

        Args:
            event_type: Type of webhook event
            payload: Webhook payload
            verified: Whether webhook signature was verified
        """
        self.db_set("last_webhook_at", now_datetime())
        self.db_set("webhook_count", cint(self.webhook_count) + 1)
        self.db_set("last_webhook_event", event_type)
        self.db_set("webhook_verified", 1 if verified else 0)
        self.db_set("webhook_response", json.dumps(payload) if payload else None)

        self.clear_cache()

    # =================================================================
    # Fraud Detection Methods
    # =================================================================

    def calculate_risk_score(self):
        """Calculate risk score based on various factors."""
        score = 0
        flags = []

        # Check for high-risk indicators
        if not self.billing_phone:
            score += 10
            flags.append("missing_phone")

        if self.buyer_type == "Guest":
            score += 15
            flags.append("guest_checkout")

        # Check payment amount
        if flt(self.amount) > 10000:  # High value transaction
            score += 20
            flags.append("high_value")

        # Check for mismatched billing/shipping (if order linked)
        if self.marketplace_order:
            order = frappe.get_doc("Marketplace Order", self.marketplace_order)
            if order.billing_country != order.shipping_country:
                score += 15
                flags.append("country_mismatch")

        # Check for multiple failed attempts
        if cint(self.retry_count) > 2:
            score += 25
            flags.append("multiple_failures")

        # Update fields
        self.db_set("risk_score", min(score, 100))
        self.db_set("fraud_flags", json.dumps(flags))

        # Set risk level
        if score >= 70:
            self.db_set("risk_level", "Critical")
            self.db_set("is_flagged", 1)
        elif score >= 50:
            self.db_set("risk_level", "High")
            self.db_set("is_flagged", 1)
        elif score >= 30:
            self.db_set("risk_level", "Medium")
        else:
            self.db_set("risk_level", "Low")

        return score

    def flag_for_review(self, reason=None):
        """Flag payment for manual review."""
        self.db_set("is_flagged", 1)
        self.db_set("fraud_check_status", "Review Required")

        if reason:
            self.append_error_log(f"Flagged for review: {reason}")

        self.clear_cache()

    # =================================================================
    # Utility Methods
    # =================================================================

    def append_error_log(self, message):
        """Append message to error log."""
        timestamp = now_datetime()
        log_entry = f"[{timestamp}] {message}\n"
        current_log = self.error_log or ""
        self.db_set("error_log", current_log + log_entry)

    def clear_cache(self):
        """Clear cached payment intent data."""
        frappe.cache().delete_value(f"payment_intent:{self.name}")
        if self.intent_id:
            frappe.cache().delete_value(f"payment_intent_by_id:{self.intent_id}")

    def get_summary(self):
        """Get payment intent summary for display."""
        return {
            "name": self.name,
            "intent_id": self.intent_id,
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "payment_method": self.payment_method,
            "payment_gateway": self.payment_gateway,
            "buyer": self.buyer,
            "marketplace_order": self.marketplace_order,
            "created_at": str(self.created_at),
            "completed_at": str(self.completed_at) if self.completed_at else None,
            "is_3d_secure": self.requires_3d_secure,
            "has_installments": self.has_installments,
            "installment_count": self.installment_count if self.has_installments else None,
            "escrow_enabled": self.escrow_enabled,
            "escrow_status": self.escrow_status if self.escrow_enabled else None
        }

    def can_retry(self):
        """Check if payment can be retried."""
        if self.status not in ["Failed", "Cancelled"]:
            return False

        if cint(self.retry_count) >= 3:
            return False

        if self.expires_at and get_datetime(self.expires_at) < now_datetime():
            return False

        return True


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def create_payment_intent(
    amount,
    currency="TRY",
    buyer=None,
    marketplace_order=None,
    payment_gateway=None,
    payment_method=None,
    metadata=None
):
    """
    Create a new payment intent.

    Args:
        amount: Payment amount
        currency: Currency code (default TRY)
        buyer: Buyer user (defaults to current user)
        marketplace_order: Linked marketplace order
        payment_gateway: Payment gateway (iyzico, PayTR, Stripe)
        payment_method: Payment method
        metadata: Additional metadata JSON

    Returns:
        dict: Payment intent details
    """
    if not buyer:
        buyer = frappe.session.user

    if buyer == "Guest":
        frappe.throw(_("Guest users must provide buyer information"))

    intent = frappe.get_doc({
        "doctype": "Payment Intent",
        "amount": flt(amount),
        "currency": currency,
        "buyer": buyer,
        "marketplace_order": marketplace_order,
        "payment_gateway": payment_gateway,
        "payment_method": payment_method,
        "metadata": json.dumps(metadata) if metadata else "{}"
    })

    intent.insert(ignore_permissions=True)

    return {
        "status": "success",
        "name": intent.name,
        "intent_id": intent.intent_id,
        "amount": intent.amount,
        "currency": intent.currency,
        "expires_at": str(intent.expires_at)
    }


@frappe.whitelist()
def get_payment_intent(intent_name=None, intent_id=None):
    """
    Get payment intent details.

    Args:
        intent_name: Frappe document name
        intent_id: Public intent ID

    Returns:
        dict: Payment intent details
    """
    if not intent_name and not intent_id:
        frappe.throw(_("Either intent_name or intent_id is required"))

    if intent_id and not intent_name:
        intent_name = frappe.db.get_value(
            "Payment Intent", {"intent_id": intent_id}, "name"
        )

    if not intent_name:
        return {"error": _("Payment intent not found")}

    intent = frappe.get_doc("Payment Intent", intent_name)

    # Permission check
    if frappe.session.user != "Administrator":
        if intent.buyer != frappe.session.user:
            if not frappe.has_permission("Payment Intent", "read"):
                return {"error": _("Not permitted to view this payment")}

    return intent.get_summary()


@frappe.whitelist()
def update_payment_status(intent_name, status, **kwargs):
    """
    Update payment intent status.

    Args:
        intent_name: Payment intent name
        status: New status
        **kwargs: Additional status-specific parameters

    Returns:
        dict: Updated status
    """
    intent = frappe.get_doc("Payment Intent", intent_name)

    # Permission check
    if not frappe.has_permission("Payment Intent", "write"):
        frappe.throw(_("Not permitted to update this payment"))

    if status == "processing":
        intent.start_processing()
    elif status == "authorized":
        intent.authorize(kwargs.get("authorization_code"))
    elif status == "captured":
        intent.capture(kwargs.get("amount"))
    elif status == "paid":
        intent.mark_paid(kwargs.get("payment_id"), kwargs.get("reference"))
    elif status == "failed":
        intent.mark_failed(kwargs.get("error_code"), kwargs.get("error_message"))
    elif status == "cancelled":
        intent.cancel(kwargs.get("reason"))
    else:
        frappe.throw(_("Invalid status: {0}").format(status))

    return {
        "status": "success",
        "payment_status": intent.status,
        "message": _("Payment status updated to {0}").format(intent.status)
    }


@frappe.whitelist()
def process_refund(intent_name, amount=None, reason=None):
    """
    Process a refund for a payment intent.

    Args:
        intent_name: Payment intent name
        amount: Refund amount (defaults to full amount)
        reason: Refund reason

    Returns:
        dict: Refund status
    """
    intent = frappe.get_doc("Payment Intent", intent_name)

    # Permission check
    if not frappe.has_permission("Payment Intent", "write"):
        frappe.throw(_("Not permitted to refund this payment"))

    intent.request_refund(flt(amount) if amount else None, reason)

    return {
        "status": "success",
        "refund_status": intent.refund_status,
        "refund_amount": intent.refund_amount,
        "message": _("Refund request submitted")
    }


@frappe.whitelist()
def get_payment_statistics(gateway=None, days=30):
    """
    Get payment statistics.

    Args:
        gateway: Filter by payment gateway
        days: Number of days to analyze

    Returns:
        dict: Payment statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"created_at": [">=", from_date]}
    if gateway:
        filters["payment_gateway"] = gateway

    # Get status breakdown
    status_data = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as count,
            SUM(amount) as total_amount,
            AVG(amount) as avg_amount
        FROM `tabPayment Intent`
        WHERE created_at >= %(from_date)s
        {gateway_filter}
        GROUP BY status
    """.format(
        gateway_filter=f"AND payment_gateway = %(gateway)s" if gateway else ""
    ), {"from_date": from_date, "gateway": gateway}, as_dict=True)

    # Get gateway breakdown
    gateway_data = frappe.db.sql("""
        SELECT
            payment_gateway,
            COUNT(*) as count,
            SUM(CASE WHEN status = 'Paid' THEN amount ELSE 0 END) as successful_amount,
            SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed_count
        FROM `tabPayment Intent`
        WHERE created_at >= %(from_date)s
        AND payment_gateway IS NOT NULL
        GROUP BY payment_gateway
    """, {"from_date": from_date}, as_dict=True)

    # Calculate totals
    total_count = sum(s.count for s in status_data)
    total_amount = sum(flt(s.total_amount) for s in status_data)
    paid_data = next((s for s in status_data if s.status == "Paid"), None)

    return {
        "period_days": cint(days),
        "total_intents": total_count,
        "total_amount": total_amount,
        "successful_amount": flt(paid_data.total_amount) if paid_data else 0,
        "success_rate": (paid_data.count / total_count * 100) if paid_data and total_count > 0 else 0,
        "average_amount": total_amount / total_count if total_count > 0 else 0,
        "status_breakdown": {s.status: {"count": s.count, "amount": s.total_amount} for s in status_data},
        "gateway_breakdown": {g.payment_gateway: {
            "count": g.count,
            "successful_amount": g.successful_amount,
            "failed_count": g.failed_count
        } for g in gateway_data}
    }


@frappe.whitelist(allow_guest=True)
def handle_webhook(gateway, payload, signature=None):
    """
    Handle webhook from payment gateway.

    Args:
        gateway: Payment gateway name
        payload: Webhook payload
        signature: Webhook signature for verification

    Returns:
        dict: Webhook processing result
    """
    # Verify webhook signature based on gateway
    if gateway == "iyzico":
        verified = verify_iyzico_webhook(payload, signature)
    elif gateway == "PayTR":
        verified = verify_paytr_webhook(payload, signature)
    elif gateway == "Stripe":
        verified = verify_stripe_webhook(payload, signature)
    else:
        verified = False

    if not verified:
        frappe.log_error(
            f"Webhook signature verification failed for {gateway}",
            "Payment Webhook Error"
        )
        return {"status": "error", "message": "Invalid signature"}

    # Parse payload
    data = json.loads(payload) if isinstance(payload, str) else payload

    # Find payment intent
    intent_id = None
    event_type = data.get("event_type") or data.get("type")

    # Gateway-specific intent ID extraction
    if gateway == "iyzico":
        intent_id = data.get("paymentId")
    elif gateway == "PayTR":
        intent_id = data.get("merchant_oid")
    elif gateway == "Stripe":
        intent_id = data.get("data", {}).get("object", {}).get("id")

    if not intent_id:
        return {"status": "error", "message": "Payment intent ID not found in payload"}

    # Find and update payment intent
    intent_name = frappe.db.get_value(
        "Payment Intent",
        {"gateway_intent_id": intent_id},
        "name"
    )

    if not intent_name:
        intent_name = frappe.db.get_value(
            "Payment Intent",
            {"intent_id": intent_id},
            "name"
        )

    if not intent_name:
        return {"status": "error", "message": "Payment intent not found"}

    intent = frappe.get_doc("Payment Intent", intent_name)

    # Record webhook
    intent.record_webhook(event_type, data, verified)

    # Process webhook event
    process_webhook_event(intent, gateway, event_type, data)

    return {"status": "success", "message": "Webhook processed"}


def verify_iyzico_webhook(payload, signature):
    """Verify iyzico webhook signature."""
    # Implementation depends on iyzico webhook format
    return True  # Placeholder


def verify_paytr_webhook(payload, signature):
    """Verify PayTR webhook signature."""
    # Implementation depends on PayTR webhook format
    return True  # Placeholder


def verify_stripe_webhook(payload, signature):
    """Verify Stripe webhook signature."""
    # Implementation depends on Stripe webhook format
    return True  # Placeholder


def process_webhook_event(intent, gateway, event_type, data):
    """Process webhook event based on gateway and type."""
    # Map common event types
    success_events = ["payment.success", "payment_intent.succeeded", "charge.succeeded"]
    failed_events = ["payment.failed", "payment_intent.failed", "charge.failed"]
    refund_events = ["refund.success", "charge.refunded"]

    if event_type in success_events:
        intent.mark_paid(
            payment_id=data.get("paymentId") or data.get("id"),
            reference=data.get("reference")
        )
    elif event_type in failed_events:
        intent.mark_failed(
            error_code=data.get("errorCode"),
            error_message=data.get("errorMessage")
        )
    elif event_type in refund_events:
        intent.complete_refund(
            gateway_refund_id=data.get("refundId") or data.get("id")
        )
