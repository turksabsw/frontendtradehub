# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SubOrderItem(Document):
    """
    Sub Order Item child table for Sub Order.

    Represents a single item in a seller's sub-order.
    Contains pricing, quantity, and fulfillment tracking.
    """

    def validate(self):
        """Validate item data."""
        self.validate_qty()
        self.calculate_totals()

    def validate_qty(self):
        """Validate quantity values."""
        if flt(self.qty) <= 0:
            frappe.throw(_("Quantity must be greater than 0"))

        if flt(self.delivered_qty) > flt(self.qty):
            frappe.throw(_("Delivered quantity cannot exceed ordered quantity"))

        if flt(self.returned_qty) > flt(self.delivered_qty):
            frappe.throw(_("Returned quantity cannot exceed delivered quantity"))

    def calculate_totals(self):
        """Calculate line totals and derived values."""
        # Line subtotal = unit_price * qty
        self.line_subtotal = flt(self.unit_price) * flt(self.qty)

        # Calculate discount
        if self.discount_type == "Percentage":
            self.discount_amount = flt(self.line_subtotal) * flt(self.discount_value) / 100
        elif self.discount_type == "Fixed":
            self.discount_amount = flt(self.discount_value)
        else:
            self.discount_amount = 0

        # Taxable amount (after discount)
        taxable_amount = flt(self.line_subtotal) - flt(self.discount_amount)

        # Calculate tax
        self.tax_amount = taxable_amount * flt(self.tax_rate) / 100

        # Line total = taxable_amount + tax
        self.line_total = taxable_amount + flt(self.tax_amount)

        # Calculate commission
        self.commission_amount = taxable_amount * flt(self.commission_rate) / 100

    def get_display_data(self):
        """Get item data for display/API."""
        return {
            "listing": self.listing,
            "listing_variant": self.listing_variant,
            "title": self.title,
            "sku": self.sku,
            "primary_image": self.primary_image,
            "qty": self.qty,
            "delivered_qty": self.delivered_qty,
            "returned_qty": self.returned_qty,
            "unit_price": self.unit_price,
            "compare_at_price": self.compare_at_price,
            "discount_amount": self.discount_amount,
            "line_subtotal": self.line_subtotal,
            "tax_rate": self.tax_rate,
            "tax_amount": self.tax_amount,
            "line_total": self.line_total,
            "fulfillment_status": self.fulfillment_status,
            "tracking_number": self.tracking_number,
            "carrier": self.carrier
        }

    def get_pending_qty(self):
        """Get quantity pending delivery."""
        return flt(self.qty) - flt(self.delivered_qty)

    def get_net_qty(self):
        """Get net quantity (delivered minus returned)."""
        return flt(self.delivered_qty) - flt(self.returned_qty)

    def update_fulfillment_status(self):
        """Update fulfillment status based on quantities."""
        if flt(self.returned_qty) == flt(self.qty):
            self.fulfillment_status = "Returned"
        elif flt(self.delivered_qty) >= flt(self.qty):
            self.fulfillment_status = "Delivered"
        elif flt(self.delivered_qty) > 0:
            self.fulfillment_status = "Partially Delivered"
