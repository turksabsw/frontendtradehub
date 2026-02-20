# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockProfileTargetApp(Document):
    """Child table for target apps in a generation profile.

    Used in Mock Generation Profile when the target mode is
    'All DocTypes in Apps' to specify which apps to include
    in the generation.
    """

    def validate(self):
        """Validate the target app entry."""
        self.validate_app_name()
        self.validate_default_record_count()

    def validate_app_name(self):
        """Validate that app_name is not empty and normalize it."""
        if not self.app_name:
            frappe.throw("App Name is required")

        # Normalize app name (lowercase, no spaces)
        self.app_name = self.app_name.strip().lower().replace(" ", "_")

    def validate_default_record_count(self):
        """Validate that default record count is reasonable."""
        if self.default_record_count is None:
            self.default_record_count = 10

        if self.default_record_count < 1:
            frappe.throw("Default Record Count must be at least 1")

        if self.default_record_count > 100000:
            frappe.throw("Default Record Count cannot exceed 100,000")
