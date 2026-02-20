# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Method DocType Controller

Consent Methods define the communication channels used to contact the user.
Examples: Email, SMS, WhatsApp, Phone, Push Notification, Post.

KVKK/GDPR Compliance:
- Users can consent to specific methods independently
- Each method can have its own validation requirements
- Electronic methods (SMS, Email) require verified contact info
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class ConsentMethod(Document):
    """
    Controller for Consent Method DocType.

    Consent Methods define how the user can be contacted.
    """

    def validate(self):
        """Validate the consent method before saving."""
        self.validate_method_code()
        self.validate_regex()

    def validate_method_code(self):
        """Ensure method_code is uppercase and valid."""
        if self.method_code:
            self.method_code = self.method_code.upper().strip().replace(" ", "_")

            if not re.match(r'^[A-Z0-9_]+$', self.method_code):
                frappe.throw(
                    _("Method Code must contain only uppercase letters, numbers, and underscores")
                )

    def validate_regex(self):
        """Validate the regex pattern if provided."""
        if self.validation_regex:
            try:
                re.compile(self.validation_regex)
            except re.error as e:
                frappe.throw(
                    _("Invalid validation regex pattern: {0}").format(str(e))
                )

    def on_trash(self):
        """Prevent deletion if method is in use."""
        consent_count = frappe.db.count(
            "Consent Record",
            filters={"consent_method": self.name}
        )

        if consent_count > 0:
            frappe.throw(
                _("Cannot delete Consent Method '{0}' as it is referenced by {1} consent record(s). "
                  "Disable the method instead.").format(self.method_name, consent_count)
            )


def get_active_methods():
    """
    Get all active consent methods.

    Returns:
        list: List of active methods
    """
    return frappe.get_all(
        "Consent Method",
        filters={"enabled": 1},
        fields=["method_name", "method_code", "method_type",
                "requires_validation", "icon"],
        order_by="display_order asc"
    )


def validate_contact_for_method(method_code, contact_value):
    """
    Validate a contact value for a specific method.

    Args:
        method_code: The method code (e.g., 'EMAIL', 'PHONE')
        contact_value: The value to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    method = frappe.db.get_value(
        "Consent Method",
        {"method_code": method_code.upper(), "enabled": 1},
        ["requires_validation", "validation_regex", "validation_error_message"],
        as_dict=True
    )

    if not method:
        return False, _("Unknown consent method: {0}").format(method_code)

    if not method.requires_validation:
        return True, None

    if not method.validation_regex:
        return True, None

    if not contact_value:
        return False, _("Contact value is required")

    if re.match(method.validation_regex, contact_value):
        return True, None

    return False, method.validation_error_message or _("Invalid contact format")
