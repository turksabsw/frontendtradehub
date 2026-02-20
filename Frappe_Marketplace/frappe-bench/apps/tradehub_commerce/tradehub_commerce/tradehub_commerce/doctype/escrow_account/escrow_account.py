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


class EscrowAccount(Document):
    """
    Escrow Account DocType for TR-TradeHub.

    Manages the escrow holding of funds between buyers and sellers.
    Supports:
    - Fund holding until delivery confirmation
    - Automatic release after timeout
    - Dispute handling and resolution
    - Partial releases
    - Seller payout management
    - Hold extensions
    - ERPNext integration
    """

    def before_insert(self):
        """Set default values before creating a new escrow account."""
        # Generate unique escrow ID
        if not self.escrow_id:
            self.escrow_id = self.generate_escrow_id()

        # Set creation timestamp
        if not self.created_at:
            self.created_at = now_datetime()

        # Initialize amounts
        self.held_amount = flt(self.total_amount)
        self.released_amount = 0
        self.refunded_amount = 0
        self.pending_release_amount = 0

        # Calculate fees and net amount
        self.calculate_fees()

        # Set scheduled release date if not set
        if not self.scheduled_release_date and self.auto_release_enabled:
            self.set_default_release_date()

        # Initialize partial releases
        if not self.partial_releases:
            self.partial_releases = "[]"

        # Initialize metadata
        if not self.metadata:
            self.metadata = "{}"

    def validate(self):
        """Validate escrow account data before saving."""
        self.validate_amounts()
        self.validate_parties()
        self.validate_status_transition()
        self.validate_release_settings()
        self.calculate_fees()
        self.update_payout_amount()

    def on_update(self):
        """Actions after escrow account is updated."""
        # Clear cache
        self.clear_cache()

        # Log event for status changes
        if self.has_value_changed("status"):
            self.log_escrow_event(
                f"Status changed to {self.status}",
                event_type="Status Change",
                old_status=self.get_doc_before_save().status if self.get_doc_before_save() else None,
                new_status=self.status
            )

        # Update related orders
        if self.status in ["Released", "Refunded"] and self.sub_order:
            self.update_sub_order_status()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_escrow_id(self):
        """Generate a unique escrow identifier."""
        import secrets
        return f"esc_{secrets.token_hex(12)}"

    def set_default_release_date(self):
        """Set the default scheduled release date based on settings."""
        days = cint(self.auto_release_days) or 7
        self.scheduled_release_date = add_days(now_datetime(), days)

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_amounts(self):
        """Validate escrow amounts."""
        if flt(self.total_amount) <= 0:
            frappe.throw(_("Total amount must be greater than 0"))

        # Validate amount consistency
        total_distributed = (
            flt(self.held_amount) +
            flt(self.released_amount) +
            flt(self.refunded_amount)
        )

        if abs(total_distributed - flt(self.total_amount)) > 0.01:
            # Auto-correct held amount
            self.held_amount = (
                flt(self.total_amount) -
                flt(self.released_amount) -
                flt(self.refunded_amount)
            )

        if flt(self.held_amount) < 0:
            frappe.throw(_("Held amount cannot be negative"))

    def validate_parties(self):
        """Validate buyer and seller."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not self.buyer:
            frappe.throw(_("Buyer is required"))

        # Validate seller exists
        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

        # Validate buyer exists
        if not frappe.db.exists("User", self.buyer):
            frappe.throw(_("Buyer {0} does not exist").format(self.buyer))

    def validate_status_transition(self):
        """Validate escrow status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Escrow Account", self.name, "status")

        # Define valid transitions
        valid_transitions = {
            "Pending": ["Funds Held", "Cancelled"],
            "Funds Held": [
                "Partially Released", "Released", "Disputed",
                "Refunded", "Partially Refunded", "Cancelled"
            ],
            "Partially Released": [
                "Released", "Disputed", "Partially Refunded", "Refunded"
            ],
            "Released": [],  # Terminal state
            "Disputed": ["Dispute Resolved", "Refunded", "Released", "Partially Refunded"],
            "Dispute Resolved": ["Released", "Refunded", "Partially Refunded"],
            "Refunded": [],  # Terminal state
            "Partially Refunded": ["Refunded", "Released"],
            "Cancelled": [],  # Terminal state
            "Expired": []  # Terminal state
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change escrow status from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_release_settings(self):
        """Validate release settings."""
        if self.auto_release_enabled:
            if cint(self.auto_release_days) < 1:
                frappe.throw(_("Auto release days must be at least 1"))

            if cint(self.auto_release_days) > 90:
                frappe.throw(_("Auto release days cannot exceed 90"))

    # =================================================================
    # Fee Calculation Methods
    # =================================================================

    def calculate_fees(self):
        """Calculate total fees and net amount to seller."""
        self.total_fees = (
            flt(self.commission_amount) +
            flt(self.platform_fee) +
            flt(self.processing_fee)
        )

        self.net_amount_to_seller = flt(self.total_amount) - flt(self.total_fees)

        # Ensure net amount is not negative
        if flt(self.net_amount_to_seller) < 0:
            frappe.throw(_("Net amount to seller cannot be negative"))

    def set_commission_from_seller(self):
        """Calculate commission based on seller's commission plan."""
        if not self.seller:
            return

        seller = frappe.get_doc("Seller Profile", self.seller)

        # Get commission plan
        if seller.commission_plan:
            plan = frappe.get_doc("Commission Plan", seller.commission_plan)
            commission = plan.calculate_commission(flt(self.total_amount))
            self.commission_amount = commission.get("total_commission", 0)
        else:
            # Default commission rate (10%)
            self.commission_amount = flt(self.total_amount) * 0.10

        self.calculate_fees()

    def update_payout_amount(self):
        """Update the payout amount based on released amount and fees."""
        if flt(self.released_amount) > 0:
            # Calculate proportional fees
            release_ratio = flt(self.released_amount) / flt(self.total_amount)
            proportional_fees = flt(self.total_fees) * release_ratio
            self.payout_amount = flt(self.released_amount) - proportional_fees

    # =================================================================
    # Fund Holding Methods
    # =================================================================

    def hold_funds(self, amount=None, payment_intent=None):
        """
        Hold funds in escrow.

        Args:
            amount: Amount to hold (defaults to total_amount)
            payment_intent: Linked payment intent
        """
        if self.status not in ["Pending"]:
            frappe.throw(
                _("Can only hold funds from Pending status")
            )

        hold_amount = flt(amount) if amount else flt(self.total_amount)

        if hold_amount > flt(self.total_amount):
            frappe.throw(_("Cannot hold more than total amount"))

        self.db_set("held_amount", hold_amount)
        self.db_set("status", "Funds Held")

        if payment_intent:
            self.db_set("payment_intent", payment_intent)

        # Log event
        self.log_escrow_event(
            f"Funds held: {self.currency} {hold_amount}",
            event_type="Funds Held",
            amount=hold_amount
        )

        self.clear_cache()

    # =================================================================
    # Release Methods
    # =================================================================

    def release_funds(self, amount=None, trigger=None, approved_by=None):
        """
        Release funds to seller.

        Args:
            amount: Amount to release (defaults to held amount)
            trigger: What triggered the release
            approved_by: User who approved the release
        """
        if self.status not in ["Funds Held", "Partially Released", "Dispute Resolved"]:
            frappe.throw(
                _("Cannot release funds from {0} status").format(self.status)
            )

        if self.has_dispute and self.dispute_status not in ["Resolved", "Closed"]:
            frappe.throw(_("Cannot release funds while dispute is active"))

        release_amount = flt(amount) if amount else flt(self.held_amount)

        if release_amount <= 0:
            frappe.throw(_("Release amount must be greater than 0"))

        if release_amount > flt(self.held_amount):
            frappe.throw(
                _("Release amount ({0}) exceeds held amount ({1})").format(
                    release_amount, self.held_amount
                )
            )

        # Update amounts
        new_held = flt(self.held_amount) - release_amount
        new_released = flt(self.released_amount) + release_amount

        self.db_set("held_amount", new_held)
        self.db_set("released_amount", new_released)

        # Update release info
        if trigger:
            self.db_set("release_trigger", trigger)

        if approved_by:
            self.db_set("release_approved_by", approved_by)
            self.db_set("release_approved_at", now_datetime())

        # Update status
        if new_held <= 0:
            self.db_set("status", "Released")
            self.db_set("closed_at", now_datetime())
        else:
            self.db_set("status", "Partially Released")

        # Record partial release
        self.add_partial_release(release_amount, "release", trigger)

        # Update payout
        self.update_payout_amount()
        self.db_set("payout_amount", self.payout_amount)

        # Log event
        self.log_escrow_event(
            f"Funds released: {self.currency} {release_amount}",
            event_type="Funds Released",
            amount=release_amount,
            trigger=trigger
        )

        # Trigger payout process
        if new_held <= 0:
            self.schedule_payout()

        self.clear_cache()

    def confirm_delivery(self, confirmed_by=None):
        """
        Confirm delivery and trigger release countdown.

        Args:
            confirmed_by: User who confirmed delivery
        """
        if self.status not in ["Funds Held", "Partially Released"]:
            frappe.throw(_("Cannot confirm delivery in {0} status").format(self.status))

        self.db_set("delivery_confirmed_at", now_datetime())

        # Update scheduled release date
        days = cint(self.auto_release_days) or 7
        new_release_date = add_days(now_datetime(), days)
        self.db_set("scheduled_release_date", new_release_date)

        # Log event
        self.log_escrow_event(
            "Delivery confirmed",
            event_type="Delivery Confirmed",
            confirmed_by=confirmed_by
        )

        self.clear_cache()

    def approve_release(self, approved_by=None):
        """
        Buyer approves release of funds.

        Args:
            approved_by: User who approved
        """
        self.release_funds(
            amount=None,
            trigger="Buyer Confirmed",
            approved_by=approved_by or frappe.session.user
        )

    def auto_release(self):
        """Automatically release funds after timeout."""
        if self.status not in ["Funds Held", "Partially Released"]:
            return False

        if self.has_dispute and self.dispute_status not in ["Resolved", "Closed"]:
            return False

        if not self.scheduled_release_date:
            return False

        if get_datetime(self.scheduled_release_date) > now_datetime():
            return False

        self.release_funds(
            amount=None,
            trigger="Auto Released After Timeout"
        )

        return True

    # =================================================================
    # Refund Methods
    # =================================================================

    def refund_funds(self, amount=None, reason=None):
        """
        Refund funds to buyer.

        Args:
            amount: Amount to refund (defaults to held amount)
            reason: Refund reason
        """
        if self.status not in ["Funds Held", "Partially Released", "Disputed", "Dispute Resolved"]:
            frappe.throw(
                _("Cannot refund from {0} status").format(self.status)
            )

        refund_amount = flt(amount) if amount else flt(self.held_amount)

        if refund_amount <= 0:
            frappe.throw(_("Refund amount must be greater than 0"))

        if refund_amount > flt(self.held_amount):
            frappe.throw(
                _("Refund amount ({0}) exceeds held amount ({1})").format(
                    refund_amount, self.held_amount
                )
            )

        # Update amounts
        new_held = flt(self.held_amount) - refund_amount
        new_refunded = flt(self.refunded_amount) + refund_amount

        self.db_set("held_amount", new_held)
        self.db_set("refunded_amount", new_refunded)

        # Update status
        if new_held <= 0:
            self.db_set("status", "Refunded")
            self.db_set("closed_at", now_datetime())
        else:
            self.db_set("status", "Partially Refunded")

        # Record partial release
        self.add_partial_release(refund_amount, "refund", reason)

        # Update payment intent if linked
        if self.payment_intent:
            self.trigger_payment_refund(refund_amount, reason)

        # Log event
        self.log_escrow_event(
            f"Funds refunded: {self.currency} {refund_amount}",
            event_type="Funds Refunded",
            amount=refund_amount,
            reason=reason
        )

        self.clear_cache()

    def trigger_payment_refund(self, amount, reason=None):
        """Trigger refund on the linked payment intent."""
        if not self.payment_intent:
            return

        try:
            from tradehub_commerce.tradehub_commerce.doctype.payment_intent.payment_intent import process_refund
            process_refund(self.payment_intent, amount, reason)
        except Exception as e:
            frappe.log_error(
                f"Failed to trigger payment refund: {str(e)}",
                "Escrow Refund Error"
            )

    # =================================================================
    # Dispute Methods
    # =================================================================

    def open_dispute(self, reason=None, opened_by=None, dispute_case=None):
        """
        Open a dispute on the escrow.

        Args:
            reason: Dispute reason
            opened_by: User who opened dispute
            dispute_case: Linked moderation case
        """
        if self.status not in ["Funds Held", "Partially Released"]:
            frappe.throw(
                _("Cannot open dispute in {0} status").format(self.status)
            )

        if self.has_dispute:
            frappe.throw(_("Dispute already exists for this escrow"))

        self.db_set("has_dispute", 1)
        self.db_set("status", "Disputed")
        self.db_set("dispute_status", "Open")
        self.db_set("dispute_opened_at", now_datetime())

        if dispute_case:
            self.db_set("dispute_case", dispute_case)

        # Extend hold during dispute
        self.extend_hold("Dispute Investigation", days=30)

        # Log event
        self.log_escrow_event(
            f"Dispute opened: {reason or 'No reason provided'}",
            event_type="Dispute Opened",
            opened_by=opened_by,
            reason=reason
        )

        self.clear_cache()

    def resolve_dispute(
        self,
        resolution,
        amount_to_buyer=0,
        amount_to_seller=0,
        resolved_by=None
    ):
        """
        Resolve a dispute.

        Args:
            resolution: Resolution decision
            amount_to_buyer: Amount to refund to buyer
            amount_to_seller: Amount to release to seller
            resolved_by: User who resolved
        """
        if not self.has_dispute:
            frappe.throw(_("No dispute to resolve"))

        if self.dispute_status not in ["Open", "Under Review", "Escalated"]:
            frappe.throw(
                _("Cannot resolve dispute in {0} status").format(self.dispute_status)
            )

        # Validate amounts
        total_resolution = flt(amount_to_buyer) + flt(amount_to_seller)
        if total_resolution > flt(self.held_amount):
            frappe.throw(
                _("Resolution amounts exceed held amount")
            )

        self.db_set("dispute_resolution", resolution)
        self.db_set("dispute_status", "Resolved")
        self.db_set("dispute_resolved_at", now_datetime())
        self.db_set("status", "Dispute Resolved")

        if amount_to_buyer:
            self.db_set("dispute_amount_to_buyer", amount_to_buyer)

        if amount_to_seller:
            self.db_set("dispute_amount_to_seller", amount_to_seller)

        # Execute resolution
        if flt(amount_to_buyer) > 0:
            self.refund_funds(amount_to_buyer, f"Dispute resolution: {resolution}")

        if flt(amount_to_seller) > 0:
            self.release_funds(
                amount_to_seller,
                "Dispute Resolution",
                resolved_by
            )

        # Log event
        self.log_escrow_event(
            f"Dispute resolved: {resolution}",
            event_type="Dispute Resolved",
            resolution=resolution,
            amount_to_buyer=amount_to_buyer,
            amount_to_seller=amount_to_seller,
            resolved_by=resolved_by
        )

        self.clear_cache()

    # =================================================================
    # Hold Extension Methods
    # =================================================================

    def extend_hold(self, reason, days=7, extended_by=None):
        """
        Extend the escrow hold period.

        Args:
            reason: Extension reason
            days: Number of days to extend
            extended_by: User who extended
        """
        if cint(self.hold_extension_count) >= cint(self.max_extensions_allowed):
            frappe.throw(
                _("Maximum extensions ({0}) reached").format(self.max_extensions_allowed)
            )

        # Store original date if first extension
        if not self.hold_extended:
            self.db_set("original_release_date", self.scheduled_release_date)

        # Calculate new release date
        current_release = get_datetime(self.scheduled_release_date or now_datetime())
        new_release = add_days(current_release, days)

        self.db_set("hold_extended", 1)
        self.db_set("hold_extension_count", cint(self.hold_extension_count) + 1)
        self.db_set("hold_extension_reason", reason)
        self.db_set("extended_release_date", new_release)
        self.db_set("scheduled_release_date", new_release)

        # Log event
        self.log_escrow_event(
            f"Hold extended by {days} days: {reason}",
            event_type="Hold Extended",
            days=days,
            reason=reason,
            extended_by=extended_by
        )

        self.clear_cache()

    # =================================================================
    # Payout Methods
    # =================================================================

    def schedule_payout(self):
        """Schedule payout to seller."""
        if flt(self.released_amount) <= 0:
            return

        if self.payout_status in ["Completed", "Processing"]:
            return

        self.db_set("payout_status", "Scheduled")

        # Log event
        self.log_escrow_event(
            f"Payout scheduled: {self.currency} {self.payout_amount}",
            event_type="Payout Scheduled",
            amount=self.payout_amount
        )

        self.clear_cache()

    def process_payout(self, method=None, account=None):
        """
        Process payout to seller.

        Args:
            method: Payout method
            account: Payout account
        """
        if self.payout_status not in ["Scheduled", "Failed"]:
            frappe.throw(
                _("Cannot process payout in {0} status").format(self.payout_status)
            )

        if method:
            self.db_set("payout_method", method)

        if account:
            self.db_set("payout_account", account)

        self.db_set("payout_status", "Processing")

        # Log event
        self.log_escrow_event(
            f"Payout processing started",
            event_type="Payout Processing"
        )

        self.clear_cache()

    def complete_payout(self, reference=None):
        """
        Complete payout to seller.

        Args:
            reference: Payout transaction reference
        """
        if self.payout_status != "Processing":
            frappe.throw(
                _("Cannot complete payout in {0} status").format(self.payout_status)
            )

        self.db_set("payout_status", "Completed")
        self.db_set("payout_date", now_datetime())

        if reference:
            self.db_set("payout_reference", reference)

        # Update seller balance
        self.update_seller_balance()

        # Log event
        self.log_escrow_event(
            f"Payout completed: {self.currency} {self.payout_amount}",
            event_type="Payout Completed",
            reference=reference
        )

        self.clear_cache()

    def fail_payout(self, error=None):
        """
        Mark payout as failed.

        Args:
            error: Error message
        """
        self.db_set("payout_status", "Failed")

        if error:
            self.db_set("payout_error", error)

        # Log event
        self.log_escrow_event(
            f"Payout failed: {error or 'Unknown error'}",
            event_type="Payout Failed",
            error=error
        )

        self.clear_cache()

    def update_seller_balance(self):
        """Update seller's balance after payout."""
        if not self.seller:
            return

        try:
            # Check if Seller Balance DocType exists
            if not frappe.db.exists("DocType", "Seller Balance"):
                return

            # Update or create seller balance record
            from tradehub_seller.tradehub_seller.doctype.seller_balance.seller_balance import (
                record_payout
            )
            record_payout(
                self.seller,
                flt(self.payout_amount),
                self.name,
                self.payout_reference
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to update seller balance: {str(e)}",
                "Escrow Payout Error"
            )

    # =================================================================
    # Partial Release Tracking
    # =================================================================

    def add_partial_release(self, amount, release_type, reason=None):
        """
        Add a partial release record.

        Args:
            amount: Amount released/refunded
            release_type: 'release' or 'refund'
            reason: Release/refund reason
        """
        releases = json.loads(self.partial_releases or "[]")
        releases.append({
            "amount": flt(amount),
            "type": release_type,
            "reason": reason,
            "timestamp": str(now_datetime()),
            "user": frappe.session.user
        })

        self.db_set("partial_releases", json.dumps(releases))

    def get_partial_releases(self):
        """Get list of partial releases."""
        return json.loads(self.partial_releases or "[]")

    # =================================================================
    # Event Logging
    # =================================================================

    def log_escrow_event(self, description, event_type=None, **kwargs):
        """
        Log an escrow event.

        Args:
            description: Event description
            event_type: Type of event
            **kwargs: Additional event data
        """
        try:
            if not frappe.db.exists("DocType", "Escrow Event"):
                return

            event = frappe.get_doc({
                "doctype": "Escrow Event",
                "escrow_account": self.name,
                "event_type": event_type or "General",
                "description": description,
                "event_data": json.dumps(kwargs) if kwargs else None,
                "user": frappe.session.user
            })
            event.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Failed to log escrow event: {str(e)}",
                "Escrow Event Log Error"
            )

    # =================================================================
    # Sub Order Integration
    # =================================================================

    def update_sub_order_status(self):
        """Update linked sub order's escrow status."""
        if not self.sub_order:
            return

        try:
            sub_order = frappe.get_doc("Sub Order", self.sub_order)

            if self.status == "Released":
                sub_order.db_set("escrow_status", "Released")
                sub_order.db_set("escrow_released_at", now_datetime())
            elif self.status == "Refunded":
                sub_order.db_set("escrow_status", "Refunded")
            elif self.status == "Disputed":
                sub_order.db_set("escrow_status", "Disputed")

        except Exception as e:
            frappe.log_error(
                f"Failed to update sub order status: {str(e)}",
                "Escrow Sub Order Update Error"
            )

    # =================================================================
    # ERPNext Integration
    # =================================================================

    def create_erpnext_journal_entry(self):
        """Create ERPNext journal entry for escrow."""
        if not frappe.db.exists("DocType", "Journal Entry"):
            return

        try:
            self.db_set("erpnext_sync_status", "Pending")

            company = frappe.defaults.get_user_default("Company")

            # Create journal entry for escrow hold
            je_data = {
                "doctype": "Journal Entry",
                "posting_date": nowdate(),
                "company": company,
                "voucher_type": "Journal Entry",
                "accounts": [
                    {
                        "account": self.get_escrow_account(),
                        "debit_in_account_currency": flt(self.total_amount)
                    },
                    {
                        "account": self.get_receivable_account(),
                        "credit_in_account_currency": flt(self.total_amount)
                    }
                ],
                "user_remark": f"Escrow hold for {self.marketplace_order or self.sub_order}"
            }

            journal_entry = frappe.get_doc(je_data)
            journal_entry.flags.ignore_permissions = True
            journal_entry.insert()

            self.db_set("erpnext_journal_entry", journal_entry.name)
            self.db_set("erpnext_sync_status", "Synced")

        except Exception as e:
            frappe.log_error(
                f"Failed to create journal entry: {str(e)}",
                "Escrow ERPNext Sync Error"
            )
            self.db_set("erpnext_sync_status", "Failed")
            self.db_set("erpnext_sync_error", str(e))

    def get_escrow_account(self):
        """Get escrow holding account from ERPNext."""
        company = frappe.defaults.get_user_default("Company")
        if company:
            # Look for escrow account or use default
            account = frappe.db.get_value(
                "Account",
                {"account_name": "Escrow Account", "company": company},
                "name"
            )
            if account:
                return account

            # Fallback to default liability account
            return frappe.db.get_value(
                "Company", company, "default_payable_account"
            )

        return None

    def get_receivable_account(self):
        """Get receivable account from ERPNext."""
        company = frappe.defaults.get_user_default("Company")
        if company:
            return frappe.db.get_value(
                "Company", company, "default_receivable_account"
            )

        return None

    # =================================================================
    # Utility Methods
    # =================================================================

    def clear_cache(self):
        """Clear cached escrow data."""
        frappe.cache().delete_value(f"escrow_account:{self.name}")
        if self.escrow_id:
            frappe.cache().delete_value(f"escrow_account_by_id:{self.escrow_id}")

    def get_summary(self):
        """Get escrow account summary for display."""
        return {
            "name": self.name,
            "escrow_id": self.escrow_id,
            "status": self.status,
            "total_amount": self.total_amount,
            "held_amount": self.held_amount,
            "released_amount": self.released_amount,
            "refunded_amount": self.refunded_amount,
            "net_amount_to_seller": self.net_amount_to_seller,
            "currency": self.currency,
            "seller": self.seller,
            "buyer": self.buyer,
            "marketplace_order": self.marketplace_order,
            "sub_order": self.sub_order,
            "has_dispute": self.has_dispute,
            "dispute_status": self.dispute_status,
            "payout_status": self.payout_status,
            "scheduled_release_date": str(self.scheduled_release_date) if self.scheduled_release_date else None,
            "created_at": str(self.created_at)
        }

    def is_releasable(self):
        """Check if funds can be released."""
        if self.status not in ["Funds Held", "Partially Released", "Dispute Resolved"]:
            return False

        if self.has_dispute and self.dispute_status not in ["Resolved", "Closed"]:
            return False

        if flt(self.held_amount) <= 0:
            return False

        return True

    def is_refundable(self):
        """Check if funds can be refunded."""
        if self.status not in ["Funds Held", "Partially Released", "Disputed", "Dispute Resolved"]:
            return False

        if flt(self.held_amount) <= 0:
            return False

        return True

    def days_until_release(self):
        """Get number of days until auto release."""
        if not self.scheduled_release_date:
            return None

        release_date = get_datetime(self.scheduled_release_date)
        if release_date <= now_datetime():
            return 0

        return date_diff(release_date, now_datetime())


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def create_escrow_account(
    total_amount,
    seller,
    buyer,
    currency="TRY",
    marketplace_order=None,
    sub_order=None,
    payment_intent=None,
    escrow_type="Order Payment"
):
    """
    Create a new escrow account.

    Args:
        total_amount: Total amount to hold
        seller: Seller Profile name
        buyer: Buyer user
        currency: Currency code
        marketplace_order: Linked marketplace order
        sub_order: Linked sub order
        payment_intent: Linked payment intent
        escrow_type: Type of escrow

    Returns:
        dict: Escrow account details
    """
    escrow = frappe.get_doc({
        "doctype": "Escrow Account",
        "total_amount": flt(total_amount),
        "seller": seller,
        "buyer": buyer,
        "currency": currency,
        "marketplace_order": marketplace_order,
        "sub_order": sub_order,
        "payment_intent": payment_intent,
        "escrow_type": escrow_type
    })

    escrow.insert(ignore_permissions=True)

    return {
        "status": "success",
        "name": escrow.name,
        "escrow_id": escrow.escrow_id,
        "total_amount": escrow.total_amount,
        "currency": escrow.currency
    }


@frappe.whitelist()
def get_escrow_account(escrow_name=None, escrow_id=None):
    """
    Get escrow account details.

    Args:
        escrow_name: Frappe document name
        escrow_id: Public escrow ID

    Returns:
        dict: Escrow account details
    """
    if not escrow_name and not escrow_id:
        frappe.throw(_("Either escrow_name or escrow_id is required"))

    if escrow_id and not escrow_name:
        escrow_name = frappe.db.get_value(
            "Escrow Account", {"escrow_id": escrow_id}, "name"
        )

    if not escrow_name:
        return {"error": _("Escrow account not found")}

    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Permission check
    if frappe.session.user != "Administrator":
        if escrow.buyer != frappe.session.user:
            seller_user = frappe.db.get_value(
                "Seller Profile", escrow.seller, "user"
            )
            if seller_user != frappe.session.user:
                if not frappe.has_permission("Escrow Account", "read"):
                    return {"error": _("Not permitted to view this escrow")}

    return escrow.get_summary()


@frappe.whitelist()
def hold_escrow_funds(escrow_name, amount=None, payment_intent=None):
    """
    Hold funds in escrow.

    Args:
        escrow_name: Escrow account name
        amount: Amount to hold
        payment_intent: Payment intent reference

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)
    escrow.hold_funds(flt(amount) if amount else None, payment_intent)

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "held_amount": escrow.held_amount
    }


@frappe.whitelist()
def release_escrow_funds(escrow_name, amount=None, trigger=None):
    """
    Release funds from escrow.

    Args:
        escrow_name: Escrow account name
        amount: Amount to release
        trigger: Release trigger

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Permission check
    if not frappe.has_permission("Escrow Account", "write"):
        frappe.throw(_("Not permitted to release funds"))

    escrow.release_funds(
        flt(amount) if amount else None,
        trigger or "Manual Release",
        frappe.session.user
    )

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "released_amount": escrow.released_amount,
        "held_amount": escrow.held_amount
    }


@frappe.whitelist()
def refund_escrow_funds(escrow_name, amount=None, reason=None):
    """
    Refund funds from escrow to buyer.

    Args:
        escrow_name: Escrow account name
        amount: Amount to refund
        reason: Refund reason

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Permission check
    if not frappe.has_permission("Escrow Account", "write"):
        frappe.throw(_("Not permitted to refund"))

    escrow.refund_funds(flt(amount) if amount else None, reason)

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "refunded_amount": escrow.refunded_amount,
        "held_amount": escrow.held_amount
    }


@frappe.whitelist()
def confirm_escrow_delivery(escrow_name):
    """
    Confirm delivery for escrow.

    Args:
        escrow_name: Escrow account name

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Only buyer or admin can confirm
    if frappe.session.user not in [escrow.buyer, "Administrator"]:
        if not frappe.has_permission("Escrow Account", "write"):
            frappe.throw(_("Not permitted to confirm delivery"))

    escrow.confirm_delivery(frappe.session.user)

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "delivery_confirmed_at": str(escrow.delivery_confirmed_at),
        "scheduled_release_date": str(escrow.scheduled_release_date)
    }


@frappe.whitelist()
def open_escrow_dispute(escrow_name, reason=None, dispute_case=None):
    """
    Open a dispute on escrow.

    Args:
        escrow_name: Escrow account name
        reason: Dispute reason
        dispute_case: Linked moderation case

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Only buyer, seller, or admin can open dispute
    seller_user = frappe.db.get_value("Seller Profile", escrow.seller, "user")
    if frappe.session.user not in [escrow.buyer, seller_user, "Administrator"]:
        frappe.throw(_("Not permitted to open dispute"))

    escrow.open_dispute(reason, frappe.session.user, dispute_case)

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "dispute_status": escrow.dispute_status
    }


@frappe.whitelist()
def resolve_escrow_dispute(
    escrow_name,
    resolution,
    amount_to_buyer=0,
    amount_to_seller=0
):
    """
    Resolve a dispute on escrow.

    Args:
        escrow_name: Escrow account name
        resolution: Resolution decision
        amount_to_buyer: Amount to refund to buyer
        amount_to_seller: Amount to release to seller

    Returns:
        dict: Updated status
    """
    escrow = frappe.get_doc("Escrow Account", escrow_name)

    # Only admin can resolve disputes
    if not frappe.has_permission("Escrow Account", "write"):
        frappe.throw(_("Not permitted to resolve disputes"))

    escrow.resolve_dispute(
        resolution,
        flt(amount_to_buyer),
        flt(amount_to_seller),
        frappe.session.user
    )

    return {
        "status": "success",
        "escrow_status": escrow.status,
        "dispute_status": escrow.dispute_status,
        "dispute_resolution": escrow.dispute_resolution
    }


@frappe.whitelist()
def get_escrow_statistics(seller=None, days=30):
    """
    Get escrow statistics.

    Args:
        seller: Filter by seller
        days: Number of days to analyze

    Returns:
        dict: Escrow statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"created_at": [">=", from_date]}
    if seller:
        filters["seller"] = seller

    # Status breakdown
    status_data = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as count,
            SUM(total_amount) as total_amount,
            SUM(held_amount) as held_amount,
            SUM(released_amount) as released_amount,
            SUM(refunded_amount) as refunded_amount
        FROM `tabEscrow Account`
        WHERE created_at >= %(from_date)s
        {seller_filter}
        GROUP BY status
    """.format(
        seller_filter=f"AND seller = %(seller)s" if seller else ""
    ), {"from_date": from_date, "seller": seller}, as_dict=True)

    # Calculate totals
    total_count = sum(s.count for s in status_data)
    total_amount = sum(flt(s.total_amount) for s in status_data)
    total_held = sum(flt(s.held_amount) for s in status_data)
    total_released = sum(flt(s.released_amount) for s in status_data)
    total_refunded = sum(flt(s.refunded_amount) for s in status_data)

    # Dispute statistics
    disputed = next((s for s in status_data if s.status == "Disputed"), None)
    dispute_resolved = next(
        (s for s in status_data if s.status == "Dispute Resolved"), None
    )

    return {
        "period_days": cint(days),
        "total_escrows": total_count,
        "total_amount": total_amount,
        "currently_held": total_held,
        "total_released": total_released,
        "total_refunded": total_refunded,
        "release_rate": (total_released / total_amount * 100) if total_amount > 0 else 0,
        "refund_rate": (total_refunded / total_amount * 100) if total_amount > 0 else 0,
        "active_disputes": disputed.count if disputed else 0,
        "resolved_disputes": dispute_resolved.count if dispute_resolved else 0,
        "status_breakdown": {
            s.status: {
                "count": s.count,
                "total_amount": s.total_amount,
                "held_amount": s.held_amount
            } for s in status_data
        }
    }


@frappe.whitelist()
def process_auto_releases():
    """
    Process all escrows eligible for auto-release.
    Called by scheduled job.

    Returns:
        dict: Processing results
    """
    # Find escrows ready for auto-release
    escrows = frappe.db.sql("""
        SELECT name
        FROM `tabEscrow Account`
        WHERE status IN ('Funds Held', 'Partially Released')
        AND auto_release_enabled = 1
        AND scheduled_release_date <= NOW()
        AND (has_dispute = 0 OR dispute_status IN ('Resolved', 'Closed'))
    """, as_dict=True)

    released = 0
    failed = 0

    for esc in escrows:
        try:
            escrow = frappe.get_doc("Escrow Account", esc.name)
            if escrow.auto_release():
                released += 1
        except Exception as e:
            failed += 1
            frappe.log_error(
                f"Auto-release failed for {esc.name}: {str(e)}",
                "Escrow Auto-Release Error"
            )

    return {
        "status": "success",
        "processed": len(escrows),
        "released": released,
        "failed": failed
    }
