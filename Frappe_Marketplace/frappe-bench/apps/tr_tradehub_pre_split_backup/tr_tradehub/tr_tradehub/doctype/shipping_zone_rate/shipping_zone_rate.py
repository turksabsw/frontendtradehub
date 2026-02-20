# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ShippingZoneRate(Document):
    """
    Child table for zone-based shipping rates.
    Each row defines rates for a specific geographic zone.
    """

    def validate(self):
        """Validate zone configuration."""
        self.validate_zone_code()
        self.validate_rates()

    def validate_zone_code(self):
        """Format zone code."""
        if self.zone_code:
            self.zone_code = self.zone_code.upper().strip()

    def validate_rates(self):
        """Validate rate values."""
        if flt(self.base_rate) < 0:
            frappe.throw(_("Base rate cannot be negative for zone {0}").format(self.zone_name))
        if flt(self.rate_per_kg) < 0:
            frappe.throw(_("Rate per KG cannot be negative for zone {0}").format(self.zone_name))

    def matches_location(self, country_code=None, region_code=None):
        """
        Check if this zone matches a given location.

        Args:
            country_code: ISO country code
            region_code: Region/state code

        Returns:
            bool: True if location matches this zone
        """
        # Check country match
        if self.countries:
            country_list = [c.strip().upper() for c in self.countries.split(',')]
            if country_code and country_code.upper() in country_list:
                return True

        # Check region match
        if self.regions:
            region_list = [r.strip().upper() for r in self.regions.split(',')]
            if region_code and region_code.upper() in region_list:
                return True

        # If no countries or regions specified, it's a catch-all zone
        if not self.countries and not self.regions:
            return True

        return False

    def calculate_rate(self, weight_kg=0, min_chargeable_weight=0):
        """
        Calculate shipping rate for this zone.

        Args:
            weight_kg: Actual weight in kg
            min_chargeable_weight: Minimum chargeable weight from parent rule

        Returns:
            dict: {rate: float, breakdown: dict}
        """
        chargeable_weight = max(flt(weight_kg), flt(min_chargeable_weight))

        rate = flt(self.base_rate)
        weight_charge = flt(self.rate_per_kg) * chargeable_weight
        rate += weight_charge

        return {
            "rate": round(rate, 2),
            "breakdown": {
                "zone": self.zone_name,
                "base_rate": flt(self.base_rate),
                "weight_charge": weight_charge,
                "chargeable_weight": chargeable_weight,
                "estimated_days": self.estimated_days
            }
        }
