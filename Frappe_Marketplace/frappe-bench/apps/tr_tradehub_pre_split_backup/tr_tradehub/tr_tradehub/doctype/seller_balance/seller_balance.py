# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime, get_datetime,
    add_days, date_diff
)
import json


class SellerBalance(Document):
    """
    Seller Balance DocType for TR-TradeHub.

    Manages seller financial balances including:
    - Available balance (funds ready for payout)
    - Pending balance (awaiting escrow release)
    - Held balance (under dispute/review)
    - Reserved balance (for pending payouts)
    - Lifetime statistics and transaction history
    - Payout settings and scheduling
    - Tax withholding tracking
    """

    def before_insert(self):
        """Set default values before creating a new balance record."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        # Initialize JSON fields
        if not self.recent_transactions:
            self.recent_transactions = "[]"

        # Set initial last_updated
        self.last_updated = now_datetime()

        # Calculate next payout date
        self.calculate_next_payout_date()

    def validate(self):
        """Validate seller balance data before saving."""
        self.validate_seller()
        self.validate_balances()
        self.validate_iban()
        self.validate_payout_settings()
        self.update_totals()
        self.modified_by_user = frappe.session.user
        self.modified_at = now_datetime()
        self.last_updated = now_datetime()

    def on_update(self):
        """Actions after balance is updated."""
        self.clear_cache()
        self.update_seller_profile()

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_seller(self):
        """Validate seller exists."""
        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

    def validate_balances(self):
        """Validate balance values are not negative."""
        for field in ['available_balance', 'pending_balance', 'held_balance',
                      'reserved_balance', 'total_balance']:
            if flt(getattr(self, field, 0)) < 0:
                frappe.throw(_("{0} cannot be negative").format(field.replace("_", " ").title()))

    def validate_iban(self):
        """Validate Turkish IBAN format."""
        if not self.iban:
            return

        iban = self.iban.replace(" ", "").upper()

        # Turkish IBAN: TR + 2 check digits + 5 bank code + 1 reserve + 16 account
        if not iban.startswith("TR"):
            frappe.throw(_("Turkish IBAN must start with TR"))

        if len(iban) != 26:
            frappe.throw(_("Turkish IBAN must be 26 characters"))

        # Validate IBAN checksum using MOD-97
        if not self._validate_iban_checksum(iban):
            frappe.throw(_("Invalid IBAN checksum"))

        # Store formatted IBAN
        self.iban = iban

    def _validate_iban_checksum(self, iban):
        """Validate IBAN using MOD-97 algorithm."""
        try:
            # Move first 4 chars to end
            rearranged = iban[4:] + iban[:4]

            # Convert letters to numbers (A=10, B=11, etc.)
            numeric = ""
            for char in rearranged:
                if char.isalpha():
                    numeric += str(ord(char) - 55)
                else:
                    numeric += char

            # Check if mod 97 == 1
            return int(numeric) % 97 == 1
        except:
            return False

    def validate_payout_settings(self):
        """Validate payout configuration."""
        if self.payout_frequency == "Weekly" and self.payout_day:
            if cint(self.payout_day) < 1 or cint(self.payout_day) > 7:
                frappe.throw(_("For weekly payouts, payout day must be 1-7"))

        if self.payout_frequency == "Monthly" and self.payout_day:
            if cint(self.payout_day) < 1 or cint(self.payout_day) > 28:
                frappe.throw(_("For monthly payouts, payout day must be 1-28"))

        if flt(self.minimum_payout_threshold) < 0:
            frappe.throw(_("Minimum payout threshold cannot be negative"))

    def update_totals(self):
        """Update calculated totals."""
        # Calculate total balance
        self.total_balance = (
            flt(self.available_balance) +
            flt(self.pending_balance) +
            flt(self.held_balance) +
            flt(self.reserved_balance)
        )

        # Calculate net lifetime earnings
        self.net_lifetime_earnings = (
            flt(self.lifetime_earnings) -
            flt(self.lifetime_commissions) -
            flt(self.lifetime_refunds) +
            flt(self.lifetime_adjustments)
        )

        # Update days to next payout
        if self.next_payout_date:
            self.days_to_next_payout = max(
                0,
                date_diff(self.next_payout_date, nowdate())
            )

        # Calculate estimated next payout
        if flt(self.available_balance) >= flt(self.minimum_payout_threshold):
            self.estimated_next_payout = flt(self.available_balance)
        else:
            self.estimated_next_payout = 0

    # =================================================================
    # Balance Update Methods
    # =================================================================

    def add_earnings(self, amount, order_name=None, description=None):
        """
        Add earnings to pending balance.

        Args:
            amount: Amount to add
            order_name: Related order name
            description: Transaction description
        """
        amount = flt(amount)
        if amount <= 0:
            frappe.throw(_("Earnings amount must be positive"))

        self.db_set("pending_balance", flt(self.pending_balance) + amount)
        self.db_set("lifetime_earnings", flt(self.lifetime_earnings) + amount)

        self._log_transaction("Earnings", amount, order_name, description)
        self._update_last_updated()

    def release_to_available(self, amount, escrow_name=None, description=None):
        """
        Release funds from pending to available balance.

        Args:
            amount: Amount to release
            escrow_name: Related escrow account
            description: Transaction description
        """
        amount = flt(amount)
        if amount <= 0:
            frappe.throw(_("Release amount must be positive"))

        if amount > flt(self.pending_balance):
            frappe.throw(_("Cannot release more than pending balance"))

        self.db_set("pending_balance", flt(self.pending_balance) - amount)
        self.db_set("available_balance", flt(self.available_balance) + amount)

        self._log_transaction("Release", amount, escrow_name, description)
        self._update_last_updated()

    def deduct_commission(self, amount, order_name=None, description=None):
        """
        Deduct commission from balance.

        Args:
            amount: Commission amount to deduct
            order_name: Related order
            description: Transaction description
        """
        amount = flt(amount)
        if amount <= 0:
            return

        self.db_set("lifetime_commissions", flt(self.lifetime_commissions) + amount)

        # Update statistics
        total_orders = cint(self.total_orders_completed) + 1
        total_commission = flt(self.total_commission_paid) + amount
        self.db_set("total_commission_paid", total_commission)

        if flt(self.lifetime_earnings) > 0:
            avg_rate = (total_commission / flt(self.lifetime_earnings)) * 100
            self.db_set("average_commission_rate", round(avg_rate, 2))

        self._log_transaction("Commission", -amount, order_name, description)
        self._update_last_updated()

    def process_refund(self, amount, order_name=None, description=None):
        """
        Process a refund deduction.

        Args:
            amount: Refund amount
            order_name: Related order
            description: Refund description
        """
        amount = flt(amount)
        if amount <= 0:
            return

        # Deduct from available balance first, then pending
        remaining = amount
        if flt(self.available_balance) >= remaining:
            self.db_set("available_balance", flt(self.available_balance) - remaining)
        else:
            remaining -= flt(self.available_balance)
            self.db_set("available_balance", 0)
            self.db_set("pending_balance", flt(self.pending_balance) - remaining)

        self.db_set("lifetime_refunds", flt(self.lifetime_refunds) + amount)
        self.db_set("total_orders_refunded", cint(self.total_orders_refunded) + 1)

        self._log_transaction("Refund", -amount, order_name, description)
        self._update_last_updated()

    def hold_funds(self, amount, reason=None):
        """
        Hold funds due to dispute or review.

        Args:
            amount: Amount to hold
            reason: Reason for hold
        """
        amount = flt(amount)
        if amount <= 0:
            return

        # Move from available to held
        if flt(self.available_balance) >= amount:
            self.db_set("available_balance", flt(self.available_balance) - amount)
            self.db_set("held_balance", flt(self.held_balance) + amount)

            self._log_transaction("Hold", amount, None, reason)
            self._update_last_updated()
        else:
            frappe.throw(_("Insufficient available balance to hold"))

    def release_held_funds(self, amount, release_to="available", description=None):
        """
        Release held funds.

        Args:
            amount: Amount to release
            release_to: 'available' or 'refund'
            description: Release description
        """
        amount = flt(amount)
        if amount <= 0:
            return

        if amount > flt(self.held_balance):
            frappe.throw(_("Cannot release more than held balance"))

        self.db_set("held_balance", flt(self.held_balance) - amount)

        if release_to == "available":
            self.db_set("available_balance", flt(self.available_balance) + amount)
            self._log_transaction("Release Hold", amount, None, description)
        else:
            self.db_set("lifetime_refunds", flt(self.lifetime_refunds) + amount)
            self._log_transaction("Hold Refunded", -amount, None, description)

        self._update_last_updated()

    def apply_adjustment(self, amount, reason, adjustment_type="Credit"):
        """
        Apply a manual adjustment.

        Args:
            amount: Adjustment amount (positive for credit, negative for debit)
            reason: Reason for adjustment
            adjustment_type: 'Credit' or 'Debit'
        """
        amount = flt(amount)

        if adjustment_type == "Debit":
            amount = -abs(amount)
        else:
            amount = abs(amount)

        self.db_set("available_balance", flt(self.available_balance) + amount)
        self.db_set("lifetime_adjustments", flt(self.lifetime_adjustments) + amount)

        self._log_transaction(
            f"Adjustment ({adjustment_type})",
            amount,
            None,
            reason
        )
        self._update_last_updated()

    # =================================================================
    # Payout Methods
    # =================================================================

    def can_payout(self):
        """
        Check if payout can be processed.

        Returns:
            tuple: (can_payout: bool, reason: str)
        """
        if self.status != "Active":
            return False, _("Balance account is not active")

        if cint(self.payout_suspended):
            return False, _("Payouts are suspended: {0}").format(self.suspension_reason)

        if cint(self.has_payment_issue):
            return False, _("Payment issue exists: {0}").format(self.payment_issue_reason)

        if flt(self.available_balance) < flt(self.minimum_payout_threshold):
            return False, _("Available balance ({0}) is below minimum threshold ({1})").format(
                self.available_balance, self.minimum_payout_threshold
            )

        if not self.iban and self.payout_method == "Bank Transfer":
            return False, _("IBAN is required for bank transfer payouts")

        return True, _("Ready for payout")

    def request_payout(self, amount=None):
        """
        Request a payout.

        Args:
            amount: Amount to payout (defaults to available balance)

        Returns:
            dict: Payout request details
        """
        can_pay, reason = self.can_payout()
        if not can_pay:
            frappe.throw(reason)

        payout_amount = flt(amount) if amount else flt(self.available_balance)

        if payout_amount > flt(self.available_balance):
            frappe.throw(_("Payout amount exceeds available balance"))

        if payout_amount < flt(self.minimum_payout_threshold):
            frappe.throw(_("Payout amount is below minimum threshold"))

        # Reserve the payout amount
        self.db_set("available_balance", flt(self.available_balance) - payout_amount)
        self.db_set("reserved_balance", flt(self.reserved_balance) + payout_amount)

        self._log_transaction("Payout Requested", -payout_amount, None,
                             f"Payout requested for {self.currency} {payout_amount}")
        self._update_last_updated()

        return {
            "seller": self.seller,
            "amount": payout_amount,
            "currency": self.currency,
            "method": self.payout_method,
            "iban": self.iban,
            "account_name": self.payout_account_name,
            "status": "pending"
        }

    def complete_payout(self, amount, reference, transaction_date=None):
        """
        Record a completed payout.

        Args:
            amount: Payout amount
            reference: Transaction reference
            transaction_date: Date of transaction
        """
        amount = flt(amount)

        # Move from reserved to paid
        if flt(self.reserved_balance) >= amount:
            self.db_set("reserved_balance", flt(self.reserved_balance) - amount)
        else:
            # If not reserved, deduct from available
            self.db_set("available_balance", flt(self.available_balance) - amount)

        # Update payout statistics
        self.db_set("lifetime_payouts", flt(self.lifetime_payouts) + amount)
        self.db_set("last_payout_date", transaction_date or now_datetime())
        self.db_set("last_payout_amount", amount)
        self.db_set("last_payout_reference", reference)
        self.db_set("total_payout_count", cint(self.total_payout_count) + 1)

        self._log_transaction("Payout Completed", -amount, reference,
                             f"Payout completed: {reference}")

        # Calculate next payout date
        self.calculate_next_payout_date()
        self._update_last_updated()

    def fail_payout(self, amount, reason):
        """
        Record a failed payout and return funds to available.

        Args:
            amount: Payout amount that failed
            reason: Failure reason
        """
        amount = flt(amount)

        # Return reserved to available
        self.db_set("reserved_balance", max(0, flt(self.reserved_balance) - amount))
        self.db_set("available_balance", flt(self.available_balance) + amount)

        # Set payment issue flag
        self.db_set("has_payment_issue", 1)
        self.db_set("payment_issue_reason", reason)

        self._log_transaction("Payout Failed", amount, None, reason)
        self._update_last_updated()

    def calculate_next_payout_date(self):
        """Calculate the next scheduled payout date."""
        if not cint(self.auto_payout_enabled):
            self.next_payout_date = None
            return

        today = getdate(nowdate())

        if self.payout_frequency == "Daily":
            next_date = add_days(today, 1)

        elif self.payout_frequency == "Weekly":
            # Calculate days until payout day (1=Monday, 7=Sunday)
            payout_day = cint(self.payout_day) or 1
            current_day = today.isoweekday()
            days_ahead = payout_day - current_day
            if days_ahead <= 0:
                days_ahead += 7
            next_date = add_days(today, days_ahead)

        elif self.payout_frequency == "Bi-Weekly":
            payout_day = cint(self.payout_day) or 1
            current_day = today.isoweekday()
            days_ahead = payout_day - current_day
            if days_ahead <= 0:
                days_ahead += 14
            next_date = add_days(today, days_ahead)

        elif self.payout_frequency == "Monthly":
            payout_day = cint(self.payout_day) or 1
            next_month = today.month + 1 if today.day >= payout_day else today.month
            next_year = today.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            next_date = today.replace(year=next_year, month=next_month, day=payout_day)

        else:  # On Demand
            next_date = None

        self.db_set("next_payout_date", next_date)

    # =================================================================
    # Suspension Methods
    # =================================================================

    def suspend_payouts(self, reason):
        """
        Suspend payout processing.

        Args:
            reason: Suspension reason
        """
        self.db_set("payout_suspended", 1)
        self.db_set("suspension_reason", reason)
        self.db_set("suspension_date", now_datetime())

        self._log_transaction("Payouts Suspended", 0, None, reason)
        self._update_last_updated()

    def resume_payouts(self):
        """Resume payout processing."""
        self.db_set("payout_suspended", 0)
        self.db_set("suspension_reason", None)
        self.db_set("suspension_date", None)

        # Clear payment issues if any
        self.db_set("has_payment_issue", 0)
        self.db_set("payment_issue_reason", None)

        self._log_transaction("Payouts Resumed", 0, None, "Payout processing resumed")
        self._update_last_updated()

    # =================================================================
    # Statistics Methods
    # =================================================================

    def record_order_completion(self, order_value, commission_amount):
        """
        Record order completion statistics.

        Args:
            order_value: Total order value
            commission_amount: Commission deducted
        """
        # Update counts
        total_orders = cint(self.total_orders_completed) + 1
        self.db_set("total_orders_completed", total_orders)

        # Update average order value
        total_value = (flt(self.average_order_value) * (total_orders - 1)) + flt(order_value)
        self.db_set("average_order_value", total_value / total_orders)

        self._update_last_updated()

    def get_balance_summary(self):
        """Get balance summary for display."""
        can_pay, pay_reason = self.can_payout()

        return {
            "seller": self.seller,
            "seller_name": self.seller_name,
            "status": self.status,
            "currency": self.currency,
            "available_balance": flt(self.available_balance),
            "pending_balance": flt(self.pending_balance),
            "held_balance": flt(self.held_balance),
            "reserved_balance": flt(self.reserved_balance),
            "total_balance": flt(self.total_balance),
            "lifetime_earnings": flt(self.lifetime_earnings),
            "lifetime_payouts": flt(self.lifetime_payouts),
            "net_lifetime_earnings": flt(self.net_lifetime_earnings),
            "can_payout": can_pay,
            "payout_reason": pay_reason,
            "minimum_payout_threshold": flt(self.minimum_payout_threshold),
            "next_payout_date": str(self.next_payout_date) if self.next_payout_date else None,
            "payout_suspended": cint(self.payout_suspended),
            "has_payment_issue": cint(self.has_payment_issue),
            "last_updated": str(self.last_updated)
        }

    def get_transaction_history(self, limit=20):
        """
        Get recent transaction history.

        Args:
            limit: Number of transactions to return

        Returns:
            list: Recent transactions
        """
        transactions = json.loads(self.recent_transactions or "[]")
        return transactions[:limit]

    # =================================================================
    # Helper Methods
    # =================================================================

    def _log_transaction(self, transaction_type, amount, reference=None, description=None):
        """Log a balance transaction."""
        transactions = json.loads(self.recent_transactions or "[]")

        transaction = {
            "type": transaction_type,
            "amount": flt(amount),
            "balance_after": flt(self.available_balance) + flt(amount) if transaction_type != "Release" else None,
            "reference": reference,
            "description": description,
            "timestamp": str(now_datetime()),
            "user": frappe.session.user
        }

        # Add to beginning (most recent first)
        transactions.insert(0, transaction)

        # Keep only last 100 transactions
        transactions = transactions[:100]

        self.db_set("recent_transactions", json.dumps(transactions))

    def _update_last_updated(self):
        """Update the last_updated timestamp."""
        self.db_set("last_updated", now_datetime(), update_modified=False)
        self.clear_cache()

    def clear_cache(self):
        """Clear cached balance data."""
        frappe.cache().delete_value(f"seller_balance:{self.name}")
        frappe.cache().delete_value(f"seller_balance_seller:{self.seller}")

    def update_seller_profile(self):
        """Update linked seller profile with balance info."""
        try:
            if frappe.db.exists("Seller Profile", self.seller):
                # Update seller profile with balance link if needed
                pass
        except Exception:
            pass


# =================================================================
# Module-Level Functions
# =================================================================

def get_or_create_seller_balance(seller):
    """
    Get or create a seller balance record.

    Args:
        seller: Seller Profile name

    Returns:
        Seller Balance document
    """
    if frappe.db.exists("Seller Balance", seller):
        return frappe.get_doc("Seller Balance", seller)

    # Create new balance record
    seller_doc = frappe.get_doc("Seller Profile", seller)

    balance = frappe.get_doc({
        "doctype": "Seller Balance",
        "seller": seller,
        "tenant": seller_doc.tenant,
        "currency": seller_doc.currency or "TRY",
        "iban": seller_doc.iban,
        "payout_account_name": seller_doc.account_holder_name,
        "bank_name": seller_doc.bank_name
    })
    balance.insert(ignore_permissions=True)

    return balance


def record_payout(seller, amount, escrow_name=None, reference=None):
    """
    Record a payout to seller balance.
    Called from Escrow Account on payout completion.

    Args:
        seller: Seller Profile name
        amount: Payout amount
        escrow_name: Related escrow account
        reference: Transaction reference
    """
    balance = get_or_create_seller_balance(seller)
    balance.complete_payout(amount, reference or escrow_name)


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_seller_balance(seller):
    """
    Get seller balance summary.

    Args:
        seller: Seller Profile name

    Returns:
        dict: Balance summary
    """
    # Permission check
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if seller_user != frappe.session.user:
            if not frappe.has_permission("Seller Balance", "read"):
                frappe.throw(_("Not permitted to view this balance"))

    balance = get_or_create_seller_balance(seller)
    return balance.get_balance_summary()


@frappe.whitelist()
def get_balance_transactions(seller, limit=20):
    """
    Get seller balance transaction history.

    Args:
        seller: Seller Profile name
        limit: Number of transactions

    Returns:
        list: Transaction history
    """
    # Permission check
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if seller_user != frappe.session.user:
            if not frappe.has_permission("Seller Balance", "read"):
                frappe.throw(_("Not permitted to view this balance"))

    balance = get_or_create_seller_balance(seller)
    return balance.get_transaction_history(cint(limit))


@frappe.whitelist()
def request_payout(seller, amount=None):
    """
    Request a payout for seller.

    Args:
        seller: Seller Profile name
        amount: Optional specific amount

    Returns:
        dict: Payout request details
    """
    # Permission check - only seller or admin can request payout
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if seller_user != frappe.session.user:
            frappe.throw(_("Not permitted to request payout"))

    balance = get_or_create_seller_balance(seller)
    return balance.request_payout(flt(amount) if amount else None)


@frappe.whitelist()
def update_payout_settings(seller, payout_method=None, iban=None,
                           account_name=None, bank_name=None,
                           payout_frequency=None, auto_payout=None):
    """
    Update seller payout settings.

    Args:
        seller: Seller Profile name
        payout_method: Payment method
        iban: IBAN number
        account_name: Account holder name
        bank_name: Bank name
        payout_frequency: Payout frequency
        auto_payout: Auto payout enabled

    Returns:
        dict: Updated settings
    """
    # Permission check
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if seller_user != frappe.session.user:
            frappe.throw(_("Not permitted to update settings"))

    balance = get_or_create_seller_balance(seller)

    if payout_method:
        balance.payout_method = payout_method
    if iban:
        balance.iban = iban
    if account_name:
        balance.payout_account_name = account_name
    if bank_name:
        balance.bank_name = bank_name
    if payout_frequency:
        balance.payout_frequency = payout_frequency
    if auto_payout is not None:
        balance.auto_payout_enabled = cint(auto_payout)

    balance.save(ignore_permissions=True)

    return {
        "status": "success",
        "message": _("Payout settings updated"),
        "payout_method": balance.payout_method,
        "iban": balance.iban,
        "payout_frequency": balance.payout_frequency,
        "auto_payout_enabled": balance.auto_payout_enabled
    }


@frappe.whitelist()
def suspend_seller_payouts(seller, reason):
    """
    Suspend payouts for a seller (admin only).

    Args:
        seller: Seller Profile name
        reason: Suspension reason

    Returns:
        dict: Status
    """
    if not frappe.has_permission("Seller Balance", "write"):
        frappe.throw(_("Not permitted to suspend payouts"))

    balance = get_or_create_seller_balance(seller)
    balance.suspend_payouts(reason)

    return {
        "status": "success",
        "message": _("Payouts suspended for {0}").format(seller)
    }


@frappe.whitelist()
def resume_seller_payouts(seller):
    """
    Resume payouts for a seller (admin only).

    Args:
        seller: Seller Profile name

    Returns:
        dict: Status
    """
    if not frappe.has_permission("Seller Balance", "write"):
        frappe.throw(_("Not permitted to resume payouts"))

    balance = get_or_create_seller_balance(seller)
    balance.resume_payouts()

    return {
        "status": "success",
        "message": _("Payouts resumed for {0}").format(seller)
    }


@frappe.whitelist()
def apply_balance_adjustment(seller, amount, reason, adjustment_type="Credit"):
    """
    Apply a manual balance adjustment (admin only).

    Args:
        seller: Seller Profile name
        amount: Adjustment amount
        reason: Adjustment reason
        adjustment_type: 'Credit' or 'Debit'

    Returns:
        dict: Status
    """
    if not frappe.has_permission("Seller Balance", "write"):
        frappe.throw(_("Not permitted to apply adjustments"))

    balance = get_or_create_seller_balance(seller)
    balance.apply_adjustment(flt(amount), reason, adjustment_type)

    return {
        "status": "success",
        "message": _("{0} of {1} {2} applied to {3}").format(
            adjustment_type, balance.currency, amount, seller
        ),
        "new_balance": balance.available_balance
    }


@frappe.whitelist()
def get_balance_statistics(tenant=None):
    """
    Get aggregate balance statistics (admin only).

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Balance statistics
    """
    if not frappe.has_permission("Seller Balance", "read"):
        frappe.throw(_("Not permitted"))

    filters = {}
    if tenant:
        filters["tenant"] = tenant

    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_sellers,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_sellers,
            SUM(available_balance) as total_available,
            SUM(pending_balance) as total_pending,
            SUM(held_balance) as total_held,
            SUM(total_balance) as total_balance,
            SUM(lifetime_earnings) as total_lifetime_earnings,
            SUM(lifetime_payouts) as total_lifetime_payouts,
            SUM(lifetime_commissions) as total_lifetime_commissions,
            AVG(available_balance) as avg_available_balance,
            SUM(CASE WHEN payout_suspended = 1 THEN 1 ELSE 0 END) as suspended_count,
            SUM(CASE WHEN has_payment_issue = 1 THEN 1 ELSE 0 END) as payment_issue_count
        FROM `tabSeller Balance`
        {tenant_filter}
    """.format(
        tenant_filter=f"WHERE tenant = %(tenant)s" if tenant else ""
    ), {"tenant": tenant}, as_dict=True)

    return stats[0] if stats else {}


@frappe.whitelist()
def process_scheduled_payouts():
    """
    Process all scheduled payouts.
    Called by scheduled job.

    Returns:
        dict: Processing results
    """
    today = nowdate()

    # Find balances ready for payout
    balances = frappe.db.sql("""
        SELECT name, seller
        FROM `tabSeller Balance`
        WHERE status = 'Active'
        AND auto_payout_enabled = 1
        AND payout_suspended = 0
        AND has_payment_issue = 0
        AND next_payout_date <= %(today)s
        AND available_balance >= minimum_payout_threshold
    """, {"today": today}, as_dict=True)

    processed = 0
    failed = 0

    for b in balances:
        try:
            balance = frappe.get_doc("Seller Balance", b.name)
            payout_request = balance.request_payout()

            # Here you would integrate with actual payment processor
            # For now, just log the request
            frappe.log_error(
                f"Payout requested for {b.seller}: {payout_request}",
                "Scheduled Payout"
            )

            processed += 1

        except Exception as e:
            failed += 1
            frappe.log_error(
                f"Failed to process payout for {b.seller}: {str(e)}",
                "Scheduled Payout Error"
            )

    return {
        "status": "success",
        "processed": processed,
        "failed": failed
    }
