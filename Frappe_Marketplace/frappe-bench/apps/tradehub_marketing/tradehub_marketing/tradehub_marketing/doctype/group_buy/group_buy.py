# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy DocType Controller

Handles contribution-based bulk purchasing campaigns with dynamic pricing.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, add_to_date


class GroupBuy(Document):
    """Group Buy campaign document controller."""

    def validate(self):
        """Validate group buy data before save."""
        self._validate_dates()
        self._validate_pricing()
        self._validate_quantities()

    def before_insert(self):
        """Set defaults before first save."""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.created_at:
            self.created_at = now_datetime()
        if not self.current_price:
            self.current_price = self.max_price

    def before_save(self):
        """Process before saving."""
        self._update_progress_stats()

    def after_insert(self):
        """Actions after group buy creation."""
        # Log creation
        frappe.logger().info(f"Group Buy created: {self.name} by {self.seller}")

    def on_update(self):
        """Handle status transitions."""
        if self.has_value_changed("status"):
            self._handle_status_change()

    def _validate_dates(self):
        """Validate start and end dates."""
        if self.start_date and self.end_date:
            if getdate(self.start_date) >= getdate(self.end_date):
                frappe.throw(_("End Date must be after Start Date"))

    def _validate_pricing(self):
        """Validate pricing fields."""
        if self.max_price and self.best_price:
            if self.best_price > self.max_price:
                frappe.throw(_("Best Price cannot be greater than Max Price"))

            if self.profitability_floor and self.profitability_floor > self.max_price:
                frappe.throw(_("Profitability Floor cannot exceed Max Price"))

        if self.reference_share and (self.reference_share <= 0 or self.reference_share > 1):
            frappe.throw(_("Reference Share must be between 0 and 1 (e.g., 0.20 for 20%)"))

        if self.alpha_factor and self.alpha_factor <= 0:
            frappe.throw(_("Alpha Factor must be positive"))

    def _validate_quantities(self):
        """Validate quantity settings."""
        if self.target_quantity and self.target_quantity <= 0:
            frappe.throw(_("Target Quantity must be positive"))

        if self.min_quantity and self.min_quantity <= 0:
            frappe.throw(_("Min Quantity must be positive"))

        if self.max_quantity_per_buyer and self.min_quantity:
            if self.max_quantity_per_buyer < self.min_quantity:
                frappe.throw(_("Max Quantity Per Buyer cannot be less than Min Quantity"))

    def _update_progress_stats(self):
        """Update computed progress statistics."""
        if self.current_quantity and self.target_quantity:
            progress = (self.current_quantity / self.target_quantity) * 100
            # Status auto-update if target reached
            if progress >= 100 and self.status == "Active":
                self.status = "Funded"
                self.funded_at = now_datetime()

    def _handle_status_change(self):
        """Handle status transitions and notifications."""
        old_status = self.get_doc_before_save()
        if not old_status:
            return

        old_status = old_status.status
        new_status = self.status

        # Log status change
        frappe.logger().info(
            f"Group Buy {self.name} status changed: {old_status} -> {new_status}"
        )

        # Send notifications based on status change
        if new_status == "Active" and old_status in ["Draft", "Scheduled", "Pending Approval"]:
            self._notify_activation()
        elif new_status == "Funded":
            self._notify_funded()
        elif new_status == "Completed":
            self.completed_at = now_datetime()
            self._notify_completion()
        elif new_status == "Expired":
            self._notify_expiration()
        elif new_status == "Cancelled":
            self._notify_cancellation()

    def _notify_activation(self):
        """Notify seller that group buy is now active."""
        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")
        if seller_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": seller_user,
                "type": "Alert",
                "document_type": "Group Buy",
                "document_name": self.name,
                "subject": _("Group Buy Activated"),
                "email_content": _(
                    "Your group buy '{0}' is now active and accepting commitments."
                ).format(self.title)
            }).insert(ignore_permissions=True)

    def _notify_funded(self):
        """Notify seller and buyers that target was reached."""
        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")
        if seller_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": seller_user,
                "type": "Alert",
                "document_type": "Group Buy",
                "document_name": self.name,
                "subject": _("Group Buy Target Reached!"),
                "email_content": _(
                    "Your group buy '{0}' has reached its target quantity of {1}. "
                    "Total participants: {2}"
                ).format(self.title, self.target_quantity, self.participant_count)
            }).insert(ignore_permissions=True)

    def _notify_completion(self):
        """Notify about group buy completion."""
        frappe.publish_realtime(
            "group_buy_completed",
            {"group_buy": self.name, "title": self.title},
            doctype="Group Buy",
            docname=self.name
        )

    def _notify_expiration(self):
        """Notify about group buy expiration."""
        frappe.publish_realtime(
            "group_buy_expired",
            {"group_buy": self.name, "title": self.title},
            doctype="Group Buy",
            docname=self.name
        )

    def _notify_cancellation(self):
        """Notify about group buy cancellation."""
        frappe.publish_realtime(
            "group_buy_cancelled",
            {"group_buy": self.name, "title": self.title},
            doctype="Group Buy",
            docname=self.name
        )

    def get_progress_percent(self) -> float:
        """Get current progress percentage."""
        if not self.target_quantity or self.target_quantity <= 0:
            return 0.0
        return min(100.0, (self.current_quantity / self.target_quantity) * 100)

    def get_remaining_quantity(self) -> float:
        """Get remaining quantity needed to reach target."""
        if not self.target_quantity:
            return 0.0
        return max(0.0, self.target_quantity - (self.current_quantity or 0))

    def can_accept_commitment(self, quantity: float) -> tuple:
        """
        Check if a commitment of given quantity can be accepted.

        Returns:
            tuple: (can_accept: bool, message: str)
        """
        if self.status != "Active":
            return False, _("Group buy is not active")

        if now_datetime() > self.end_date:
            return False, _("Group buy has ended")

        if quantity < self.min_quantity:
            return False, _("Quantity below minimum of {0}").format(self.min_quantity)

        if self.max_quantity_per_buyer and quantity > self.max_quantity_per_buyer:
            return False, _("Quantity exceeds maximum of {0}").format(self.max_quantity_per_buyer)

        return True, _("Commitment can be accepted")

    def recalculate_prices(self):
        """Recalculate all commitment prices using the pricing module."""
        from tradehub_marketing.tradehub_marketing.groupbuy.pricing import calculate_all_prices
        return calculate_all_prices(self.name)
