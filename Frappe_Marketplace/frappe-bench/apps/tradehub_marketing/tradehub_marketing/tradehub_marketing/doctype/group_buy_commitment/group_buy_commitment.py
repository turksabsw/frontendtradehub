# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy Commitment DocType Controller

Handles buyer commitments to group buy campaigns with dynamic pricing updates.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class GroupBuyCommitment(Document):
    """Group Buy Commitment document controller."""

    def validate(self):
        """Validate commitment before save."""
        self._validate_group_buy()
        self._validate_quantity()
        self._calculate_pricing()

    def before_insert(self):
        """Set defaults before first save."""
        if not self.commitment_date:
            self.commitment_date = now_datetime()
        self._calculate_share_percent()

    def after_insert(self):
        """Update group buy statistics after commitment."""
        self._update_group_buy_stats()
        self._send_confirmation_notification()

    def on_update(self):
        """Handle updates to commitment."""
        if self.has_value_changed("quantity"):
            self.modified_count = (self.modified_count or 0) + 1
            self._update_group_buy_stats()

        if self.has_value_changed("status"):
            self._handle_status_change()

    def on_trash(self):
        """Handle commitment deletion."""
        if self.status not in ["Cancelled", "Refunded", "Expired"]:
            frappe.throw(_("Only cancelled, refunded, or expired commitments can be deleted"))

    def _validate_group_buy(self):
        """Validate the linked group buy."""
        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        # Check if group buy is active
        if group_buy.status != "Active" and not self.is_new():
            if self.has_value_changed("quantity") or self.has_value_changed("status"):
                # Allow status changes but not quantity changes on non-active group buys
                if self.has_value_changed("quantity"):
                    frappe.throw(_("Cannot modify commitment quantity - group buy is not active"))

        # Check deadline for new commitments
        if self.is_new():
            if group_buy.status != "Active":
                frappe.throw(_("Cannot create commitment - group buy is not active"))

            if now_datetime() > group_buy.end_date:
                frappe.throw(_("Cannot create commitment - group buy has ended"))

    def _validate_quantity(self):
        """Validate commitment quantity against group buy limits."""
        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        if self.quantity <= 0:
            frappe.throw(_("Quantity must be positive"))

        if self.quantity < group_buy.min_quantity:
            frappe.throw(
                _("Quantity must be at least {0}").format(group_buy.min_quantity)
            )

        if group_buy.max_quantity_per_buyer and self.quantity > group_buy.max_quantity_per_buyer:
            frappe.throw(
                _("Quantity cannot exceed {0}").format(group_buy.max_quantity_per_buyer)
            )

        # Check total commitment for this buyer
        if not self.is_new():
            return

        existing = frappe.db.get_value(
            "Group Buy Commitment",
            {
                "group_buy": self.group_buy,
                "buyer": self.buyer,
                "status": ["in", ["Active", "Payment Pending", "Paid"]]
            },
            "sum(quantity)"
        ) or 0

        total = existing + self.quantity
        if group_buy.max_quantity_per_buyer and total > group_buy.max_quantity_per_buyer:
            frappe.throw(
                _("Total commitment would exceed max quantity per buyer ({0}). "
                  "You already have {1} committed.").format(
                    group_buy.max_quantity_per_buyer, existing
                )
            )

    def _calculate_pricing(self):
        """Calculate commitment pricing using contribution model."""
        from tradehub_marketing.tradehub_marketing.groupbuy.pricing import calculate_buyer_price

        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        # Calculate unit price
        self.unit_price = calculate_buyer_price(
            q_i=self.quantity,
            T=group_buy.target_quantity,
            P_T=group_buy.max_price,
            P_best=group_buy.best_price,
            s_ref=group_buy.reference_share or 0.20,
            alpha=group_buy.alpha_factor or 1.0
        )

        # Calculate totals
        self.total_amount = self.quantity * self.unit_price

        # Calculate contribution factor
        if group_buy.target_quantity > 0:
            s_i = self.quantity / group_buy.target_quantity
            s_ref = group_buy.reference_share or 0.20
            self.contribution_factor = min(1.0, s_i / s_ref)
        else:
            self.contribution_factor = 0

        # Calculate discount percentage
        if group_buy.max_price > 0:
            self.discount_percent = ((group_buy.max_price - self.unit_price) / group_buy.max_price) * 100
        else:
            self.discount_percent = 0

    def _calculate_share_percent(self):
        """Calculate buyer's share percentage of target."""
        group_buy = frappe.get_doc("Group Buy", self.group_buy)
        if group_buy.target_quantity > 0:
            self.share_percent = (self.quantity / group_buy.target_quantity) * 100
        else:
            self.share_percent = 0

    def _update_group_buy_stats(self):
        """Update group buy statistics after commitment changes."""
        from tradehub_marketing.tradehub_marketing.groupbuy.pricing import calculate_all_prices
        calculate_all_prices(self.group_buy)

    def _send_confirmation_notification(self):
        """Send commitment confirmation to buyer."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if not buyer_user:
            return

        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": buyer_user,
            "type": "Alert",
            "document_type": "Group Buy Commitment",
            "document_name": self.name,
            "subject": _("Commitment Confirmed"),
            "email_content": _(
                "Your commitment to '{0}' has been confirmed.\n"
                "Quantity: {1}\n"
                "Unit Price: {2}\n"
                "Total: {3}"
            ).format(group_buy.title, self.quantity, self.unit_price, self.total_amount)
        }).insert(ignore_permissions=True)

    def _handle_status_change(self):
        """Handle commitment status transitions."""
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_status = old_doc.status
        new_status = self.status

        frappe.logger().info(
            f"Commitment {self.name} status changed: {old_status} -> {new_status}"
        )

        if new_status == "Cancelled":
            self.cancelled_at = now_datetime()
            self._update_group_buy_stats()
            self._notify_cancellation()

        elif new_status == "Refunded":
            self.refunded_at = now_datetime()
            self._notify_refund()

        elif new_status == "Payment Pending" and old_status == "Active":
            self.price_locked = 1
            self.locked_at = now_datetime()

        elif new_status == "Paid":
            self._notify_payment_confirmed()

    def _notify_cancellation(self):
        """Notify buyer about commitment cancellation."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Commitment",
                "document_name": self.name,
                "subject": _("Commitment Cancelled"),
                "email_content": _("Your commitment has been cancelled.")
            }).insert(ignore_permissions=True)

    def _notify_refund(self):
        """Notify buyer about refund."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Commitment",
                "document_name": self.name,
                "subject": _("Commitment Refunded"),
                "email_content": _(
                    "Your commitment has been refunded. "
                    "Amount: {0}"
                ).format(self.refund_amount or self.total_amount)
            }).insert(ignore_permissions=True)

    def _notify_payment_confirmed(self):
        """Notify buyer about successful payment."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Commitment",
                "document_name": self.name,
                "subject": _("Payment Confirmed"),
                "email_content": _("Your payment has been confirmed. Thank you!")
            }).insert(ignore_permissions=True)

    def can_cancel(self) -> tuple:
        """
        Check if this commitment can be cancelled.

        Returns:
            tuple: (can_cancel: bool, message: str)
        """
        if self.status not in ["Active", "Payment Pending"]:
            return False, _("Only active or payment pending commitments can be cancelled")

        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        if not group_buy.allow_cancel_commitment:
            return False, _("Cancellation is not allowed for this group buy")

        # Check cutoff time
        if group_buy.cancel_cutoff_hours:
            from frappe.utils import add_to_date
            cutoff_time = add_to_date(group_buy.end_date, hours=-group_buy.cancel_cutoff_hours)
            if now_datetime() > cutoff_time:
                return False, _("Cancellation period has ended")

        return True, _("Commitment can be cancelled")
