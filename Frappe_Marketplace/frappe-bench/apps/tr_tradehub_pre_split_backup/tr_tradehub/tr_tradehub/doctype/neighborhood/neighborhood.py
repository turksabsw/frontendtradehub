# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Neighborhood(Document):
    """
    Neighborhood (Mahalle) DocType for Turkish neighborhoods.

    Represents neighborhoods within Turkish districts. Each neighborhood belongs to a single
    district and is the lowest level of the address hierarchy: City -> District -> Neighborhood
    """

    def validate(self):
        """Validate neighborhood data before saving."""
        self.validate_neighborhood_name()
        self.validate_district()
        self.validate_unique_neighborhood_in_district()

    def validate_neighborhood_name(self):
        """Validate neighborhood name is not empty and properly formatted."""
        if self.neighborhood_name:
            self.neighborhood_name = self.neighborhood_name.strip()
            if len(self.neighborhood_name) < 2:
                frappe.throw(_("Neighborhood name must be at least 2 characters"))

    def validate_district(self):
        """Validate that the linked district exists and is active."""
        if self.district:
            district_doc = frappe.get_cached_doc("District", self.district)
            if not district_doc.is_active:
                frappe.throw(
                    _("Cannot link to inactive District '{0}'. Please select an active district.").format(
                        district_doc.district_name
                    )
                )

    def validate_unique_neighborhood_in_district(self):
        """Ensure neighborhood name is unique within the same district."""
        if self.neighborhood_name and self.district:
            existing = frappe.db.exists(
                "Neighborhood",
                {
                    "neighborhood_name": self.neighborhood_name,
                    "district": self.district,
                    "name": ["!=", self.name]
                }
            )
            if existing:
                frappe.throw(
                    _("Neighborhood '{0}' already exists in this district").format(self.neighborhood_name)
                )

    def on_trash(self):
        """Prevent deletion of neighborhood with linked addresses."""
        self.check_linked_documents()

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked address items
        if frappe.db.exists("Address Item", {"neighborhood": self.name}):
            frappe.throw(
                _("Cannot delete Neighborhood with linked Address Items. Please update addresses first.")
            )

    def get_district_info(self):
        """Get parent district information."""
        if self.district:
            return frappe.get_cached_doc("District", self.district)
        return None

    def get_city_info(self):
        """Get parent city information."""
        if self.city:
            return frappe.get_cached_doc("City", self.city)
        return None

    def get_full_address(self):
        """Get the full address hierarchy string."""
        parts = []
        if self.neighborhood_name:
            parts.append(self.neighborhood_name)
        if self.district_name:
            parts.append(self.district_name)
        if self.city_name:
            parts.append(self.city_name)
        return ", ".join(parts)


@frappe.whitelist()
def get_neighborhoods_by_district(district):
    """
    Get all neighborhoods in a specific district.

    Args:
        district: District name/code

    Returns:
        list: Neighborhoods in the specified district
    """
    if not district:
        return []

    return frappe.get_all(
        "Neighborhood",
        filters={"district": district, "is_active": 1},
        fields=["name", "neighborhood_code", "neighborhood_name", "postal_code"],
        order_by="neighborhood_name asc"
    )


@frappe.whitelist()
def get_neighborhoods_by_city(city):
    """
    Get all neighborhoods in a specific city (across all districts).

    Args:
        city: City name/code

    Returns:
        list: Neighborhoods in the specified city
    """
    if not city:
        return []

    return frappe.get_all(
        "Neighborhood",
        filters={"city": city, "is_active": 1},
        fields=["name", "neighborhood_code", "neighborhood_name", "district", "district_name", "postal_code"],
        order_by="neighborhood_name asc"
    )


@frappe.whitelist()
def get_active_neighborhoods():
    """
    Get all active neighborhoods.

    Returns:
        list: All active neighborhoods ordered by name
    """
    return frappe.get_all(
        "Neighborhood",
        filters={"is_active": 1},
        fields=["name", "neighborhood_code", "neighborhood_name", "district", "district_name", "city", "city_name"],
        order_by="neighborhood_name asc"
    )


@frappe.whitelist()
def search_neighborhoods(query, district=None, city=None):
    """
    Search neighborhoods by name or code, optionally filtered by district or city.

    Args:
        query: Search term
        district: Optional district to filter by
        city: Optional city to filter by

    Returns:
        list: Matching neighborhoods
    """
    if not query:
        return []

    filters = {"is_active": 1}
    if district:
        filters["district"] = district
    if city:
        filters["city"] = city

    return frappe.get_all(
        "Neighborhood",
        filters=filters,
        or_filters={
            "neighborhood_name": ["like", f"%{query}%"],
            "neighborhood_code": ["like", f"%{query}%"]
        },
        fields=["name", "neighborhood_code", "neighborhood_name", "district", "district_name", "city", "city_name"],
        order_by="neighborhood_name asc",
        limit=20
    )
