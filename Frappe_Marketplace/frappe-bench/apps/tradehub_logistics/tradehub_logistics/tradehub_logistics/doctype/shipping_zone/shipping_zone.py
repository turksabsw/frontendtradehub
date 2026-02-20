# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShippingZone(Document):
    """
    Shipping Zone child table for Shipping Rule.

    Defines geographic zones where a shipping rule applies.
    Supports filtering by country, city, and postal code range.
    """

    def get_display_name(self):
        """Get display name for the zone."""
        if self.zone_name:
            return self.zone_name

        parts = [self.country]
        if self.city:
            parts.append(self.city)
        if self.postal_code_from and self.postal_code_to:
            parts.append(f"({self.postal_code_from}-{self.postal_code_to})")
        elif self.postal_code_from:
            parts.append(f"({self.postal_code_from}+)")

        return " - ".join(parts)
