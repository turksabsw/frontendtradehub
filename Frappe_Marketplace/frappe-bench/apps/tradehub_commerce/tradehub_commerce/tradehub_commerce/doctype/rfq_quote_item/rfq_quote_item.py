# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RFQQuoteItem(Document):
    """
    RFQ Quote Item - Child table for items in an RFQ Quote.

    Each item must reference an item from the parent RFQ.
    """

    def validate(self):
        """Validate the quote item"""
        self.calculate_total_price()
        self.validate_quantity()
        self.validate_unit_price()

    def calculate_total_price(self):
        """Calculate total price from qty and unit_price"""
        self.total_price = flt(self.qty) * flt(self.unit_price)

    def validate_quantity(self):
        """Validate quantity is positive"""
        if flt(self.qty) <= 0:
            frappe.throw(_("Row {0}: Quantity must be greater than zero").format(self.idx))

    def validate_unit_price(self):
        """Validate unit price is positive"""
        if flt(self.unit_price) < 0:
            frappe.throw(_("Row {0}: Unit Price cannot be negative").format(self.idx))
