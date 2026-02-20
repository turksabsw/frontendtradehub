# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class MockProfileFieldOverride(Document):
    """Child table for field overrides in a generation profile.

    Used in Mock Generation Profile to specify custom generation
    rules for specific fields, overriding the default generation logic.
    """

    # Valid generator types
    GENERATOR_TYPES = [
        "Faker",
        "Fixed Value",
        "Range",
        "Pattern",
        "Select Options",
        "LLM"
    ]

    def validate(self):
        """Validate the field override entry."""
        self.validate_doctype_exists()
        self.validate_field_exists()
        self.validate_generator_type()
        self.validate_generator_config()

    def validate_doctype_exists(self):
        """Validate that the specified DocType exists."""
        if not self.doctype_name:
            frappe.throw("DocType is required")

        if not frappe.db.exists("DocType", self.doctype_name):
            frappe.throw(f"DocType '{self.doctype_name}' does not exist")

    def validate_field_exists(self):
        """Validate that the specified field exists in the DocType."""
        if not self.field_name:
            frappe.throw("Field Name is required")

        if not self.doctype_name:
            return

        meta = frappe.get_meta(self.doctype_name)
        field_names = [f.fieldname for f in meta.fields]

        if self.field_name not in field_names:
            frappe.throw(
                f"Field '{self.field_name}' does not exist in DocType '{self.doctype_name}'"
            )

    def validate_generator_type(self):
        """Validate that generator_type is valid."""
        if not self.generator_type:
            frappe.throw("Generator Type is required")

        if self.generator_type not in self.GENERATOR_TYPES:
            frappe.throw(
                f"Invalid Generator Type '{self.generator_type}'. "
                f"Valid options are: {', '.join(self.GENERATOR_TYPES)}"
            )

    def validate_generator_config(self):
        """Validate the configuration for the selected generator type."""
        if self.generator_type == "Faker":
            self._validate_faker_config()
        elif self.generator_type == "Fixed Value":
            self._validate_fixed_value_config()
        elif self.generator_type == "Range":
            self._validate_range_config()
        elif self.generator_type == "Pattern":
            self._validate_pattern_config()
        elif self.generator_type == "Select Options":
            self._validate_select_options_config()
        elif self.generator_type == "LLM":
            self._validate_llm_config()

    def _validate_faker_config(self):
        """Validate Faker generator configuration."""
        if not self.faker_method:
            frappe.throw("Faker Method is required for Faker generator type")

        # Validate faker_args is valid JSON if provided
        if self.faker_args:
            try:
                json.loads(self.faker_args)
            except json.JSONDecodeError as e:
                frappe.throw(f"Faker Arguments must be valid JSON: {e}")

    def _validate_fixed_value_config(self):
        """Validate Fixed Value generator configuration."""
        if self.fixed_value is None or self.fixed_value == "":
            frappe.throw("Fixed Value is required for Fixed Value generator type")

    def _validate_range_config(self):
        """Validate Range generator configuration."""
        if self.range_min is None:
            frappe.throw("Range Min is required for Range generator type")

        if self.range_max is None:
            frappe.throw("Range Max is required for Range generator type")

        if self.range_min > self.range_max:
            frappe.throw("Range Min cannot be greater than Range Max")

    def _validate_pattern_config(self):
        """Validate Pattern generator configuration."""
        if not self.pattern_template:
            frappe.throw("Pattern Template is required for Pattern generator type")

    def _validate_select_options_config(self):
        """Validate Select Options generator configuration."""
        if not self.select_options:
            frappe.throw("Select Options is required for Select Options generator type")

        # Ensure there's at least one option
        options = [opt.strip() for opt in self.select_options.split("\n") if opt.strip()]
        if not options:
            frappe.throw("At least one option is required for Select Options generator type")

    def _validate_llm_config(self):
        """Validate LLM generator configuration."""
        if not self.llm_prompt:
            frappe.throw("LLM Prompt is required for LLM generator type")

    def get_generator_config(self):
        """Get the configuration dictionary for this field override.

        Returns:
            dict: Configuration dictionary with all relevant settings
                  for the selected generator type.
        """
        config = {
            "doctype": self.doctype_name,
            "field": self.field_name,
            "generator_type": self.generator_type,
            "enabled": self.enabled
        }

        if self.generator_type == "Faker":
            config["faker_method"] = self.faker_method
            config["faker_args"] = json.loads(self.faker_args) if self.faker_args else {}
        elif self.generator_type == "Fixed Value":
            config["fixed_value"] = self.fixed_value
        elif self.generator_type == "Range":
            config["range_min"] = self.range_min
            config["range_max"] = self.range_max
        elif self.generator_type == "Pattern":
            config["pattern_template"] = self.pattern_template
        elif self.generator_type == "Select Options":
            options = [opt.strip() for opt in self.select_options.split("\n") if opt.strip()]
            config["select_options"] = options
        elif self.generator_type == "LLM":
            config["llm_prompt"] = self.llm_prompt

        return config
