# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
ESign Transaction DocType Controller

Records of e-signature transactions with providers.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ESignTransaction(Document):
    """
    Controller for ESign Transaction DocType.
    """

    def before_insert(self):
        """Set initial values."""
        if not self.initiated_at:
            self.initiated_at = now_datetime()

    def validate(self):
        """Validate the transaction."""
        self.validate_status_transition()

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("ESign Transaction", self.name, "status")

        # Terminal states
        terminal_states = ["Completed", "Rejected", "Expired", "Failed"]

        if old_status in terminal_states and self.status != old_status:
            frappe.throw(
                _("Cannot change status from terminal state: {0}").format(old_status)
            )

    def before_save(self):
        """Handle status changes."""
        if self.has_value_changed("status"):
            if self.status == "Completed":
                self.completed_at = now_datetime()
                if not self.signed_at:
                    self.signed_at = now_datetime()

                # Update contract instance
                self.update_contract_status("Signed")

            elif self.status == "Rejected":
                self.completed_at = now_datetime()
                self.update_contract_status("Rejected")

            elif self.status == "Expired":
                self.completed_at = now_datetime()

    def update_contract_status(self, new_status):
        """Update the linked contract instance status."""
        if self.contract_instance:
            contract = frappe.get_doc("Contract Instance", self.contract_instance)

            contract.status = new_status

            if new_status == "Signed":
                contract.signed_at = self.signed_at or now_datetime()
                if self.signed_pdf:
                    contract.signed_pdf = self.signed_pdf

            contract.save(ignore_permissions=True)
