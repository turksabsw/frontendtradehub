# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PhoneCode(Document):
    """
    Phone Code (Alan Kodu) DocType for Turkish phone area codes.

    Represents phone area codes for Turkish cities. Some cities have multiple
    area codes (e.g., Istanbul has 212 for European side and 216 for Asian side).
    Each phone code is linked to a City and can be marked as primary for that city.
    """

    def validate(self):
        """Validate phone code data before saving."""
        self.validate_phone_code()
        self.validate_city()
        self.validate_unique_phone_code_description()
        self.validate_single_primary_per_city()

    def validate_phone_code(self):
        """Validate Turkish phone code format (3 digits)."""
        if self.phone_code:
            phone_code = self.phone_code.strip()

            # Must be numeric
            if not phone_code.isdigit():
                frappe.throw(_("Phone code must contain only digits"))

            # Must be 3 digits
            if len(phone_code) != 3:
                frappe.throw(_("Phone code must be a 3-digit number (e.g., 212, 312)"))

            # Must be in valid range (200-999 for Turkish area codes)
            code_int = int(phone_code)
            if code_int < 200 or code_int > 999:
                frappe.throw(_("Phone code must be between 200 and 999"))

            self.phone_code = phone_code

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

    def validate_unique_phone_code_description(self):
        """Ensure phone code + description combination is unique within the same city."""
        if self.phone_code and self.city:
            filters = {
                "phone_code": self.phone_code,
                "city": self.city,
                "name": ["!=", self.name]
            }
            # If description is set, add it to filters
            if self.description:
                filters["description"] = self.description

            existing = frappe.db.exists("Phone Code", filters)
            if existing:
                if self.description:
                    frappe.throw(
                        _("Phone code '{0}' with description '{1}' already exists for this city").format(
                            self.phone_code, self.description
                        )
                    )
                else:
                    frappe.throw(
                        _("Phone code '{0}' already exists for this city").format(self.phone_code)
                    )

    def validate_single_primary_per_city(self):
        """Ensure only one phone code can be primary per city."""
        if self.is_primary and self.city:
            existing_primary = frappe.db.exists(
                "Phone Code",
                {
                    "city": self.city,
                    "is_primary": 1,
                    "name": ["!=", self.name]
                }
            )
            if existing_primary:
                frappe.throw(
                    _("City already has a primary phone code. Please unmark the existing primary first.")
                )

    def on_trash(self):
        """Hook called before deleting the document."""
        # No linked documents to check for phone codes
        pass

    def get_city_info(self):
        """Get parent city information."""
        if self.city:
            return frappe.get_cached_doc("City", self.city)
        return None


@frappe.whitelist()
def get_phone_codes_by_city(city):
    """
    Get all phone codes for a specific city.

    Args:
        city: City code/name

    Returns:
        list: Phone codes for the specified city
    """
    if not city:
        return []

    return frappe.get_all(
        "Phone Code",
        filters={"city": city, "is_active": 1},
        fields=["name", "phone_code", "description", "is_primary"],
        order_by="is_primary desc, phone_code asc"
    )


@frappe.whitelist()
def get_primary_phone_code(city):
    """
    Get the primary phone code for a specific city.

    Args:
        city: City code/name

    Returns:
        dict: Primary phone code info or None
    """
    if not city:
        return None

    primary = frappe.get_all(
        "Phone Code",
        filters={"city": city, "is_active": 1, "is_primary": 1},
        fields=["name", "phone_code", "description"],
        limit=1
    )

    if primary:
        return primary[0]

    # If no primary set, return the first active phone code
    fallback = frappe.get_all(
        "Phone Code",
        filters={"city": city, "is_active": 1},
        fields=["name", "phone_code", "description"],
        order_by="phone_code asc",
        limit=1
    )

    return fallback[0] if fallback else None


@frappe.whitelist()
def get_active_phone_codes():
    """
    Get all active phone codes.

    Returns:
        list: All active phone codes ordered by code
    """
    return frappe.get_all(
        "Phone Code",
        filters={"is_active": 1},
        fields=["name", "phone_code", "description", "city", "city_name", "is_primary"],
        order_by="phone_code asc"
    )


@frappe.whitelist()
def search_phone_codes(query, city=None):
    """
    Search phone codes by code or description, optionally filtered by city.

    Args:
        query: Search term
        city: Optional city to filter by

    Returns:
        list: Matching phone codes
    """
    if not query:
        return []

    filters = {"is_active": 1}
    if city:
        filters["city"] = city

    return frappe.get_all(
        "Phone Code",
        filters=filters,
        or_filters={
            "phone_code": ["like", f"%{query}%"],
            "description": ["like", f"%{query}%"],
            "city_name": ["like", f"%{query}%"]
        },
        fields=["name", "phone_code", "description", "city", "city_name"],
        order_by="phone_code asc",
        limit=20
    )
