# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MarketplaceOrderItem(Document):
    """
    Marketplace Order Item - Child table for order line items.

    Each item represents a product from a specific seller in the order.
    Items are grouped by seller for Sub Order creation.
    """

    def validate(self):
        """Validate order item data."""
        self.validate_listing()
        self.calculate_totals()
        self.calculate_commission()

    def validate_listing(self):
        """Validate listing exists and is from correct seller."""
        if not frappe.db.exists("Listing", self.listing):
            frappe.throw(_("Listing {0} does not exist").format(self.listing))

        if self.listing_variant:
            if not frappe.db.exists("Listing Variant", self.listing_variant):
                frappe.throw(
                    _("Listing Variant {0} does not exist").format(self.listing_variant)
                )

    def calculate_totals(self):
        """Calculate line totals."""
        # Line subtotal (before discount and tax)
        self.line_subtotal = flt(self.unit_price) * flt(self.qty)

        # Calculate discount
        self.calculate_discount()

        # Line total after discount, before tax
        subtotal_after_discount = flt(self.line_subtotal) - flt(self.discount_amount)

        # Tax calculation
        if flt(self.tax_rate) > 0:
            self.tax_amount = subtotal_after_discount * (flt(self.tax_rate) / 100)
        else:
            self.tax_amount = 0

        # Final line total
        self.line_total = subtotal_after_discount + flt(self.tax_amount)

    def calculate_discount(self):
        """Calculate discount amount based on type."""
        if not self.discount_type or flt(self.discount_value) <= 0:
            self.discount_amount = 0
            return

        if self.discount_type == "Percentage":
            self.discount_amount = flt(self.line_subtotal) * (flt(self.discount_value) / 100)
        elif self.discount_type == "Fixed":
            self.discount_amount = min(flt(self.discount_value), flt(self.line_subtotal))
        else:
            self.discount_amount = 0

    def calculate_commission(self):
        """Calculate commission amount for this item."""
        if flt(self.commission_rate) > 0:
            # Commission is calculated on line subtotal (before discount and tax)
            # Or on line_total - depends on business rules
            taxable_amount = flt(self.line_subtotal) - flt(self.discount_amount)
            self.commission_amount = taxable_amount * (flt(self.commission_rate) / 100)
        else:
            self.commission_amount = 0

    def get_net_seller_amount(self):
        """Get the amount seller receives after commission."""
        taxable_amount = flt(self.line_subtotal) - flt(self.discount_amount)
        return taxable_amount - flt(self.commission_amount)

    def get_display_data(self):
        """Get formatted data for display."""
        return {
            "listing": self.listing,
            "listing_variant": self.listing_variant,
            "seller": self.seller,
            "title": self.title,
            "sku": self.sku,
            "qty": self.qty,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "fulfillment_status": self.fulfillment_status,
            "primary_image": self.primary_image
        }

    def update_fulfillment_status(self, status):
        """Update fulfillment status."""
        valid_statuses = [
            "Pending", "Processing", "Packed", "Shipped",
            "In Transit", "Out for Delivery", "Delivered",
            "Partially Delivered", "Returned", "Cancelled"
        ]
        if status not in valid_statuses:
            frappe.throw(_("Invalid fulfillment status: {0}").format(status))

        self.fulfillment_status = status

    def mark_delivered(self, qty=None):
        """Mark item as delivered."""
        deliver_qty = flt(qty) if qty else flt(self.qty)

        if deliver_qty > flt(self.qty) - flt(self.delivered_qty):
            frappe.throw(_("Cannot deliver more than ordered quantity"))

        self.delivered_qty = flt(self.delivered_qty) + deliver_qty

        if flt(self.delivered_qty) >= flt(self.qty):
            self.fulfillment_status = "Delivered"
        elif flt(self.delivered_qty) > 0:
            self.fulfillment_status = "Partially Delivered"

    def mark_returned(self, qty=None, reason=None):
        """Mark item as returned."""
        return_qty = flt(qty) if qty else flt(self.qty)

        if return_qty > flt(self.qty):
            frappe.throw(_("Cannot return more than ordered quantity"))

        self.returned_qty = flt(self.returned_qty) + return_qty

        if flt(self.returned_qty) >= flt(self.qty):
            self.fulfillment_status = "Returned"
