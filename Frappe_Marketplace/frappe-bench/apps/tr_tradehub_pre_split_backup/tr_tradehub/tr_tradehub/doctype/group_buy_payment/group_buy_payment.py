# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy Payment DocType Controller

Handles payment processing for group buy commitments.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class GroupBuyPayment(Document):
    """Group Buy Payment document controller."""

    def validate(self):
        """Validate payment before save."""
        self._validate_commitment()
        self._calculate_net_amount()

    def before_insert(self):
        """Set defaults before first save."""
        if not self.currency:
            group_buy = frappe.get_doc("Group Buy", self.group_buy)
            self.currency = group_buy.currency

    def after_insert(self):
        """Actions after payment creation."""
        # Update commitment status
        frappe.db.set_value(
            "Group Buy Commitment",
            self.commitment,
            "status",
            "Payment Pending"
        )

    def on_update(self):
        """Handle payment status updates."""
        if self.has_value_changed("status"):
            self._handle_status_change()

    def on_trash(self):
        """Prevent deletion of processed payments."""
        if self.status in ["Completed", "Refunded", "Partially Refunded"]:
            frappe.throw(_("Cannot delete processed payments"))

    def _validate_commitment(self):
        """Validate the linked commitment."""
        commitment = frappe.get_doc("Group Buy Commitment", self.commitment)

        # Verify group buy matches
        if commitment.group_buy != self.group_buy:
            frappe.throw(_("Commitment does not belong to the specified Group Buy"))

        # Verify buyer matches
        if commitment.buyer != self.buyer:
            frappe.throw(_("Buyer does not match the commitment"))

        # Verify amount
        if self.amount and abs(self.amount - commitment.total_amount) > 0.01:
            frappe.msgprint(
                _("Payment amount ({0}) differs from commitment amount ({1})").format(
                    self.amount, commitment.total_amount
                ),
                indicator="orange"
            )

    def _calculate_net_amount(self):
        """Calculate net amount after fees."""
        if self.amount:
            self.net_amount = self.amount - (self.platform_fee or 0)

    def _handle_status_change(self):
        """Handle payment status transitions."""
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_status = old_doc.status
        new_status = self.status

        frappe.logger().info(
            f"Payment {self.name} status changed: {old_status} -> {new_status}"
        )

        if new_status == "Completed" and old_status != "Completed":
            self._process_completion()

        elif new_status == "Failed":
            self._process_failure()

        elif new_status in ["Refunded", "Partially Refunded"]:
            self._process_refund()

        elif new_status == "Cancelled":
            self._process_cancellation()

    def _process_completion(self):
        """Process successful payment completion."""
        self.payment_date = now_datetime()
        self.processed_at = now_datetime()
        self.processed_by = frappe.session.user

        # Update commitment status to Paid
        frappe.db.set_value(
            "Group Buy Commitment",
            self.commitment,
            "status",
            "Paid"
        )

        # Notify buyer
        self._notify_payment_success()

        # Check if all commitments are paid
        self._check_group_buy_completion()

    def _process_failure(self):
        """Process payment failure."""
        # Revert commitment to active
        frappe.db.set_value(
            "Group Buy Commitment",
            self.commitment,
            {
                "status": "Active",
                "price_locked": 0
            }
        )

        # Notify buyer
        self._notify_payment_failure()

    def _process_refund(self):
        """Process refund."""
        self.refunded_at = now_datetime()

        # Update commitment status
        commitment = frappe.get_doc("Group Buy Commitment", self.commitment)
        commitment.status = "Refunded"
        commitment.refunded_at = now_datetime()
        commitment.refund_amount = self.refund_amount or self.amount
        commitment.save(ignore_permissions=True)

        # Notify buyer
        self._notify_refund()

    def _process_cancellation(self):
        """Process payment cancellation."""
        # Revert commitment if not already cancelled
        commitment = frappe.get_doc("Group Buy Commitment", self.commitment)
        if commitment.status == "Payment Pending":
            commitment.status = "Active"
            commitment.price_locked = 0
            commitment.save(ignore_permissions=True)

    def _notify_payment_success(self):
        """Notify buyer of successful payment."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            group_buy = frappe.get_doc("Group Buy", self.group_buy)
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Payment",
                "document_name": self.name,
                "subject": _("Payment Successful"),
                "email_content": _(
                    "Your payment of {0} for '{1}' has been processed successfully. "
                    "Thank you for your participation!"
                ).format(self.amount, group_buy.title)
            }).insert(ignore_permissions=True)

    def _notify_payment_failure(self):
        """Notify buyer of payment failure."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Payment",
                "document_name": self.name,
                "subject": _("Payment Failed"),
                "email_content": _(
                    "Your payment could not be processed. "
                    "Please try again or contact support."
                )
            }).insert(ignore_permissions=True)

    def _notify_refund(self):
        """Notify buyer of refund."""
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy Payment",
                "document_name": self.name,
                "subject": _("Refund Processed"),
                "email_content": _(
                    "A refund of {0} has been processed. "
                    "Please allow 5-10 business days for the funds to appear."
                ).format(self.refund_amount or self.amount)
            }).insert(ignore_permissions=True)

    def _check_group_buy_completion(self):
        """Check if all payments are complete and update group buy."""
        group_buy = frappe.get_doc("Group Buy", self.group_buy)

        if group_buy.status != "Funded":
            return

        # Count pending payments
        pending_count = frappe.db.count(
            "Group Buy Payment",
            {
                "group_buy": self.group_buy,
                "status": ["in", ["Pending", "Processing"]]
            }
        )

        if pending_count == 0:
            # All payments complete - mark group buy as completed
            group_buy.status = "Completed"
            group_buy.completed_at = now_datetime()
            group_buy.save(ignore_permissions=True)

            # Notify seller
            seller_user = frappe.db.get_value("Seller Profile", group_buy.seller, "user")
            if seller_user:
                frappe.get_doc({
                    "doctype": "Notification Log",
                    "for_user": seller_user,
                    "type": "Alert",
                    "document_type": "Group Buy",
                    "document_name": self.group_buy,
                    "subject": _("Group Buy Completed!"),
                    "email_content": _(
                        "All payments for '{0}' have been collected. "
                        "You can now fulfill the orders."
                    ).format(group_buy.title)
                }).insert(ignore_permissions=True)
