# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PIMVariantAxisValue(Document):
    """
    Child table for PIM Product Variant that stores axis values.

    Each variant is defined by a combination of axis values (e.g., Color=Red, Size=XL).
    This table stores those attribute-value pairs for each variant.
    """

    def before_save(self):
        """Set value_label from value if not provided."""
        if not self.value_label and self.value:
            self.value_label = self.value
