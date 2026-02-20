# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MockExcludedApp(Document):
    """Child table for apps excluded from mock data generation.

    Used in Mock Engine Settings to specify which Frappe apps
    should be completely excluded from mock data generation.
    """

    def validate(self):
        """Validate the excluded app entry."""
        self.validate_app_name()

    def validate_app_name(self):
        """Validate that app_name is not empty and normalize it."""
        if not self.app_name:
            frappe.throw("App Name is required")

        # Normalize app name (lowercase, no spaces)
        self.app_name = self.app_name.strip().lower().replace(" ", "_")
