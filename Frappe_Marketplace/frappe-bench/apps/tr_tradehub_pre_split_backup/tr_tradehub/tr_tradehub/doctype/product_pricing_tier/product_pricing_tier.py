# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class ProductPricingTier(Document):
    """
    Child DocType for defining quantity-based pricing tiers for product listings.
    Used as a child table in Listing DocType for tiered/wholesale pricing.

    Pricing tiers allow sellers to offer volume discounts:
    - Tier 1: 1-9 units @ $10/unit
    - Tier 2: 10-49 units @ $9/unit
    - Tier 3: 50+ units @ $8/unit
    """

    def validate(self):
        """Validate pricing tier data before saving."""
        self.validate_quantities()
        self.validate_unit_price()
        self.validate_dates()
        self.calculate_discount()

    def validate_quantities(self):
        """
        Validate that min_qty and max_qty are logical.
        - min_qty must be positive
        - max_qty must be >= min_qty (if specified)
        """
        if flt(self.min_qty) < 0:
            frappe.throw(_("Minimum quantity cannot be negative."))

        if flt(self.min_qty) == 0:
            frappe.msgprint(
                _("Minimum quantity of 0 means this tier applies from the first unit."),
                indicator="blue",
                alert=True
            )

        if self.max_qty and flt(self.max_qty) < flt(self.min_qty):
            frappe.throw(
                _("Maximum quantity ({0}) cannot be less than minimum quantity ({1}).").format(
                    self.max_qty, self.min_qty
                )
            )

        if self.max_qty and flt(self.max_qty) == flt(self.min_qty):
            frappe.msgprint(
                _("Minimum and maximum quantities are equal. This tier applies only to exact quantity {0}.").format(
                    self.min_qty
                ),
                indicator="orange",
                alert=True
            )

    def validate_unit_price(self):
        """
        Validate that unit price is positive.
        """
        if flt(self.unit_price) < 0:
            frappe.throw(_("Unit price cannot be negative."))

        if flt(self.unit_price) == 0:
            frappe.msgprint(
                _("Unit price is set to 0. This tier will provide items for free."),
                indicator="orange",
                alert=True
            )

    def validate_dates(self):
        """
        Validate validity period dates.
        - valid_until must be >= valid_from (if both specified)
        - Warn if tier is expired
        """
        if self.valid_from and self.valid_until:
            if getdate(self.valid_until) < getdate(self.valid_from):
                frappe.throw(
                    _("Valid Until date ({0}) cannot be before Valid From date ({1}).").format(
                        self.valid_until, self.valid_from
                    )
                )

        # Warn if tier is expired
        if self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
            frappe.msgprint(
                _("This pricing tier has expired (Valid Until: {0}).").format(self.valid_until),
                indicator="orange",
                alert=True
            )

        # Warn if tier is not yet active
        if self.valid_from and getdate(self.valid_from) > getdate(nowdate()):
            frappe.msgprint(
                _("This pricing tier is not yet active (Valid From: {0}).").format(self.valid_from),
                indicator="blue",
                alert=True
            )

    def calculate_discount(self):
        """
        Calculate discount percentage and amount from base price if available.
        This requires access to the parent document's base price.
        """
        # Get the parent document to access base price
        if self.parenttype and self.parent:
            try:
                parent_doc = frappe.get_doc(self.parenttype, self.parent)
                base_price = flt(getattr(parent_doc, 'base_price', 0) or getattr(parent_doc, 'price', 0))

                if base_price > 0 and flt(self.unit_price) > 0:
                    discount_amount = base_price - flt(self.unit_price)
                    self.discount_amount = max(0, discount_amount)

                    if discount_amount > 0:
                        self.discount_percentage = (discount_amount / base_price) * 100
                    else:
                        self.discount_percentage = 0
            except Exception:
                # Parent may not exist yet or may not have price fields
                pass

    def is_valid(self):
        """
        Check if this pricing tier is currently valid.
        Returns True if:
        - is_active is True
        - Current date is within valid_from and valid_until range
        """
        if not self.is_active:
            return False

        today = getdate(nowdate())

        if self.valid_from and getdate(self.valid_from) > today:
            return False

        if self.valid_until and getdate(self.valid_until) < today:
            return False

        return True

    def matches_quantity(self, quantity):
        """
        Check if a given quantity falls within this tier's range.

        Args:
            quantity: The quantity to check

        Returns:
            True if quantity >= min_qty and (quantity <= max_qty or max_qty is not set)
        """
        qty = flt(quantity)

        if qty < flt(self.min_qty):
            return False

        if self.max_qty and qty > flt(self.max_qty):
            return False

        return True

    def get_price_for_quantity(self, quantity):
        """
        Get the total price for a given quantity using this tier's unit price.

        Args:
            quantity: The quantity to calculate price for

        Returns:
            Total price (unit_price * quantity) or 0 if quantity doesn't match tier
        """
        if not self.matches_quantity(quantity) or not self.is_valid():
            return 0

        return flt(self.unit_price) * flt(quantity)


def get_applicable_tier(pricing_tiers, quantity):
    """
    Find the applicable pricing tier for a given quantity.

    This is a utility function to be used by the parent Listing DocType.

    Args:
        pricing_tiers: List of ProductPricingTier child records
        quantity: The quantity to find a tier for

    Returns:
        The matching ProductPricingTier record or None
    """
    applicable_tier = None

    for tier in pricing_tiers:
        if tier.is_active and tier.matches_quantity(quantity):
            # Create a temporary document to use is_valid method
            tier_doc = frappe.get_doc({
                'doctype': 'Product Pricing Tier',
                'is_active': tier.is_active,
                'valid_from': tier.valid_from,
                'valid_until': tier.valid_until,
                'min_qty': tier.min_qty,
                'max_qty': tier.max_qty,
                'unit_price': tier.unit_price
            })

            if tier_doc.is_valid() and tier_doc.matches_quantity(quantity):
                # Return the tier with highest min_qty that matches
                # (most specific tier)
                if applicable_tier is None or flt(tier.min_qty) > flt(applicable_tier.min_qty):
                    applicable_tier = tier

    return applicable_tier


def calculate_tiered_price(pricing_tiers, quantity, base_price=0):
    """
    Calculate the price for a quantity using tiered pricing.

    Args:
        pricing_tiers: List of ProductPricingTier child records
        quantity: The quantity to calculate price for
        base_price: Base price to use if no tier matches

    Returns:
        dict with 'unit_price', 'total_price', 'tier_name', 'discount_percentage'
    """
    tier = get_applicable_tier(pricing_tiers, quantity)

    if tier:
        unit_price = flt(tier.unit_price)
        total_price = unit_price * flt(quantity)
        discount_pct = 0

        if base_price > 0:
            discount_pct = ((flt(base_price) - unit_price) / flt(base_price)) * 100

        return {
            'unit_price': unit_price,
            'total_price': total_price,
            'tier_name': tier.tier_name or _('Tier {0}').format(int(tier.idx or 1)),
            'discount_percentage': max(0, discount_pct),
            'tier_matched': True
        }

    # No matching tier, use base price
    return {
        'unit_price': flt(base_price),
        'total_price': flt(base_price) * flt(quantity),
        'tier_name': None,
        'discount_percentage': 0,
        'tier_matched': False
    }
