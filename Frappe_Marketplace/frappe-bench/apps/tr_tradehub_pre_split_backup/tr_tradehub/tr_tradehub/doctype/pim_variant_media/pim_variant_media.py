# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PIMVariantMedia(Document):
    """
    Child table for PIM Product Variant that stores variant-specific media.

    Variants can have their own images/videos that override or supplement
    the parent product's media (e.g., showing a specific color variant).
    """

    def before_save(self):
        """Auto-detect file metadata if possible."""
        # Alt text defaults to title if not provided
        if not self.alt_text and self.title:
            self.alt_text = self.title
