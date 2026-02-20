# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SellerLevelBenefit(Document):
    """Child table for Seller Level benefits."""

    def validate(self):
        """Validate benefit data."""
        self.validate_value()
        self.validate_benefit_code()

    def validate_value(self):
        """Validate value based on value_type."""
        if not self.value:
            return

        if self.value_type == "Percentage":
            try:
                val = float(self.value)
                if val < 0 or val > 100:
                    frappe.msgprint(
                        _("Percentage value should be between 0 and 100"),
                        indicator="orange",
                        alert=True
                    )
            except (ValueError, TypeError):
                frappe.msgprint(
                    _("Invalid percentage value: {0}").format(self.value),
                    indicator="orange",
                    alert=True
                )
        elif self.value_type == "Fixed Amount":
            try:
                val = float(self.value)
                if val < 0:
                    frappe.msgprint(
                        _("Fixed amount cannot be negative"),
                        indicator="orange",
                        alert=True
                    )
            except (ValueError, TypeError):
                frappe.msgprint(
                    _("Invalid fixed amount value: {0}").format(self.value),
                    indicator="orange",
                    alert=True
                )
        elif self.value_type == "Count":
            try:
                val = int(self.value)
                if val < 0:
                    frappe.msgprint(
                        _("Count cannot be negative"),
                        indicator="orange",
                        alert=True
                    )
            except (ValueError, TypeError):
                frappe.msgprint(
                    _("Invalid count value: {0}").format(self.value),
                    indicator="orange",
                    alert=True
                )
        elif self.value_type == "Boolean":
            if self.value.lower() not in ["true", "false", "1", "0", "yes", "no"]:
                frappe.msgprint(
                    _("Boolean value should be true/false, yes/no, or 1/0"),
                    indicator="orange",
                    alert=True
                )
        elif self.value_type == "Multiplier":
            try:
                val = float(self.value)
                if val <= 0:
                    frappe.msgprint(
                        _("Multiplier should be greater than 0"),
                        indicator="orange",
                        alert=True
                    )
            except (ValueError, TypeError):
                frappe.msgprint(
                    _("Invalid multiplier value: {0}").format(self.value),
                    indicator="orange",
                    alert=True
                )

    def validate_benefit_code(self):
        """Validate benefit code format."""
        if self.benefit_code:
            # Ensure uppercase and only alphanumeric + underscore
            import re
            if not re.match(r'^[A-Z0-9_]+$', self.benefit_code.upper()):
                frappe.msgprint(
                    _("Benefit code should contain only letters, numbers, and underscores"),
                    indicator="orange",
                    alert=True
                )
            # Auto-format to uppercase
            self.benefit_code = self.benefit_code.upper().replace(" ", "_")

    def get_numeric_value(self):
        """Get the value as a numeric type based on value_type."""
        if not self.value:
            return None

        try:
            if self.value_type in ["Percentage", "Fixed Amount", "Multiplier"]:
                return float(self.value)
            elif self.value_type == "Count":
                return int(self.value)
            elif self.value_type == "Boolean":
                return self.value.lower() in ["true", "1", "yes"]
            else:
                return self.value
        except (ValueError, TypeError):
            return self.value

    def is_applicable(self):
        """Check if this benefit is currently applicable."""
        return self.is_active == 1

    def get_display_value(self):
        """Get a formatted display value for the benefit."""
        if not self.value:
            return _("Enabled") if self.is_active else _("Disabled")

        if self.value_type == "Percentage":
            return f"{self.value}%"
        elif self.value_type == "Fixed Amount":
            return frappe.format_value(float(self.value), {"fieldtype": "Currency"})
        elif self.value_type == "Count":
            return str(self.value)
        elif self.value_type == "Boolean":
            return _("Yes") if self.get_numeric_value() else _("No")
        elif self.value_type == "Multiplier":
            return f"{self.value}x"
        else:
            return self.value

    def applies_to_seller(self, seller_doc=None):
        """Check if this benefit applies to a specific seller."""
        if not self.is_active:
            return False
        # Additional logic can be added here based on seller attributes
        return True
