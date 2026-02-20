# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document


class PIMAttribute(Document):
    """
    PIM Attribute DocType

    Defines product attributes with support for 20+ data types, localization,
    scoping, and marketplace integration flags. Used by Product Families to
    define the attribute schema for products.

    Attribute Types:
    - Text types: Text, Long Text, HTML
    - Numeric types: Int, Float, Currency, Percent, Rating
    - Boolean: Check
    - Selection: Select, Multiselect, Color, Size
    - Date types: Date, Datetime
    - Reference: Link
    - Media: Image, File
    - Special: Measurement, URL, JSON, Table
    """

    def validate(self):
        """Validate the document before saving"""
        self.validate_attribute_code()
        self.validate_type_specific_config()
        self.validate_options()
        self.set_defaults()

    def validate_attribute_code(self):
        """Ensure attribute_code is lowercase and contains only valid characters"""
        if self.attribute_code:
            # Convert to lowercase and replace spaces with underscores
            self.attribute_code = self.attribute_code.lower().replace(" ", "_").replace("-", "_")

            # Check for valid characters (alphanumeric and underscore only)
            if not re.match(r'^[a-z][a-z0-9_]*$', self.attribute_code):
                frappe.throw(
                    _("Attribute Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                    title=_("Invalid Attribute Code")
                )

            # Check minimum length
            if len(self.attribute_code) < 2:
                frappe.throw(
                    _("Attribute Code must be at least 2 characters long"),
                    title=_("Invalid Attribute Code")
                )

    def validate_type_specific_config(self):
        """Validate type-specific configuration fields"""
        # Validate Link type configuration
        if self.attribute_type == "Link":
            if not self.link_doctype:
                frappe.throw(
                    _("Link DocType is required for Link type attributes"),
                    title=_("Missing Configuration")
                )
            # Verify the DocType exists
            if not frappe.db.exists("DocType", self.link_doctype):
                frappe.throw(
                    _("Link DocType '{0}' does not exist").format(self.link_doctype),
                    title=_("Invalid DocType")
                )

        # Validate JSON in link_filters
        if self.link_filters:
            try:
                import json
                json.loads(self.link_filters)
            except (json.JSONDecodeError, ValueError):
                frappe.throw(
                    _("Link Filters must be valid JSON"),
                    title=_("Invalid JSON")
                )

        # Validate numeric constraints
        if self.attribute_type in ["Int", "Float", "Currency", "Percent", "Rating"]:
            if self.min_value is not None and self.max_value is not None:
                if self.min_value > self.max_value:
                    frappe.throw(
                        _("Minimum value cannot be greater than maximum value"),
                        title=_("Invalid Range")
                    )

        # Validate Rating type
        if self.attribute_type == "Rating":
            if self.max_value is None:
                self.max_value = 5  # Default max rating
            if self.min_value is None:
                self.min_value = 0

        # Validate Percent type
        if self.attribute_type == "Percent":
            if self.max_value is None:
                self.max_value = 100
            if self.min_value is None:
                self.min_value = 0

        # Validate measurement unit
        if self.attribute_type == "Measurement" and not self.measurement_unit:
            frappe.msgprint(
                _("Consider specifying a measurement unit for this attribute"),
                indicator="yellow"
            )

        # Validate file extensions format
        if self.allowed_extensions:
            # Normalize extensions (remove dots, lowercase)
            extensions = [ext.strip().lower().lstrip('.') for ext in self.allowed_extensions.split(',')]
            self.allowed_extensions = ','.join(extensions)

    def validate_options(self):
        """Validate options for Select/Multiselect types"""
        if self.attribute_type in ["Select", "Multiselect", "Color", "Size"]:
            if not self.options or len(self.options) == 0:
                frappe.msgprint(
                    _("Consider adding options for this {0} type attribute").format(self.attribute_type),
                    indicator="yellow"
                )
            else:
                # Check for duplicate option values
                option_values = [opt.option_value for opt in self.options]
                if len(option_values) != len(set(option_values)):
                    frappe.throw(
                        _("Option values must be unique"),
                        title=_("Duplicate Options")
                    )

    def set_defaults(self):
        """Set default values if not provided"""
        if self.is_active is None:
            self.is_active = 1

        if self.attribute_type == "Rating":
            if self.max_value is None:
                self.max_value = 5
            if self.min_value is None:
                self.min_value = 0

        if self.attribute_type in ["Currency", "Measurement", "Float", "Percent"]:
            if self.attribute_type == "Currency" and self.currency_precision is None:
                self.currency_precision = 2
            if self.attribute_type == "Measurement" and self.measurement_precision is None:
                self.measurement_precision = 2

    def before_rename(self, old_name, new_name, merge=False):
        """Handle rename operations"""
        if merge:
            frappe.throw(
                _("Cannot merge PIM Attributes"),
                title=_("Merge Not Allowed")
            )

        if self.is_system:
            frappe.throw(
                _("Cannot rename system attributes"),
                title=_("Operation Not Allowed")
            )

    def on_trash(self):
        """Prevent deletion of system attributes"""
        if self.is_system:
            frappe.throw(
                _("Cannot delete system attributes"),
                title=_("Operation Not Allowed")
            )

    def get_frappe_fieldtype(self):
        """
        Map PIM Attribute type to Frappe fieldtype for dynamic form generation

        Returns:
            str: The corresponding Frappe fieldtype
        """
        type_mapping = {
            "Text": "Data",
            "Long Text": "Text",
            "HTML": "Text Editor",
            "Int": "Int",
            "Float": "Float",
            "Currency": "Currency",
            "Check": "Check",
            "Select": "Select",
            "Multiselect": "Table MultiSelect",
            "Color": "Color",
            "Size": "Select",
            "Date": "Date",
            "Datetime": "Datetime",
            "Link": "Link",
            "Image": "Attach Image",
            "File": "Attach",
            "Measurement": "Float",
            "URL": "Data",
            "JSON": "Code",
            "Table": "Table",
            "Rating": "Rating",
            "Percent": "Percent"
        }
        return type_mapping.get(self.attribute_type, "Data")

    def get_field_options(self):
        """
        Get options string for Select/Multiselect types

        Returns:
            str: Newline-separated options or empty string
        """
        if self.attribute_type in ["Select", "Multiselect", "Color", "Size"] and self.options:
            return "\n".join([opt.option_value for opt in self.options])
        return ""

    def get_validation_dict(self):
        """
        Get validation configuration as dictionary

        Returns:
            dict: Validation rules for this attribute
        """
        validation = {}

        if self.is_required:
            validation["reqd"] = 1

        if self.is_unique:
            validation["unique"] = 1

        if self.min_value is not None:
            validation["min_value"] = self.min_value

        if self.max_value is not None:
            validation["max_value"] = self.max_value

        if self.validation_regex:
            validation["regex"] = self.validation_regex
            validation["regex_message"] = self.validation_message or _("Invalid value format")

        return validation
