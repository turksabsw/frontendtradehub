# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class ShippingRateTier(Document):
    """
    Shipping Rate Tier child table for Shipping Rule.

    Defines tiered pricing for weight-based or price-based shipping calculation.
    Each tier has a threshold range and associated rate.
    """

    def get_rate_for_value(self, value):
        """
        Get the rate for a given value.

        Args:
            value: Weight in kg or order amount

        Returns:
            float: Calculated rate
        """
        threshold_to = flt(self.threshold_to) if flt(self.threshold_to) > 0 else float('inf')

        if flt(self.threshold_from) <= value < threshold_to:
            if self.rate_type == "Fixed":
                return flt(self.rate)
            elif self.rate_type == "Percentage":
                return value * (flt(self.rate) / 100)
            elif self.rate_type == "Per KG":
                return value * flt(self.rate)

        return 0

    def get_display_text(self):
        """Get display text for the tier."""
        if flt(self.threshold_to) > 0:
            range_text = f"{self.threshold_from} - {self.threshold_to}"
        else:
            range_text = f"{self.threshold_from}+"

        if self.rate_type == "Percentage":
            rate_text = f"{self.rate}%"
        elif self.rate_type == "Per KG":
            rate_text = f"{self.rate}/kg"
        else:
            rate_text = f"{self.rate}"

        return f"{range_text}: {rate_text}"
