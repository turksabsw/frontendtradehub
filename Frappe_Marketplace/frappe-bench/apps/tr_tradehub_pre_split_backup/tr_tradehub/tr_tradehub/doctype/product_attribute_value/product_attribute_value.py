# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Product Attribute Value DocType for Trade Hub B2B Marketplace.

This module implements the Product Attribute Value DocType for defining
the possible values of product attributes (e.g., Red, Blue for Color;
S, M, L for Size). Values inherit tenant settings from their parent attribute.

Key Features:
- Links to parent Product Attribute with fetch_from pattern
- Color code support for color swatches
- Image support for visual swatches
- Abbreviation for compact display
- Multi-tenant isolation inherited from parent attribute
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class ProductAttributeValue(Document):
    """
    Product Attribute Value DocType for defining attribute values.

    Each attribute (Color, Size, etc.) can have multiple values. Values
    inherit tenant settings from their parent attribute for multi-tenant
    isolation.
    """

    def before_insert(self):
        """Set default values before inserting a new attribute value."""
        self.generate_value_code()
        self.validate_parent_attribute()

    def validate(self):
        """Validate attribute value data before saving."""
        self.validate_value_name()
        self.validate_parent_attribute()
        self.validate_uniqueness()
        self.validate_color_code()
        self.generate_value_code()

    def on_update(self):
        """Actions after attribute value is updated."""
        self.update_parent_value_count()
        self.clear_value_cache()

    def after_insert(self):
        """Actions after new value is inserted."""
        self.update_parent_value_count()

    def on_trash(self):
        """Actions before deletion."""
        self.update_parent_value_count()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def generate_value_code(self):
        """Generate value code from value name if not provided."""
        if not self.value_code and self.value_name:
            # Convert to uppercase and replace special characters
            code = self.value_name.upper()

            # Turkish character replacements
            turkish_map = {
                'I': 'I', 'G': 'G', 'U': 'U', 'S': 'S', 'O': 'O', 'C': 'C',
                'i': 'I', 'g': 'G', 'u': 'U', 's': 'S', 'o': 'O', 'c': 'C'
            }
            for tr_char, en_char in turkish_map.items():
                code = code.replace(tr_char, en_char)

            # Replace spaces and special chars with underscores
            code = re.sub(r'[^A-Z0-9_]', '_', code)
            # Remove consecutive underscores
            code = re.sub(r'_+', '_', code)
            # Remove leading/trailing underscores
            code = code.strip('_')

            # Limit length
            if len(code) > 20:
                code = code[:20]

            self.value_code = code

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_value_name(self):
        """Validate value name is not empty and follows naming conventions."""
        if not self.value_name:
            frappe.throw(_("Value Name is required"))

        # Check for invalid characters
        if any(char in self.value_name for char in ['<', '>', '"', '\\']):
            frappe.throw(_("Value Name contains invalid characters"))

        # Check length
        if len(self.value_name) > 140:
            frappe.throw(_("Value Name cannot exceed 140 characters"))

        # Trim whitespace
        self.value_name = self.value_name.strip()

    def validate_parent_attribute(self):
        """Validate parent attribute exists and check tenant permissions."""
        if not self.attribute:
            frappe.throw(_("Parent Attribute is required"))

        if not frappe.db.exists("Product Attribute", self.attribute):
            frappe.throw(_("Product Attribute {0} not found").format(self.attribute))

        # Get parent attribute
        parent_attr = frappe.get_doc("Product Attribute", self.attribute)

        # Validate tenant access
        if parent_attr.tenant and not parent_attr.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if parent_attr.tenant != user_tenant:
                if not frappe.has_permission("Tenant", "write"):
                    frappe.throw(_("Access denied: Cannot add values to this attribute"))

    def validate_uniqueness(self):
        """Validate value name is unique within the same attribute."""
        existing = frappe.db.exists(
            "Product Attribute Value",
            {
                "attribute": self.attribute,
                "value_name": self.value_name,
                "name": ("!=", self.name or "")
            }
        )
        if existing:
            frappe.throw(
                _("Value '{0}' already exists for attribute '{1}'").format(
                    self.value_name, self.attribute
                )
            )

    def validate_color_code(self):
        """Validate color code format if provided."""
        if self.color_code:
            # Ensure hex color format
            if not re.match(r'^#[0-9A-Fa-f]{6}$', self.color_code):
                # Try to fix common issues
                if re.match(r'^[0-9A-Fa-f]{6}$', self.color_code):
                    self.color_code = f"#{self.color_code}"
                elif re.match(r'^#[0-9A-Fa-f]{3}$', self.color_code):
                    # Expand 3-char to 6-char
                    c = self.color_code[1:]
                    self.color_code = f"#{c[0]}{c[0]}{c[1]}{c[1]}{c[2]}{c[2]}"
                else:
                    frappe.throw(
                        _("Color code must be in hex format (e.g., #FF0000)")
                    )

    # =========================================================================
    # PARENT ATTRIBUTE METHODS
    # =========================================================================

    def update_parent_value_count(self):
        """Update the value count in parent attribute."""
        if self.attribute and frappe.db.exists("Product Attribute", self.attribute):
            parent = frappe.get_doc("Product Attribute", self.attribute)
            parent.update_value_count()

    def get_parent_attribute(self):
        """
        Get the parent attribute document.

        Returns:
            Document: Parent Product Attribute document
        """
        if self.attribute:
            return frappe.get_doc("Product Attribute", self.attribute)
        return None

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_value_cache(self):
        """Clear cached value data."""
        cache_keys = [
            f"attribute_values:{self.attribute}",
            f"attribute_value:{self.name}"
        ]

        # Also clear parent tenant cache
        if self.tenant:
            cache_keys.append(f"attribute_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_values_for_attribute(attribute, include_disabled=False):
    """
    Get all values for a specific attribute.

    Args:
        attribute: Name of the parent attribute
        include_disabled: Include disabled values

    Returns:
        list: List of attribute value documents
    """
    if not frappe.db.exists("Product Attribute", attribute):
        frappe.throw(_("Attribute {0} not found").format(attribute))

    filters = {"attribute": attribute}
    if not include_disabled:
        filters["enabled"] = 1

    return frappe.get_all(
        "Product Attribute Value",
        filters=filters,
        fields=[
            "name", "value_name", "value_code", "color_code",
            "image", "abbreviation", "display_order", "enabled", "is_default"
        ],
        order_by="display_order asc, value_name asc"
    )


@frappe.whitelist()
def get_value_by_code(attribute, value_code):
    """
    Get attribute value by its code.

    Args:
        attribute: Name of the parent attribute
        value_code: Code of the value to find

    Returns:
        dict: Attribute value data
    """
    value = frappe.db.get_value(
        "Product Attribute Value",
        {"attribute": attribute, "value_code": value_code},
        ["name", "value_name", "value_code", "color_code",
         "image", "abbreviation", "enabled"],
        as_dict=True
    )

    if not value:
        frappe.throw(
            _("Value with code '{0}' not found in attribute '{1}'").format(
                value_code, attribute
            )
        )

    return value


@frappe.whitelist()
def set_default_value(value_name):
    """
    Set a value as the default for its attribute.

    Args:
        value_name: Name of the value to set as default

    Returns:
        dict: Updated value data
    """
    if not frappe.db.exists("Product Attribute Value", value_name):
        frappe.throw(_("Attribute Value {0} not found").format(value_name))

    value = frappe.get_doc("Product Attribute Value", value_name)

    # Clear existing default for this attribute
    frappe.db.sql("""
        UPDATE `tabProduct Attribute Value`
        SET is_default = 0
        WHERE attribute = %s AND name != %s
    """, (value.attribute, value.name))

    # Set this value as default
    value.is_default = 1
    value.save()

    return {
        "name": value.name,
        "value_name": value.value_name,
        "is_default": value.is_default
    }


@frappe.whitelist()
def create_standard_color_values():
    """
    Create standard color values for the Color attribute.
    Intended to be called during initial setup.

    Returns:
        dict: Created color values
    """
    # Check if Color attribute exists
    if not frappe.db.exists("Product Attribute", "Color"):
        frappe.throw(_("Color attribute must be created first"))

    standard_colors = [
        {"value_name": "Red", "color_code": "#FF0000", "display_order": 1},
        {"value_name": "Blue", "color_code": "#0000FF", "display_order": 2},
        {"value_name": "Green", "color_code": "#00FF00", "display_order": 3},
        {"value_name": "Black", "color_code": "#000000", "display_order": 4},
        {"value_name": "White", "color_code": "#FFFFFF", "display_order": 5},
        {"value_name": "Yellow", "color_code": "#FFFF00", "display_order": 6},
        {"value_name": "Orange", "color_code": "#FFA500", "display_order": 7},
        {"value_name": "Purple", "color_code": "#800080", "display_order": 8},
        {"value_name": "Pink", "color_code": "#FFC0CB", "display_order": 9},
        {"value_name": "Gray", "color_code": "#808080", "display_order": 10},
        {"value_name": "Brown", "color_code": "#8B4513", "display_order": 11},
        {"value_name": "Navy", "color_code": "#000080", "display_order": 12}
    ]

    created = []
    for color_data in standard_colors:
        existing = frappe.db.exists(
            "Product Attribute Value",
            {"attribute": "Color", "value_name": color_data["value_name"]}
        )
        if not existing:
            value = frappe.get_doc({
                "doctype": "Product Attribute Value",
                "attribute": "Color",
                **color_data
            })
            value.insert(ignore_permissions=True)
            created.append(value.name)

    frappe.db.commit()

    return {"created": created, "count": len(created)}


@frappe.whitelist()
def create_standard_size_values():
    """
    Create standard size values for the Size attribute.
    Intended to be called during initial setup.

    Returns:
        dict: Created size values
    """
    # Check if Size attribute exists
    if not frappe.db.exists("Product Attribute", "Size"):
        frappe.throw(_("Size attribute must be created first"))

    standard_sizes = [
        {"value_name": "XS", "abbreviation": "XS", "display_order": 1},
        {"value_name": "S", "abbreviation": "S", "display_order": 2},
        {"value_name": "M", "abbreviation": "M", "display_order": 3},
        {"value_name": "L", "abbreviation": "L", "display_order": 4},
        {"value_name": "XL", "abbreviation": "XL", "display_order": 5},
        {"value_name": "XXL", "abbreviation": "XXL", "display_order": 6},
        {"value_name": "XXXL", "abbreviation": "3XL", "display_order": 7}
    ]

    created = []
    for size_data in standard_sizes:
        existing = frappe.db.exists(
            "Product Attribute Value",
            {"attribute": "Size", "value_name": size_data["value_name"]}
        )
        if not existing:
            value = frappe.get_doc({
                "doctype": "Product Attribute Value",
                "attribute": "Size",
                **size_data
            })
            value.insert(ignore_permissions=True)
            created.append(value.name)

    frappe.db.commit()

    return {"created": created, "count": len(created)}


@frappe.whitelist()
def bulk_create_values(attribute, values):
    """
    Bulk create attribute values.

    Args:
        attribute: Name of the parent attribute
        values: List of value data dicts (value_name required, others optional)

    Returns:
        dict: Created values count and names
    """
    if not frappe.db.exists("Product Attribute", attribute):
        frappe.throw(_("Attribute {0} not found").format(attribute))

    # Parse values if string
    if isinstance(values, str):
        import json
        values = json.loads(values)

    created = []
    errors = []

    for idx, value_data in enumerate(values):
        try:
            value_name = value_data.get("value_name")
            if not value_name:
                errors.append(f"Row {idx + 1}: value_name is required")
                continue

            # Check for existing
            existing = frappe.db.exists(
                "Product Attribute Value",
                {"attribute": attribute, "value_name": value_name}
            )
            if existing:
                errors.append(f"Row {idx + 1}: '{value_name}' already exists")
                continue

            # Create value
            value = frappe.get_doc({
                "doctype": "Product Attribute Value",
                "attribute": attribute,
                "value_name": value_name,
                "value_code": value_data.get("value_code"),
                "color_code": value_data.get("color_code"),
                "abbreviation": value_data.get("abbreviation"),
                "display_order": value_data.get("display_order", idx * 10),
                "enabled": value_data.get("enabled", 1)
            })
            value.insert(ignore_permissions=True)
            created.append(value.name)

        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")

    frappe.db.commit()

    return {
        "created": created,
        "count": len(created),
        "errors": errors if errors else None
    }
