# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
ESign Provider DocType Controller

Configuration for e-signature providers.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ESignProvider(Document):
    """
    Controller for ESign Provider DocType.
    """

    def validate(self):
        """Validate provider configuration."""
        self.validate_default()
        self.validate_api_config()

    def validate_default(self):
        """Ensure only one default provider."""
        if self.is_default and self.enabled:
            # Unset other defaults
            frappe.db.sql("""
                UPDATE `tabESign Provider`
                SET is_default = 0
                WHERE name != %s AND is_default = 1
            """, self.name)

    def validate_api_config(self):
        """Validate API configuration."""
        if self.enabled and not self.api_url:
            frappe.throw(_("API URL is required for enabled providers"))

    def on_trash(self):
        """Prevent deletion if provider has transactions."""
        transaction_count = frappe.db.count(
            "ESign Transaction",
            filters={"provider": self.name}
        )

        if transaction_count > 0:
            frappe.throw(
                _("Cannot delete provider with {0} transaction(s). Disable instead.").format(
                    transaction_count
                )
            )
