# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Mock Field Mapping - DocType Controller

This module provides the controller for Mock Field Mapping, which defines
custom field generation rules based on field name patterns. Mappings can
specify how to generate data for fields matching certain patterns using
various generator types (Faker, Fixed Value, Pattern, Range, Turkish
Validators, LLM, or Custom Functions).

Mappings are evaluated in priority order (lower numbers first) and the
first matching mapping is used to generate the field value.
"""

import json
import re
from typing import Any, Optional

import frappe
from frappe import _
from frappe.model.document import Document


class MockFieldMapping(Document):
    """
    Controller for Mock Field Mapping DocType.

    Manages custom field generation rules based on field name patterns
    with support for multiple generator types and matching strategies.
    """

    def validate(self):
        """Validate the mapping before save."""
        self.validate_mapping_name()
        self.validate_priority()
        self.validate_field_pattern()
        self.validate_generator_config()
        self.validate_json_fields()

    def validate_mapping_name(self):
        """Ensure mapping name is properly formatted."""
        if self.mapping_name:
            self.mapping_name = self.mapping_name.strip()
            if not self.mapping_name:
                frappe.throw(_("Mapping Name cannot be empty"))

    def validate_priority(self):
        """Validate priority is within acceptable range."""
        if self.priority is not None:
            if self.priority < 1 or self.priority > 1000:
                frappe.throw(
                    _("Priority must be between 1 and 1000. "
                      "Lower numbers indicate higher priority."),
                    title=_("Invalid Priority")
                )

    def validate_field_pattern(self):
        """Validate field pattern based on match type."""
        if not self.field_pattern:
            frappe.throw(_("Field Pattern is required"))

        self.field_pattern = self.field_pattern.strip()

        # Validate regex pattern if match type is Regex
        if self.match_type == "Regex":
            try:
                re.compile(self.field_pattern)
            except re.error as e:
                frappe.throw(
                    _("Invalid regex pattern: {0}").format(str(e)),
                    title=_("Regex Error")
                )

    def validate_generator_config(self):
        """Validate generator-specific configuration."""
        if self.generator_type == "Faker":
            if not self.faker_provider or not self.faker_method:
                frappe.throw(
                    _("Faker Provider and Faker Method are required for Faker generator type."),
                    title=_("Missing Faker Configuration")
                )

        elif self.generator_type == "Fixed Value":
            if self.fixed_value is None or self.fixed_value == "":
                frappe.throw(
                    _("Fixed Value is required for Fixed Value generator type."),
                    title=_("Missing Fixed Value")
                )

        elif self.generator_type == "Pattern":
            if not self.pattern_template:
                frappe.throw(
                    _("Pattern Template is required for Pattern generator type."),
                    title=_("Missing Pattern Template")
                )

        elif self.generator_type == "Range":
            if self.min_value is None or self.max_value is None:
                frappe.throw(
                    _("Both Minimum and Maximum values are required for Range generator type."),
                    title=_("Missing Range Values")
                )
            if self.min_value > self.max_value:
                frappe.throw(
                    _("Minimum value cannot be greater than Maximum value."),
                    title=_("Invalid Range")
                )

        elif self.generator_type == "LLM":
            if not self.llm_prompt:
                frappe.throw(
                    _("LLM Prompt is required for LLM generator type."),
                    title=_("Missing LLM Prompt")
                )

        elif self.generator_type == "Custom Function":
            if not self.custom_function:
                frappe.throw(
                    _("Custom Function path is required for Custom Function generator type."),
                    title=_("Missing Custom Function")
                )
            # Validate function path format
            if not self._is_valid_function_path(self.custom_function):
                frappe.throw(
                    _("Custom Function must be a valid Python function path "
                      "(e.g., 'module.submodule.function_name')."),
                    title=_("Invalid Function Path")
                )

    def _is_valid_function_path(self, path: str) -> bool:
        """Check if the function path is a valid Python dotted path."""
        if not path:
            return False
        parts = path.split(".")
        return all(part.isidentifier() for part in parts) and len(parts) >= 2

    def validate_json_fields(self):
        """Validate JSON field contents."""
        # Validate faker_args
        if self.faker_args:
            try:
                json.loads(self.faker_args)
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Faker Arguments must be valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

        # Validate pattern_variables
        if self.pattern_variables:
            try:
                json.loads(self.pattern_variables)
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Pattern Variables must be valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

        # Validate validation_regex
        if self.validation_regex:
            try:
                re.compile(self.validation_regex)
            except re.error as e:
                frappe.throw(
                    _("Validation Regex is invalid: {0}").format(str(e)),
                    title=_("Invalid Regex")
                )

    def matches_field(self, fieldname: str, fieldtype: str = None, doctype: str = None) -> bool:
        """
        Check if this mapping matches the given field.

        Args:
            fieldname: The name of the field to check.
            fieldtype: The Frappe field type (optional).
            doctype: The DocType name (optional).

        Returns:
            bool: True if the mapping matches the field.
        """
        if not self.enabled:
            return False

        # Check field type filter
        if self.field_types and fieldtype:
            allowed_types = [ft.strip() for ft in self.field_types.split(",")]
            if fieldtype not in allowed_types:
                return False

        # Check doctype filter
        if self.target_doctypes and doctype:
            allowed_doctypes = [dt.strip() for dt in self.target_doctypes.split(",") if dt.strip()]
            if doctype not in allowed_doctypes:
                return False

        # Check field name pattern
        return self._matches_pattern(fieldname)

    def _matches_pattern(self, fieldname: str) -> bool:
        """
        Check if the fieldname matches the field pattern based on match type.

        Args:
            fieldname: The field name to check.

        Returns:
            bool: True if the fieldname matches the pattern.
        """
        pattern = self.field_pattern.lower()
        name = fieldname.lower()

        if self.match_type == "Exact":
            return name == pattern

        elif self.match_type == "Contains":
            return pattern in name

        elif self.match_type == "Starts With":
            return name.startswith(pattern)

        elif self.match_type == "Ends With":
            return name.endswith(pattern)

        elif self.match_type == "Regex":
            try:
                return bool(re.search(self.field_pattern, fieldname, re.IGNORECASE))
            except re.error:
                return False

        return False

    def get_generator_config(self) -> dict:
        """
        Get the generator configuration for this mapping.

        Returns:
            dict: Generator configuration including type and all relevant settings.
        """
        config = {
            "type": self.generator_type,
            "mapping_name": self.mapping_name,
            "priority": self.priority,
            "fallback_value": self.fallback_value,
            "validation_regex": self.validation_regex,
        }

        if self.generator_type == "Faker":
            config.update({
                "provider": self.faker_provider,
                "method": self.faker_method,
                "locale": self.faker_locale,
                "args": self._parse_json(self.faker_args) or {},
            })

        elif self.generator_type == "Fixed Value":
            config.update({
                "value": self._convert_fixed_value(),
                "value_type": self.fixed_value_type,
            })

        elif self.generator_type == "Pattern":
            config.update({
                "template": self.pattern_template,
                "variables": self._parse_json(self.pattern_variables) or {},
            })

        elif self.generator_type == "Range":
            config.update({
                "min": self.min_value,
                "max": self.max_value,
                "decimal_places": self.decimal_places or 0,
            })

        elif self.generator_type == "Select Options":
            # Uses the field's own options
            config.update({
                "use_field_options": True,
            })

        elif self.generator_type == "Turkish Validator":
            config.update({
                "turkish_type": self.turkish_type,
            })

        elif self.generator_type == "LLM":
            config.update({
                "prompt": self.llm_prompt,
                "context_fields": [
                    f.strip()
                    for f in (self.llm_context_fields or "").split(",")
                    if f.strip()
                ],
            })

        elif self.generator_type == "Custom Function":
            config.update({
                "function_path": self.custom_function,
            })

        return config

    def _parse_json(self, json_str: str) -> Optional[Any]:
        """Safely parse a JSON string."""
        if not json_str:
            return None
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    def _convert_fixed_value(self) -> Any:
        """Convert fixed value based on fixed_value_type."""
        if not self.fixed_value:
            return None

        try:
            if self.fixed_value_type == "Integer":
                return int(self.fixed_value)
            elif self.fixed_value_type == "Float":
                return float(self.fixed_value)
            elif self.fixed_value_type == "Boolean":
                return self.fixed_value.lower() in ("true", "1", "yes")
            elif self.fixed_value_type == "JSON":
                return json.loads(self.fixed_value)
            else:  # String
                return self.fixed_value
        except (ValueError, json.JSONDecodeError):
            return self.fixed_value

    @staticmethod
    def get_matching_mapping(
        fieldname: str,
        fieldtype: str = None,
        doctype: str = None
    ) -> Optional["MockFieldMapping"]:
        """
        Find the first matching field mapping for the given field.

        Mappings are checked in priority order (ascending - lower numbers first).

        Args:
            fieldname: The name of the field.
            fieldtype: The Frappe field type (optional).
            doctype: The DocType name (optional).

        Returns:
            MockFieldMapping or None: The first matching mapping, or None if no match.
        """
        # Get all enabled mappings sorted by priority
        mappings = frappe.get_all(
            "Mock Field Mapping",
            filters={"enabled": 1},
            fields=["name"],
            order_by="priority ASC"
        )

        for mapping_ref in mappings:
            mapping = frappe.get_doc("Mock Field Mapping", mapping_ref.name)
            if mapping.matches_field(fieldname, fieldtype, doctype):
                return mapping

        return None

    @staticmethod
    def get_all_matching_mappings(
        fieldname: str,
        fieldtype: str = None,
        doctype: str = None
    ) -> list:
        """
        Find all matching field mappings for the given field.

        Mappings are returned in priority order (ascending).

        Args:
            fieldname: The name of the field.
            fieldtype: The Frappe field type (optional).
            doctype: The DocType name (optional).

        Returns:
            list: List of matching MockFieldMapping documents.
        """
        # Get all enabled mappings sorted by priority
        mappings = frappe.get_all(
            "Mock Field Mapping",
            filters={"enabled": 1},
            fields=["name"],
            order_by="priority ASC"
        )

        matching = []
        for mapping_ref in mappings:
            mapping = frappe.get_doc("Mock Field Mapping", mapping_ref.name)
            if mapping.matches_field(fieldname, fieldtype, doctype):
                matching.append(mapping)

        return matching

    @staticmethod
    def get_mappings_by_generator_type(generator_type: str) -> list:
        """
        Get all enabled mappings of a specific generator type.

        Args:
            generator_type: The generator type to filter by.

        Returns:
            list: List of mapping documents.
        """
        return frappe.get_all(
            "Mock Field Mapping",
            filters={"enabled": 1, "generator_type": generator_type},
            fields=["name", "mapping_name", "field_pattern", "priority"],
            order_by="priority ASC"
        )

    @staticmethod
    def get_turkish_mappings() -> list:
        """
        Get all enabled Turkish validator mappings.

        Returns:
            list: List of Turkish validator mapping documents.
        """
        return MockFieldMapping.get_mappings_by_generator_type("Turkish Validator")

    @frappe.whitelist()
    def test_mapping(self, test_fieldname: str, test_fieldtype: str = None, test_doctype: str = None) -> dict:
        """
        Test if this mapping would match a given field.

        Args:
            test_fieldname: The field name to test.
            test_fieldtype: The field type to test (optional).
            test_doctype: The DocType to test (optional).

        Returns:
            dict: Test result with match status and generator config if matched.
        """
        matches = self.matches_field(test_fieldname, test_fieldtype, test_doctype)

        result = {
            "mapping_name": self.mapping_name,
            "test_fieldname": test_fieldname,
            "test_fieldtype": test_fieldtype,
            "test_doctype": test_doctype,
            "matches": matches,
        }

        if matches:
            result["generator_config"] = self.get_generator_config()

        return result

    @frappe.whitelist()
    def duplicate_mapping(self, new_name: str = None) -> str:
        """
        Create a duplicate of this mapping.

        Args:
            new_name: Optional name for the duplicate.

        Returns:
            str: The name of the new mapping.
        """
        if not new_name:
            new_name = f"{self.mapping_name} (Copy)"

        # Ensure unique name
        counter = 1
        base_name = new_name
        while frappe.db.exists("Mock Field Mapping", new_name):
            counter += 1
            new_name = f"{base_name} {counter}"

        new_doc = frappe.copy_doc(self)
        new_doc.mapping_name = new_name
        new_doc.enabled = 0  # Disable by default to avoid conflicts
        new_doc.insert()

        frappe.msgprint(
            _("Mapping duplicated as '{0}' (disabled by default).").format(new_name),
            indicator="green",
            alert=True
        )

        return new_doc.name
