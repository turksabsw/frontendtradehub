# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AddressItem(Document):
    """Child table for managing multiple addresses with full Turkish address hierarchy.

    This child table supports:
    - Multiple address types (Billing, Shipping, Warehouse, Store, etc.)
    - Full Turkish address hierarchy (City -> District -> Neighborhood)
    - Default address marking per type
    - Contact information per address
    """

    def validate(self):
        """Validate address item data."""
        self.validate_address_hierarchy()

    def validate_address_hierarchy(self):
        """Ensure district belongs to selected city and neighborhood belongs to selected district."""
        if self.district and self.city:
            district_city = frappe.db.get_value("District", self.district, "city")
            if district_city and district_city != self.city:
                frappe.throw(
                    _("District {0} does not belong to City {1}").format(
                        self.district, self.city
                    )
                )

        if self.neighborhood and self.district:
            neighborhood_district = frappe.db.get_value("Neighborhood", self.neighborhood, "district")
            if neighborhood_district and neighborhood_district != self.district:
                frappe.throw(
                    _("Neighborhood {0} does not belong to District {1}").format(
                        self.neighborhood, self.district
                    )
                )

    def get_full_address(self):
        """Return the full address as a formatted string."""
        parts = []

        if self.street_address:
            parts.append(self.street_address)

        if self.building_info:
            parts.append(self.building_info)

        if self.neighborhood_name:
            parts.append(self.neighborhood_name + " Mah.")

        if self.district_name:
            parts.append(self.district_name)

        if self.city_name:
            parts.append(self.city_name)

        if self.postal_code:
            parts.append(self.postal_code)

        return ", ".join(parts) if parts else ""

    def get_display_title(self):
        """Return a display title for the address."""
        if self.address_title:
            return self.address_title

        parts = []
        if self.address_type:
            parts.append(self.address_type)
        if self.city_name:
            parts.append(self.city_name)
        if self.district_name:
            parts.append(self.district_name)

        return " - ".join(parts) if parts else _("Unnamed Address")
