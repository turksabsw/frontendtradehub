# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockExcludedDocType(Document):
    """Child table for DocTypes excluded from mock data generation.

    Used in Mock Engine Settings to specify which DocTypes
    should be excluded from mock data generation.
    """

    def validate(self):
        """Validate the excluded DocType entry."""
        self.validate_doctype_exists()

    def validate_doctype_exists(self):
        """Validate that the specified DocType exists."""
        if not self.doctype_name:
            frappe.throw("DocType is required")

        if not frappe.db.exists("DocType", self.doctype_name):
            frappe.throw(f"DocType '{self.doctype_name}' does not exist")
