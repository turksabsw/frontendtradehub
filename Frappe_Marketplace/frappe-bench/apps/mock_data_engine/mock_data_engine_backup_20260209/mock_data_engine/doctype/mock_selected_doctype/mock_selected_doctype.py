# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockSelectedDocType(Document):
    """Child table for selecting DocTypes in a generation request.

    Used in Mock Generation Request when the generation mode is
    'Multiple DocTypes' to specify which DocTypes to generate
    and how many records for each.
    """

    def validate(self):
        """Validate the selected DocType entry."""
        self.validate_doctype_exists()
        self.validate_record_count()

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
