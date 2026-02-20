# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import re


class SellerBankAccount(Document):
    """
    Child DocType for storing seller bank account information.
    Used as a child table in Seller Profile for managing multiple bank accounts.
    """

    def validate(self):
        """Validate bank account data before saving."""
        self.validate_iban()
        self.validate_swift_code()

    def validate_iban(self):
        """
        Validate IBAN format.
        Turkish IBANs are 26 characters and start with 'TR'.
        """
        if not self.iban:
            return

        # Remove spaces and convert to uppercase
        iban = self.iban.replace(" ", "").upper()
        self.iban = iban

        # Check length for Turkish IBAN
        if iban.startswith("TR") and len(iban) != 26:
            frappe.msgprint(
                frappe._("Turkish IBAN should be 26 characters. Current length: {0}").format(len(iban)),
                indicator="orange",
                alert=True
            )

        # Basic IBAN format validation (2 letters + 2 digits + up to 30 alphanumeric)
        iban_pattern = r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$'
        if not re.match(iban_pattern, iban):
            frappe.msgprint(
                frappe._("IBAN format appears to be invalid. Please verify."),
                indicator="orange",
                alert=True
            )

    def validate_swift_code(self):
        """
        Validate SWIFT/BIC code format.
        SWIFT codes are 8 or 11 characters.
        """
        if not self.swift_code:
            return

        # Remove spaces and convert to uppercase
        swift = self.swift_code.replace(" ", "").upper()
        self.swift_code = swift

        # SWIFT code is 8 or 11 characters
        if len(swift) not in [8, 11]:
            frappe.msgprint(
                frappe._("SWIFT/BIC code should be 8 or 11 characters. Current length: {0}").format(len(swift)),
                indicator="orange",
                alert=True
            )

        # Basic SWIFT format validation (4 letters bank code + 2 letters country + 2 alphanumeric location + optional 3 alphanumeric branch)
        swift_pattern = r'^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$'
        if not re.match(swift_pattern, swift):
            frappe.msgprint(
                frappe._("SWIFT/BIC code format appears to be invalid. Please verify."),
                indicator="orange",
                alert=True
            )
