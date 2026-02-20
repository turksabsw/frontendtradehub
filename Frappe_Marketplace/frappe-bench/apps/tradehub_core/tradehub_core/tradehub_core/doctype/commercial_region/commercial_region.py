# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CommercialRegion(Document):
    """
    Commercial Region DocType for geographic business regions in TR-TradeHub marketplace.

    Commercial regions group cities and districts for business purposes such as:
    - Regional shipping zones and delivery planning
    - Regional pricing and commission structures
    - Regional sales reporting and analytics
    - Territory assignment for sales teams
    """

    def validate(self):
        """Validate commercial region data before saving."""
        self.validate_region_code()
        self.validate_sort_order()

    def validate_region_code(self):
        """Validate and normalize region code."""
        if self.region_code:
            # Normalize region code to uppercase
            self.region_code = self.region_code.strip().upper()

            # Check for valid characters (alphanumeric and underscore only)
            if not self.region_code.replace("_", "").isalnum():
                frappe.throw(_("Region Code can only contain letters, numbers, and underscores"))

    def validate_sort_order(self):
        """Validate sort order is non-negative."""
        if self.sort_order and self.sort_order < 0:
            frappe.throw(_("Sort Order cannot be negative"))

    def on_trash(self):
        """Check for linked documents before deletion."""
        self.check_linked_cities()

    def check_linked_cities(self):
        """Check if any cities are linked to this commercial region."""
        # Check if City DocType has a commercial_region field
        if frappe.db.exists("DocType", "City"):
            city_meta = frappe.get_meta("City")
            if city_meta.has_field("commercial_region"):
                linked_cities = frappe.db.count("City", {"commercial_region": self.name})
                if linked_cities > 0:
                    frappe.throw(
                        _("Cannot delete Commercial Region with {0} linked cities. Please update or remove the city associations first.").format(linked_cities)
                    )


@frappe.whitelist()
def get_active_regions():
    """
    Get list of active commercial regions.

    Returns:
        list: List of active commercial regions with code and name
    """
    return frappe.get_all(
        "Commercial Region",
        filters={"is_active": 1},
        fields=["region_code", "region_name", "region_name_tr"],
        order_by="sort_order asc, region_name asc"
    )


@frappe.whitelist()
def get_regions_by_country(country="Turkey"):
    """
    Get commercial regions for a specific country.

    Args:
        country: Country name (default: Turkey)

    Returns:
        list: List of commercial regions for the country
    """
    return frappe.get_all(
        "Commercial Region",
        filters={"country": country, "is_active": 1},
        fields=["region_code", "region_name", "region_name_tr", "coverage_cities"],
        order_by="sort_order asc, region_name asc"
    )


@frappe.whitelist()
def search_regions(search_term):
    """
    Search commercial regions by name or code.

    Args:
        search_term: Search term to match against region name or code

    Returns:
        list: Matching commercial regions
    """
    if not search_term:
        return []

    search_term = f"%{search_term}%"

    # Try with is_active filter first, fall back if column doesn't exist
    try:
        return frappe.db.sql(
            """
            SELECT region_code, region_name, region_name_tr
            FROM `tabCommercial Region`
            WHERE is_active = 1
            AND (
                region_code LIKE %(search)s
                OR region_name LIKE %(search)s
                OR region_name_tr LIKE %(search)s
            )
            ORDER BY sort_order ASC, region_name ASC
            LIMIT 20
            """,
            {"search": search_term},
            as_dict=True
        )
    except Exception as e:
        # Column might not exist, try without is_active filter
        if "is_active" in str(e).lower() or "Unknown column" in str(e):
            return frappe.db.sql(
                """
                SELECT region_code, region_name, region_name_tr
                FROM `tabCommercial Region`
                WHERE (
                    region_code LIKE %(search)s
                    OR region_name LIKE %(search)s
                    OR region_name_tr LIKE %(search)s
                )
                ORDER BY sort_order ASC, region_name ASC
                LIMIT 20
                """,
                {"search": search_term},
                as_dict=True
            )
        else:
            # Re-raise if it's a different error
            raise
