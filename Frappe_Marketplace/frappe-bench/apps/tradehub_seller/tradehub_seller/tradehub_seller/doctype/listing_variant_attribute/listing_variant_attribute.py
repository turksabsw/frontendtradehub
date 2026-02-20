# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ListingVariantAttribute(Document):
    """
    Child table for Listing Variant to store attribute values.

    Each row represents a single attribute-value pair that defines
    part of the variant (e.g., Color=Red, Size=XL).
    """

    def validate(self):
        """Validate attribute value."""
        self.validate_attribute_value()

    def validate_attribute_value(self):
        """Validate that the attribute value is valid for the attribute type."""
        if not self.attribute:
            return

        attribute = frappe.get_cached_doc("Attribute", self.attribute)

        if attribute.attribute_type == "Select":
            # Validate against predefined values
            valid_values = [av.attribute_value for av in attribute.attribute_values]
            if self.attribute_value not in valid_values:
                frappe.throw(
                    frappe._(
                        "Value '{0}' is not valid for attribute '{1}'. "
                        "Valid values are: {2}"
                    ).format(
                        self.attribute_value,
                        attribute.attribute_name,
                        ", ".join(valid_values)
                    )
                )

        elif attribute.attribute_type == "Color":
            # Validate against predefined color values
            valid_values = [av.attribute_value for av in attribute.attribute_values]
            if valid_values and self.attribute_value not in valid_values:
                frappe.throw(
                    frappe._(
                        "Color '{0}' is not valid for attribute '{1}'. "
                        "Valid colors are: {2}"
                    ).format(
                        self.attribute_value,
                        attribute.attribute_name,
                        ", ".join(valid_values)
                    )
                )

            # Set color code from predefined value if not set
            if not self.color_code:
                for av in attribute.attribute_values:
                    if av.attribute_value == self.attribute_value:
                        self.color_code = av.color_code
                        break

        elif attribute.attribute_type == "Numeric":
            # Validate numeric range
            try:
                value = float(self.attribute_value)
            except (ValueError, TypeError):
                frappe.throw(
                    frappe._(
                        "Attribute '{0}' requires a numeric value"
                    ).format(attribute.attribute_name)
                )

            if attribute.numeric_min and value < attribute.numeric_min:
                frappe.throw(
                    frappe._(
                        "Value {0} is below minimum {1} for attribute '{2}'"
                    ).format(value, attribute.numeric_min, attribute.attribute_name)
                )

            if attribute.numeric_max and value > attribute.numeric_max:
                frappe.throw(
                    frappe._(
                        "Value {0} is above maximum {1} for attribute '{2}'"
                    ).format(value, attribute.numeric_max, attribute.attribute_name)
                )

        elif attribute.attribute_type == "Boolean":
            # Validate boolean values
            valid_bools = ["Yes", "No", "True", "False", "1", "0"]
            if self.attribute_value not in valid_bools:
                frappe.throw(
                    frappe._(
                        "Attribute '{0}' requires a boolean value (Yes/No)"
                    ).format(attribute.attribute_name)
                )

    def get_display_value(self):
        """Get the display value for this attribute."""
        if self.display_value:
            return self.display_value
        return self.attribute_value
