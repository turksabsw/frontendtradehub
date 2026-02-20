# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, flt


class CartItem(Document):
    def validate(self):
        """Validate cart item data"""
        self.validate_quantity()
        self.fetch_seller_from_listing()
        self.calculate_line_totals()

    def validate_quantity(self):
        """Ensure quantity is positive and within limits"""
        if flt(self.qty) <= 0:
            frappe.throw(_("Quantity must be greater than zero"))

        if self.listing:
            listing_data = frappe.db.get_value(
                "Listing",
                self.listing,
                ["min_order_qty", "max_order_qty"],
                as_dict=True
            )

            if listing_data:
                min_qty = flt(listing_data.get("min_order_qty") or 1)
                max_qty = flt(listing_data.get("max_order_qty") or 0)

                if flt(self.qty) < min_qty:
                    frappe.throw(
                        _("Minimum order quantity for this product is {0}").format(min_qty)
                    )

                if max_qty > 0 and flt(self.qty) > max_qty:
                    frappe.throw(
                        _("Maximum order quantity for this product is {0}").format(max_qty)
                    )

    def fetch_seller_from_listing(self):
        """Fetch seller from the listing"""
        if self.listing and not self.seller:
            self.seller = frappe.db.get_value("Listing", self.listing, "seller")

    def calculate_line_totals(self):
        """Calculate line subtotal and totals"""
        self.line_subtotal = flt(self.unit_price) * flt(self.qty)

        # Get tax rate from listing
        if self.listing:
            tax_rate = frappe.db.get_value("Listing", self.listing, "tax_rate") or 18
        else:
            tax_rate = 18

        self.tax_amount = flt(self.line_subtotal) * flt(tax_rate) / 100
        self.line_total = flt(self.line_subtotal) + flt(self.tax_amount) - flt(self.discount_amount or 0)
