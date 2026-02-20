# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockProfileDocTypeQuantity(Document):
    """Child table for DocType quantities in a generation profile.

    Used in Mock Generation Profile when the target mode is
    'Specific DocTypes' to specify exactly which DocTypes to generate
    and how many records for each.
    """

    def validate(self):
        """Validate the DocType quantity entry."""
        self.validate_doctype_exists()
        self.validate_record_count()
        self.validate_priority()

    def validate_doctype_exists(self):
        """Validate that the specified DocType exists."""
        if not self.doctype_name:
            frappe.throw("DocType is required")

        if not frappe.db.exists("DocType", self.doctype_name):
            frappe.throw(f"DocType '{self.doctype_name}' does not exist")

    def validate_record_count(self):
        """Validate that record count is a positive integer."""
        if self.record_count is None:
            self.record_count = 10

        if self.record_count < 1:
            frappe.throw("Record Count must be at least 1")

        if self.record_count > 100000:
            frappe.throw("Record Count cannot exceed 100,000")

    def validate_priority(self):
        """Validate that priority is a non-negative integer."""
        if self.priority is None:
            self.priority = 0

        if self.priority < 0:
            self.priority = 0
