# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Buyer Profile DocType Controller

Manages buyer profiles for marketplace and group buy participation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class BuyerProfile(Document):
    """Buyer Profile document controller."""

    def validate(self):
        """Validate buyer profile data."""
        self._validate_user()
        self._set_display_name()

    def before_insert(self):
        """Set defaults before first save."""
        if not self.joined_at:
            self.joined_at = now_datetime()
        if not self.created_by:
            self.created_by = frappe.session.user

    def on_update(self):
        """Update last active timestamp."""
        frappe.db.set_value(
            "Buyer Profile",
            self.name,
            "last_active_at",
            now_datetime(),
            update_modified=False
        )

    def _validate_user(self):
        """Validate user link."""
        if self.user:
            # Check if user already has a buyer profile
            existing = frappe.db.get_value(
                "Buyer Profile",
                {"user": self.user, "name": ["!=", self.name]},
                "name"
            )
            if existing:
                frappe.throw(
                    _("User {0} already has a buyer profile: {1}").format(
                        self.user, existing
                    )
                )

    def _set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.buyer_name

    def update_group_buy_stats(self):
        """Update group buy participation statistics."""
        # Count total commitments
        commitments = frappe.db.get_all(
            "Group Buy Commitment",
            filters={"buyer": self.name, "status": ["in", ["Active", "Paid", "Payment Pending"]]},
            fields=["name", "group_buy", "total_amount"]
        )

        self.total_commitments = len(commitments)
        self.total_commitment_amount = sum(c.total_amount or 0 for c in commitments)

        # Count unique group buys
        group_buys = set(c.group_buy for c in commitments)
        self.total_group_buys = len(group_buys)

        # Count successful group buys
        if group_buys:
            successful = frappe.db.count(
                "Group Buy",
                {"name": ["in", list(group_buys)], "status": ["in", ["Funded", "Completed"]]}
            )
            self.successful_group_buys = successful

        self.save(ignore_permissions=True)

    def update_order_stats(self):
        """Update order statistics."""
        orders = frappe.db.get_all(
            "Marketplace Order",
            filters={"buyer": self.name, "status": ["not in", ["Cancelled", "Draft"]]},
            fields=["name", "grand_total", "creation"]
        )

        self.total_orders = len(orders)
        self.total_spent = sum(o.grand_total or 0 for o in orders)

        if orders:
            self.average_order_value = self.total_spent / len(orders)
            self.last_order_date = max(o.creation for o in orders)

        self.save(ignore_permissions=True)

    def get_active_commitments(self):
        """Get list of active group buy commitments."""
        return frappe.db.get_all(
            "Group Buy Commitment",
            filters={"buyer": self.name, "status": ["in", ["Active", "Payment Pending"]]},
            fields=["name", "group_buy", "quantity", "unit_price", "total_amount", "status"]
        )

    def can_participate_in_group_buy(self, group_buy_name: str) -> tuple:
        """
        Check if buyer can participate in a group buy.

        Returns:
            tuple: (can_participate: bool, message: str)
        """
        if self.status != "Active":
            return False, _("Buyer account is not active")

        group_buy = frappe.get_doc("Group Buy", group_buy_name)

        if group_buy.status != "Active":
            return False, _("Group buy is not active")

        return True, _("Can participate")
