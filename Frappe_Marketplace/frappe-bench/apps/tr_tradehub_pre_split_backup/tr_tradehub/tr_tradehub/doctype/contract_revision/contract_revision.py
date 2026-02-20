# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Contract Revision DocType Controller

Immutable revision history for contracts.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
import hashlib


class ContractRevision(Document):
    """
    Controller for Contract Revision DocType.

    Revision records are immutable.
    """

    def before_insert(self):
        """Set initial values."""
        if not self.created_by:
            self.created_by = frappe.session.user

        if not self.creation_date:
            self.creation_date = now_datetime()

        # Calculate content hash
        if self.content_snapshot:
            self.content_hash = hashlib.sha256(
                self.content_snapshot.encode('utf-8')
            ).hexdigest()

    def validate(self):
        """Prevent modifications to existing records."""
        if not self.is_new():
            frappe.throw(
                _("Contract Revisions are immutable and cannot be modified.")
            )

    def on_trash(self):
        """Prevent deletion."""
        frappe.throw(
            _("Contract Revisions cannot be deleted for audit purposes.")
        )
