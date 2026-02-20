# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class CartLine(Document):
    """
    Cart Line DocType - child table of Cart.

    Represents a single item in a shopping cart with:
    - Product reference (Listing/Listing Variant)
    - Quantity and pricing
    - Tax calculations
    - Discount handling
    - Stock reservation tracking
    """

    def validate(self):
        """Validate cart line data."""
        self.validate_listing()
        self.validate_quantity()
        self.calculate_totals()

    def validate_listing(self):
        """Validate listing reference."""
        if not self.listing:
            frappe.throw(_("Listing is required"))

        if not frappe.db.exists("Listing", self.listing):
            frappe.throw(_("Listing {0} does not exist").format(self.listing))

        # Set seller from listing if not set
        if not self.seller:
            self.seller = frappe.db.get_value("Listing", self.listing, "seller")

        # Validate variant if specified
        if self.listing_variant:
            if not frappe.db.exists("Listing Variant", self.listing_variant):
                frappe.throw(
                    _("Listing Variant {0} does not exist").format(self.listing_variant)
                )

            # Ensure variant belongs to listing
            variant_listing = frappe.db.get_value(
                "Listing Variant", self.listing_variant, "listing"
            )
            if variant_listing != self.listing:
                frappe.throw(
                    _("Variant {0} does not belong to Listing {1}").format(
                        self.listing_variant, self.listing
                    )
                )

    def validate_quantity(self):
        """Validate quantity against listing limits."""
        if flt(self.qty) <= 0:
            frappe.throw(_("Quantity must be greater than 0"))

        listing = frappe.get_doc("Listing", self.listing)

        # Check minimum order quantity
        if flt(self.qty) < flt(listing.min_order_qty):
            frappe.throw(
                _("Minimum order quantity for {0} is {1}").format(
                    listing.title, listing.min_order_qty
                )
            )

        # Check maximum order quantity
        if listing.max_order_qty and flt(listing.max_order_qty) > 0:
            if flt(self.qty) > flt(listing.max_order_qty):
                frappe.throw(
                    _("Maximum order quantity for {0} is {1}").format(
                        listing.title, listing.max_order_qty
                    )
                )

    def calculate_totals(self):
        """Calculate line totals including discounts and taxes."""
        # Calculate discount
        self.calculate_discount()

        # Get effective unit price after discount
        effective_price = flt(self.discounted_price) or flt(self.unit_price)

        # Calculate base line total (qty * price)
        base_total = flt(self.qty) * effective_price

        # Calculate tax
        self.calculate_tax(base_total)

        # Set line total
        if self.price_includes_tax:
            # Price already includes tax, no adjustment needed
            self.line_total = base_total
        else:
            # Add tax to total
            self.line_total = base_total + flt(self.tax_amount)

    def calculate_discount(self):
        """Calculate discount amount based on type and value."""
        if not self.discount_type or flt(self.discount_value) <= 0:
            self.discount_amount = 0
            self.discounted_price = flt(self.unit_price)
            return

        if self.discount_type == "Percentage":
            # Percentage discount
            discount_percent = min(flt(self.discount_value), 100)
            self.discount_amount = flt(self.unit_price) * discount_percent / 100
        elif self.discount_type == "Fixed Amount":
            # Fixed amount discount
            self.discount_amount = min(flt(self.discount_value), flt(self.unit_price))
        else:
            self.discount_amount = 0

        # Calculate discounted price per unit
        self.discounted_price = max(0, flt(self.unit_price) - flt(self.discount_amount))

        # Total discount is per unit discount * quantity
        self.discount_amount = flt(self.discount_amount) * flt(self.qty)

    def calculate_tax(self, base_amount):
        """
        Calculate tax amount.

        Args:
            base_amount: Base amount to calculate tax on
        """
        tax_rate = flt(self.tax_rate) or 18.0  # Default Turkish VAT

        if self.price_includes_tax:
            # Extract tax from inclusive price
            # If price includes tax: base = total / (1 + rate/100)
            # tax = total - base
            tax_divisor = 1 + (tax_rate / 100)
            self.taxable_amount = base_amount / tax_divisor
            self.tax_amount = base_amount - self.taxable_amount
        else:
            # Calculate tax on base amount
            self.taxable_amount = base_amount
            self.tax_amount = base_amount * (tax_rate / 100)

        # Round tax amounts
        self.taxable_amount = round(flt(self.taxable_amount), 2)
        self.tax_amount = round(flt(self.tax_amount), 2)

    # =================================================================
    # Helper Methods
    # =================================================================

    def get_listing_doc(self):
        """Get the associated Listing document."""
        return frappe.get_doc("Listing", self.listing)

    def get_variant_doc(self):
        """Get the associated Listing Variant document if any."""
        if self.listing_variant:
            return frappe.get_doc("Listing Variant", self.listing_variant)
        return None

    def get_effective_price(self, buyer_type="B2C"):
        """
        Get the effective price considering discounts and buyer type.

        Args:
            buyer_type: "B2B" or "B2C"

        Returns:
            float: Effective unit price
        """
        listing = self.get_listing_doc()

        # Get listing price based on buyer type
        base_price = listing.get_price(qty=self.qty, buyer_type=buyer_type)

        # Apply line-level discount if any
        if self.discount_type and flt(self.discount_value) > 0:
            if self.discount_type == "Percentage":
                discount = base_price * flt(self.discount_value) / 100
            else:
                discount = flt(self.discount_value)
            return max(0, base_price - discount)

        return base_price

    def refresh_from_listing(self):
        """Refresh cart line data from listing."""
        listing = self.get_listing_doc()

        self.title = listing.title
        self.sku = listing.sku
        self.primary_image = listing.primary_image
        self.stock_uom = listing.stock_uom
        self.weight = listing.weight
        self.weight_uom = listing.weight_uom
        self.is_free_shipping = listing.is_free_shipping
        self.tax_rate = listing.tax_rate or 18.0
        self.compare_at_price = listing.compare_at_price

        # Update price if not overridden
        # Note: We don't auto-update unit_price to preserve cart price at time of add

    def check_stock_availability(self):
        """
        Check if requested quantity is available.

        Returns:
            dict: Availability info
        """
        listing = self.get_listing_doc()

        if not listing.track_inventory:
            return {
                "available": True,
                "qty_available": float("inf"),
                "message": _("Stock not tracked for this item")
            }

        available_qty = flt(listing.available_qty)

        if listing.allow_backorders:
            return {
                "available": True,
                "qty_available": available_qty,
                "backordered": max(0, flt(self.qty) - available_qty),
                "message": _("Backorders allowed")
            }

        if flt(self.qty) <= available_qty:
            return {
                "available": True,
                "qty_available": available_qty,
                "message": _("In stock")
            }

        return {
            "available": False,
            "qty_available": available_qty,
            "message": _("Only {0} available").format(available_qty)
        }

    def get_shipping_weight(self):
        """Get total shipping weight for this line."""
        if self.weight:
            return flt(self.weight) * flt(self.qty)
        return 0

    def get_display_data(self):
        """Get formatted data for display."""
        return {
            "listing": self.listing,
            "listing_variant": self.listing_variant,
            "title": self.title,
            "sku": self.sku,
            "primary_image": self.primary_image,
            "qty": self.qty,
            "unit_price": self.unit_price,
            "compare_at_price": self.compare_at_price,
            "discounted_price": self.discounted_price,
            "discount_amount": self.discount_amount,
            "line_total": self.line_total,
            "tax_amount": self.tax_amount,
            "currency": self.currency,
            "seller": self.seller,
            "seller_name": frappe.db.get_value(
                "Seller Profile", self.seller, "seller_name"
            ) if self.seller else None,
            "stock_uom": self.stock_uom,
            "is_free_shipping": self.is_free_shipping,
            "stock_reserved": self.stock_reserved,
            "availability": self.check_stock_availability()
        }

    def get_savings(self):
        """
        Calculate savings from original/compare price.

        Returns:
            dict: Savings information
        """
        savings = {
            "has_savings": False,
            "unit_savings": 0,
            "total_savings": 0,
            "savings_percent": 0
        }

        compare_price = flt(self.compare_at_price) or 0
        effective_price = flt(self.discounted_price) or flt(self.unit_price)

        if compare_price > effective_price:
            unit_savings = compare_price - effective_price
            savings.update({
                "has_savings": True,
                "unit_savings": unit_savings,
                "total_savings": unit_savings * flt(self.qty),
                "savings_percent": round((unit_savings / compare_price) * 100, 0)
            })

        return savings

    def apply_discount(self, discount_type, discount_value):
        """
        Apply discount to this cart line.

        Args:
            discount_type: "Percentage" or "Fixed Amount"
            discount_value: Discount value

        Returns:
            float: New line total
        """
        self.discount_type = discount_type
        self.discount_value = flt(discount_value)
        self.calculate_totals()
        return self.line_total

    def remove_discount(self):
        """Remove discount from this cart line."""
        self.discount_type = None
        self.discount_value = 0
        self.discount_amount = 0
        self.discounted_price = flt(self.unit_price)
        self.calculate_totals()
        return self.line_total

    def update_quantity(self, new_qty):
        """
        Update quantity and recalculate totals.

        Args:
            new_qty: New quantity

        Returns:
            float: New line total
        """
        if flt(new_qty) <= 0:
            frappe.throw(_("Quantity must be greater than 0"))

        self.qty = flt(new_qty)
        self.calculate_totals()
        return self.line_total

    def update_price(self, new_price):
        """
        Update unit price and recalculate totals.

        Args:
            new_price: New unit price

        Returns:
            float: New line total
        """
        if flt(new_price) < 0:
            frappe.throw(_("Price cannot be negative"))

        self.unit_price = flt(new_price)
        self.calculate_totals()
        return self.line_total
