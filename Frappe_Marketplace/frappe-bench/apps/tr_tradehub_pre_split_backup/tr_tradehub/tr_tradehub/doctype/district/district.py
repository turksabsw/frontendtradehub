# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class District(Document):
    """
    District (Ilce) DocType for Turkish districts.

    Represents districts within Turkish provinces. Each district belongs to a single
    city (province) and can contain multiple neighborhoods. Used as the middle level
    of the address hierarchy: City -> District -> Neighborhood
    """

    def validate(self):
        """Validate district data before saving."""
        self.validate_district_name()
        self.validate_city()
        self.validate_unique_district_in_city()

    def validate_district_name(self):
        """Validate district name is not empty and properly formatted."""
        if self.district_name:
            self.district_name = self.district_name.strip()
            if len(self.district_name) < 2:
                frappe.throw(_("District name must be at least 2 characters"))

    def validate_city(self):
        """Validate that the linked city exists and is active."""
        if self.city:
            city_doc = frappe.get_cached_doc("City", self.city)
            if not city_doc.is_active:
                frappe.throw(
                    _("Cannot link to inactive City '{0}'. Please select an active city.").format(
                        city_doc.city_name
                    )
                )

    def validate_unique_district_in_city(self):
        """Ensure district name is unique within the same city."""
        if self.district_name and self.city:
            existing = frappe.db.exists(
                "District",
                {
                    "district_name": self.district_name,
                    "city": self.city,
                    "name": ["!=", self.name]
                }
            )
            if existing:
                frappe.throw(
                    _("District '{0}' already exists in this city").format(self.district_name)
                )

    def on_trash(self):
        """Prevent deletion of district with linked neighborhoods."""
        self.check_linked_documents()

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked neighborhoods
        if frappe.db.exists("Neighborhood", {"district": self.name}):
            frappe.throw(
                _("Cannot delete District with linked Neighborhoods. Please delete all Neighborhoods in this district first.")
            )

    def get_neighborhood_count(self):
        """Get count of neighborhoods for this district."""
        return frappe.db.count("Neighborhood", {"district": self.name})

    def get_neighborhoods(self):
        """Get all neighborhoods for this district."""
        return frappe.get_all(
            "Neighborhood",
            filters={"district": self.name},
            fields=["name", "neighborhood_name", "neighborhood_code"],
            order_by="neighborhood_name asc"
        )

    def get_city_info(self):
        """Get parent city information."""
        if self.city:
            return frappe.get_cached_doc("City", self.city)
        return None


@frappe.whitelist()
def get_districts_by_city(city):
    """
    Get all districts in a specific city.

    Args:
        city: City code/name

    Returns:
        list: Districts in the specified city
    """
    if not city:
        return []

    return frappe.get_all(
        "District",
        filters={"city": city, "is_active": 1},
        fields=["name", "district_code", "district_name", "postal_code_prefix"],
        order_by="district_name asc"
    )


@frappe.whitelist()
def get_active_districts():
    """
    Get all active districts.

    Returns:
        list: All active districts ordered by name
    """
    return frappe.get_all(
        "District",
        filters={"is_active": 1},
        fields=["name", "district_code", "district_name", "city", "city_name"],
        order_by="district_name asc"
    )


@frappe.whitelist()
def search_districts(query, city=None):
    """
    Search districts by name or code, optionally filtered by city.

    Args:
        query: Search term
        city: Optional city to filter by

    Returns:
        list: Matching districts
    """
    if not query:
        return []

    filters = {"is_active": 1}
    if city:
        filters["city"] = city

    return frappe.get_all(
        "District",
        filters=filters,
        or_filters={
            "district_name": ["like", f"%{query}%"],
            "district_code": ["like", f"%{query}%"]
        },
        fields=["name", "district_code", "district_name", "city", "city_name"],
        order_by="district_name asc",
        limit=20
    )
