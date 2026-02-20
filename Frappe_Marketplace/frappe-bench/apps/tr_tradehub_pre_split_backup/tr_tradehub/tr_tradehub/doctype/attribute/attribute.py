# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class Attribute(Document):
    """
    Attribute DocType for TR-TradeHub marketplace product specifications.

    Attributes define product characteristics that can be:
    - Used for variant creation (Size, Color)
    - Used for filtering in search
    - Used for product comparisons
    - Required or optional based on category
    """

    def before_insert(self):
        """Actions before inserting a new attribute."""
        self.set_defaults()

    def validate(self):
        """Validate attribute data before saving."""
        self.validate_attribute_name()
        self.validate_attribute_type()
        self.validate_attribute_values()
        self.validate_numeric_settings()

    def on_update(self):
        """Actions after attribute is updated."""
        self.clear_attribute_cache()

    def on_trash(self):
        """Prevent deletion of attribute if in use."""
        self.check_usage()

    def set_defaults(self):
        """Set default values for attribute."""
        if not self.attribute_label:
            self.attribute_label = self.attribute_name

    def validate_attribute_name(self):
        """Validate attribute name format."""
        if not self.attribute_name:
            frappe.throw(_("Attribute Name is required"))

        # Check for special characters
        if not self.attribute_name.replace(" ", "").replace("-", "").replace("_", "").isalnum():
            frappe.throw(_("Attribute Name can only contain letters, numbers, spaces, hyphens, and underscores"))

    def validate_attribute_type(self):
        """Validate attribute type and related settings."""
        valid_types = ["Select", "Text", "Numeric", "Boolean", "Date", "Color"]
        if self.attribute_type not in valid_types:
            frappe.throw(_("Invalid Attribute Type. Must be one of: {0}").format(", ".join(valid_types)))

        # Variant attributes must be Select or Color type
        if self.is_variant and self.attribute_type not in ["Select", "Color"]:
            frappe.throw(_("Variant attributes must be of type 'Select' or 'Color'"))

    def validate_attribute_values(self):
        """Validate attribute values for Select/Color types."""
        if self.attribute_type in ["Select", "Color"]:
            if not self.attribute_values or len(self.attribute_values) == 0:
                frappe.throw(_("Attribute Values are required for {0} type attributes").format(self.attribute_type))

            # Check for duplicate values
            values = [v.attribute_value for v in self.attribute_values]
            if len(values) != len(set(values)):
                frappe.throw(_("Duplicate attribute values are not allowed"))

            # Validate color codes for Color type
            if self.attribute_type == "Color":
                for value in self.attribute_values:
                    if value.color_code and not self.is_valid_color_code(value.color_code):
                        frappe.throw(_("Invalid color code: {0}. Must be a valid hex color (e.g., #FF0000)").format(value.color_code))

    def validate_numeric_settings(self):
        """Validate numeric attribute settings."""
        if self.attribute_type == "Numeric":
            if self.numeric_min is not None and self.numeric_max is not None:
                if flt(self.numeric_min) > flt(self.numeric_max):
                    frappe.throw(_("Minimum value cannot be greater than maximum value"))

            if self.numeric_step and flt(self.numeric_step) <= 0:
                frappe.throw(_("Step value must be greater than zero"))

    def is_valid_color_code(self, color_code):
        """Check if color code is a valid hex color."""
        if not color_code:
            return True

        color_code = color_code.strip()
        if not color_code.startswith("#"):
            return False

        hex_part = color_code[1:]
        if len(hex_part) not in [3, 6]:
            return False

        try:
            int(hex_part, 16)
            return True
        except ValueError:
            return False

    def clear_attribute_cache(self):
        """Clear cached attribute data."""
        frappe.cache().delete_value("all_attributes")
        frappe.cache().delete_value(f"attribute:{self.name}")

    def check_usage(self):
        """Check if attribute is used in any attribute sets."""
        usage_count = frappe.db.count("Attribute Set Item", {"attribute": self.name})
        if usage_count:
            frappe.throw(
                _("Cannot delete Attribute '{0}' as it is used in {1} Attribute Set(s). "
                  "Remove it from Attribute Sets first.").format(self.name, usage_count)
            )

    def get_values_list(self):
        """Get list of attribute values."""
        if self.attribute_type in ["Select", "Color"]:
            return [v.attribute_value for v in self.attribute_values if v.is_active]
        return []

    def get_display_values(self):
        """Get list of display values with their codes."""
        if self.attribute_type in ["Select", "Color"]:
            return [
                {
                    "value": v.attribute_value,
                    "display": v.display_value or v.attribute_value,
                    "abbreviation": v.abbreviation,
                    "color_code": v.color_code,
                    "image": v.image
                }
                for v in self.attribute_values
                if v.is_active
            ]
        return []

    def validate_value(self, value):
        """
        Validate a value against this attribute's constraints.

        Args:
            value: The value to validate

        Returns:
            tuple: (is_valid, error_message)
        """
        if not self.is_active:
            return False, _("Attribute is not active")

        if self.attribute_type == "Select":
            valid_values = self.get_values_list()
            if value not in valid_values:
                return False, _("'{0}' is not a valid value for {1}. Valid values: {2}").format(
                    value, self.attribute_name, ", ".join(valid_values)
                )

        elif self.attribute_type == "Color":
            valid_values = self.get_values_list()
            if value not in valid_values:
                return False, _("'{0}' is not a valid color for {1}").format(value, self.attribute_name)

        elif self.attribute_type == "Numeric":
            try:
                num_value = flt(value)
                if self.numeric_min is not None and num_value < flt(self.numeric_min):
                    return False, _("Value must be at least {0}").format(self.numeric_min)
                if self.numeric_max is not None and num_value > flt(self.numeric_max):
                    return False, _("Value must be at most {0}").format(self.numeric_max)
            except (ValueError, TypeError):
                return False, _("Value must be a number")

        elif self.attribute_type == "Boolean":
            if value not in [True, False, 1, 0, "1", "0", "true", "false", "True", "False"]:
                return False, _("Value must be a boolean")

        elif self.attribute_type == "Date":
            try:
                from frappe.utils import getdate
                getdate(value)
            except Exception:
                return False, _("Value must be a valid date")

        return True, None


@frappe.whitelist()
def get_attribute_values(attribute_name):
    """
    Get all values for an attribute.

    Args:
        attribute_name: Name of the attribute

    Returns:
        list: List of attribute value dictionaries
    """
    if not frappe.has_permission("Attribute", "read"):
        frappe.throw(_("Not permitted"))

    attribute = frappe.get_doc("Attribute", attribute_name)
    return attribute.get_display_values()


@frappe.whitelist()
def get_filterable_attributes(category=None):
    """
    Get all filterable attributes, optionally filtered by category.

    Args:
        category: Optional category name to filter by attribute set

    Returns:
        list: List of filterable attributes with their values
    """
    filters = {"is_active": 1, "is_filterable": 1}

    if category:
        # Get attribute set for category
        attribute_set = frappe.db.get_value("Category", category, "attribute_set")
        if attribute_set:
            # Get attributes from attribute set
            attribute_names = frappe.get_all(
                "Attribute Set Item",
                filters={"parent": attribute_set},
                pluck="attribute"
            )
            if attribute_names:
                filters["name"] = ["in", attribute_names]

    attributes = frappe.get_all(
        "Attribute",
        filters=filters,
        fields=["name", "attribute_name", "attribute_label", "attribute_type", "icon"],
        order_by="display_order asc"
    )

    # Add values for each attribute
    for attr in attributes:
        attr_doc = frappe.get_doc("Attribute", attr.name)
        attr["values"] = attr_doc.get_display_values()

    return attributes


@frappe.whitelist()
def get_variant_attributes():
    """
    Get all attributes that can be used for variants.

    Returns:
        list: List of variant attributes with their values
    """
    attributes = frappe.get_all(
        "Attribute",
        filters={"is_active": 1, "is_variant": 1},
        fields=["name", "attribute_name", "attribute_label", "attribute_type", "icon"],
        order_by="display_order asc"
    )

    # Add values for each attribute
    for attr in attributes:
        attr_doc = frappe.get_doc("Attribute", attr.name)
        attr["values"] = attr_doc.get_display_values()

    return attributes
