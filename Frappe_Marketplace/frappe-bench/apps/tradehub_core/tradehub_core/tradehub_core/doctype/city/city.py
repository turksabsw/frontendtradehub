# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class City(Document):
    """
    City (Il) DocType for Turkish provinces.

    Represents the 81 provinces of Turkey with their official plate codes (01-81),
    names, and geographic regions. Used as the top level of the address hierarchy:
    City -> District -> Neighborhood
    """

    def validate(self):
        """Validate city data before saving."""
        self.validate_city_code()
        self.validate_city_name()

    def validate_city_code(self):
        """Validate Turkish city code format (01-81)."""
        if self.city_code:
            city_code = self.city_code.strip()

            # Must be 2 digits
            if not city_code.isdigit() or len(city_code) != 2:
                frappe.throw(_("City code must be a 2-digit number (01-81)"))

            # Must be in valid range (01-81)
            code_int = int(city_code)
            if code_int < 1 or code_int > 81:
                frappe.throw(_("City code must be between 01 and 81"))

            # Ensure leading zero format
            self.city_code = city_code.zfill(2)

    def validate_city_name(self):
        """Validate city name is not empty and properly formatted."""
        if self.city_name:
            self.city_name = self.city_name.strip()
            if len(self.city_name) < 2:
                frappe.throw(_("City name must be at least 2 characters"))

    def on_trash(self):
        """Prevent deletion of city with linked districts."""
        self.check_linked_documents()

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked districts
        if frappe.db.exists("District", {"city": self.name}):
            frappe.throw(
                _("Cannot delete City with linked Districts. Please delete all Districts in this city first.")
            )

    def get_district_count(self):
        """Get count of districts for this city."""
        return frappe.db.count("District", {"city": self.name})

    def get_districts(self):
        """Get all districts for this city."""
        return frappe.get_all(
            "District",
            filters={"city": self.name},
            fields=["name", "district_name", "district_code"],
            order_by="district_name asc"
        )


@frappe.whitelist()
def get_cities_by_region(region):
    """
    Get all cities in a specific region.

    Args:
        region: Geographic region name (e.g., 'Marmara', 'Ege')

    Returns:
        list: Cities in the specified region
    """
    return frappe.get_all(
        "City",
        filters={"region": region, "is_active": 1},
        fields=["name", "city_code", "city_name", "phone_code"],
        order_by="city_name asc"
    )


@frappe.whitelist()
def get_active_cities():
    """
    Get all active cities.

    Returns:
        list: All active cities ordered by code
    """
    return frappe.get_all(
        "City",
        filters={"is_active": 1},
        fields=["name", "city_code", "city_name", "region", "phone_code"],
        order_by="city_code asc"
    )


@frappe.whitelist()
def search_cities(query):
    """
    Search cities by name or code.

    Args:
        query: Search term

    Returns:
        list: Matching cities
    """
    if not query:
        return []

    return frappe.get_all(
        "City",
        filters={
            "is_active": 1
        },
        or_filters={
            "city_name": ["like", f"%{query}%"],
            "city_code": ["like", f"%{query}%"]
        },
        fields=["name", "city_code", "city_name", "region"],
        order_by="city_name asc",
        limit=20
    )
