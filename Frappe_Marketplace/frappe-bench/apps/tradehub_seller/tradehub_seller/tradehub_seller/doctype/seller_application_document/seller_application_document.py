# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import now_datetime


class SellerApplicationDocument(Document):
    """Child table for additional documents in Seller Application."""

    def before_insert(self):
        """Set uploaded timestamp."""
        if not self.uploaded_at:
            self.uploaded_at = now_datetime()
