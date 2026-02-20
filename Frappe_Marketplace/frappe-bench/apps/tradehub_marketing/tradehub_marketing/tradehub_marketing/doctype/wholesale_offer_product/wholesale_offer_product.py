# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class WholesaleOfferProduct(Document):
    def validate(self):
        """Validate the wholesale offer product item."""
        self.calculate_total_price()

    def calculate_total_price(self):
        """Calculate total price based on quantity and unit price."""
        self.total_price = flt(self.quantity) * flt(self.unit_price)
