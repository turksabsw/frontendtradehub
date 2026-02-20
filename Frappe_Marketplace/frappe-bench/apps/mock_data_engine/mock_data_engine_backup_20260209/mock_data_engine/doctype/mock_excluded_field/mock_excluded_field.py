# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockExcludedField(Document):
    """Child table for fields excluded from mock data generation.

    Used to specify which specific fields within DocTypes
    should be excluded from mock data generation.
    """

    def validate(self):
        """Validate the excluded field entry."""
        self.validate_doctype_exists()
        self.validate_field_exists()

    def validate_doctype_exists(self):
        """Validate that the specified DocType exists."""
        if not self.doctype_name:
            frappe.throw("DocType is required")

        if not frappe.db.exists("DocType", self.doctype_name):
            frappe.throw(f"DocType '{self.doctype_name}' does not exist")

    def validate_field_exists(self):
        """Validate that the specified field exists in the DocType."""
        if not self.field_name:
            frappe.throw("Field Name is required")

        if not self.doctype_name:
            return

        meta = frappe.get_meta(self.doctype_name)
        field_names = [f.fieldname for f in meta.fields]

        if self.field_name not in field_names:
            frappe.throw(
                f"Field '{self.field_name}' does not exist in DocType '{self.doctype_name}'"
            )
