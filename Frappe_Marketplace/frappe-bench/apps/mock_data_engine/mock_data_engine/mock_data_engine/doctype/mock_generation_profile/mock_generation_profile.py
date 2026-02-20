# Copyright (c) 2024, Custom and contributors
# For license information, please see license.txt

"""
Mock Generation Profile - DocType Controller

This module provides the controller for Mock Generation Profile, which stores
reusable presets for mock data generation including target DocTypes,
quantities, generation options, and field overrides.

Profiles can be linked to Mock Generation Requests for consistent,
repeatable data generation configurations.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class MockGenerationProfile(Document):
    """
    Controller for Mock Generation Profile DocType.

    Manages reusable generation presets including target configuration,
    generation options, AI settings, and field overrides.
    """

    def validate(self):
        """Validate the profile before save."""
        self.validate_target_configuration()
        self.validate_ai_settings()
        self.validate_doctype_quantities()
        self.validate_field_overrides()

    def validate_target_configuration(self):
        """
        Validate that the target configuration is properly set.

        Raises:
            frappe.ValidationError: If target configuration is invalid.
        """
        if self.target_mode == "All DocTypes in App":
            if not self.target_app:
                frappe.throw(
                    _("Target App is required when target mode is 'All DocTypes in App'."),
                    title=_("Missing Target App")
                )

        elif self.target_mode == "All DocTypes in Apps":
            if not self.target_apps or len(self.target_apps) == 0:
                frappe.throw(
                    _("At least one target app must be specified when target mode is "
                      "'All DocTypes in Apps'."),
                    title=_("Missing Target Apps")
                )

        elif self.target_mode == "Specific DocTypes":
            if not self.doctype_quantities or len(self.doctype_quantities) == 0:
                frappe.throw(
                    _("At least one DocType must be specified when target mode is "
                      "'Specific DocTypes'."),
                    title=_("Missing DocType Quantities")
                )

    def validate_ai_settings(self):
        """
        Validate AI generation settings.

        Raises:
            frappe.ValidationError: If AI settings are invalid.
        """
        if self.use_ai_generation:
            # Validate temperature range
            if self.ai_temperature is not None:
                if self.ai_temperature < 0 or self.ai_temperature > 2:
                    frappe.throw(
                        _("AI Temperature must be between 0 and 2. "
                          "Value 0 is deterministic, 1 is default, 2 is most creative."),
                        title=_("Invalid AI Temperature")
                    )

    def validate_doctype_quantities(self):
        """
        Validate DocType quantities for duplicate entries.

        Raises:
            frappe.ValidationError: If duplicate DocTypes are found.
        """
        if self.doctype_quantities:
            doctypes = []
            for row in self.doctype_quantities:
                if row.doctype_name:
                    if row.doctype_name in doctypes:
                        frappe.throw(
                            _("Duplicate DocType '{0}' found in DocType Quantities. "
                              "Each DocType can only appear once.").format(row.doctype_name),
                            title=_("Duplicate DocType")
                        )
                    doctypes.append(row.doctype_name)

                    # Validate record count
                    if row.record_count is not None and row.record_count < 1:
                        frappe.throw(
                            _("Record count for '{0}' must be at least 1.").format(
                                row.doctype_name
                            ),
                            title=_("Invalid Record Count")
                        )

    def validate_field_overrides(self):
        """
        Validate field overrides for consistency.

        Raises:
            frappe.ValidationError: If field overrides are invalid.
        """
        if self.field_overrides:
            seen = set()
            for row in self.field_overrides:
                # Create unique key for doctype + fieldname combination
                key = f"{row.target_doctype}:{row.fieldname}"
                if key in seen:
                    frappe.throw(
                        _("Duplicate field override for '{0}.{1}'. "
                          "Each field can only have one override per DocType.").format(
                            row.target_doctype, row.fieldname
                        ),
                        title=_("Duplicate Field Override")
                    )
                seen.add(key)

    def get_target_doctypes(self):
        """
        Get the list of target DocTypes based on the target mode.

        Returns:
            list: List of dicts with 'doctype' and 'record_count' keys.
        """
        if self.target_mode == "Specific DocTypes":
            return [
                {
                    "doctype": row.doctype_name,
                    "record_count": row.record_count or 10
                }
                for row in (self.doctype_quantities or [])
                if row.doctype_name
            ]

        elif self.target_mode == "All DocTypes in App":
            return self._get_doctypes_for_app(self.target_app)

        elif self.target_mode == "All DocTypes in Apps":
            result = []
            for app_row in (self.target_apps or []):
                if app_row.app_name:
                    result.extend(self._get_doctypes_for_app(
                        app_row.app_name,
                        app_row.default_record_count or 10
                    ))
            return result

        return []

    def _get_doctypes_for_app(self, app_name, default_count=10):
        """
        Get all non-excluded DocTypes for an app.

        Args:
            app_name: The Frappe app name.
            default_count: Default record count for each DocType.

        Returns:
            list: List of dicts with 'doctype' and 'record_count' keys.
        """
        try:
            # Get all modules for the app
            modules = frappe.get_all(
                "Module Def",
                filters={"app_name": app_name},
                pluck="name"
            )

            if not modules:
                return []

            # Get all DocTypes in those modules
            doctypes = frappe.get_all(
                "DocType",
                filters={
                    "module": ["in", modules],
                    "istable": 0,  # Exclude child tables
                    "issingle": 0,  # Exclude single DocTypes
                    "custom": 0  # Exclude custom DocTypes by default
                },
                pluck="name"
            )

            # Filter out excluded DocTypes from settings
            settings = frappe.get_single("Mock Engine Settings")
            excluded = set()
            for row in (settings.excluded_doctypes or []):
                if row.doctype_name:
                    excluded.add(row.doctype_name)

            return [
                {"doctype": dt, "record_count": default_count}
                for dt in doctypes
                if dt not in excluded
            ]

        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error getting DocTypes for app: {app_name}"
            )
            return []

    def get_effective_locale(self):
        """
        Get the effective locale for this profile.

        Falls back to global settings if not specified.

        Returns:
            str: The locale to use for generation.
        """
        if self.locale:
            return self.locale

        settings = frappe.get_single("Mock Engine Settings")
        return settings.default_locale or "en_US"

    def get_effective_seed(self):
        """
        Get the effective seed value for this profile.

        Falls back to global settings if not specified.

        Returns:
            int or None: The seed value to use for generation.
        """
        if self.seed_value:
            return self.seed_value

        settings = frappe.get_single("Mock Engine Settings")
        return settings.seed_value

    def get_effective_ai_provider(self):
        """
        Get the effective AI provider for this profile.

        Falls back to global settings if not specified.

        Returns:
            str or None: The AI provider to use.
        """
        if self.ai_provider_override:
            return self.ai_provider_override

        settings = frappe.get_single("Mock Engine Settings")
        return settings.primary_llm_provider

    def get_field_override(self, doctype, fieldname):
        """
        Get the field override configuration for a specific field.

        Args:
            doctype: The target DocType name.
            fieldname: The field name.

        Returns:
            dict or None: The override configuration if found.
        """
        if not self.field_overrides:
            return None

        for row in self.field_overrides:
            if row.target_doctype == doctype and row.fieldname == fieldname:
                return {
                    "generator_type": row.generator_type,
                    "fixed_value": row.fixed_value,
                    "faker_provider": row.faker_provider,
                    "faker_method": row.faker_method,
                    "custom_options": row.custom_options,
                    "min_value": row.min_value,
                    "max_value": row.max_value,
                    "skip_field": row.skip_field
                }

        return None

    def get_total_record_count(self):
        """
        Get the total number of records to be generated.

        Returns:
            int: Total record count across all target DocTypes.
        """
        targets = self.get_target_doctypes()
        return sum(t.get("record_count", 0) for t in targets)

    @frappe.whitelist()
    def duplicate_profile(self, new_name=None):
        """
        Create a duplicate of this profile with a new name.

        Args:
            new_name: Optional name for the duplicate. If not provided,
                     will append " (Copy)" to the original name.

        Returns:
            str: The name of the newly created profile.
        """
        if not new_name:
            new_name = f"{self.profile_name} (Copy)"

        # Check if name already exists
        counter = 1
        base_name = new_name
        while frappe.db.exists("Mock Generation Profile", new_name):
            counter += 1
            new_name = f"{base_name} {counter}"

        # Create new document
        new_doc = frappe.copy_doc(self)
        new_doc.profile_name = new_name
        new_doc.enabled = 1
        new_doc.insert()

        frappe.msgprint(
            _("Profile duplicated as '{0}'.").format(new_name),
            indicator="green",
            alert=True
        )

        return new_doc.name

    @frappe.whitelist()
    def create_request_from_profile(self):
        """
        Create a new Mock Generation Request using this profile.

        Returns:
            str: The name of the newly created request.
        """
        if not self.enabled:
            frappe.throw(
                _("Cannot create request from disabled profile. "
                  "Enable the profile first."),
                title=_("Profile Disabled")
            )

        request = frappe.new_doc("Mock Generation Request")
        request.generation_mode = "From Profile"
        request.profile = self.name
        request.title = f"From Profile: {self.profile_name}"
        request.locale = self.locale
        request.seed_value = self.seed_value
        request.auto_resolve_dependencies = self.auto_resolve_dependencies
        request.fail_on_error = self.fail_on_error
        request.log_generation_details = self.log_generation_details
        request.insert()

        frappe.msgprint(
            _("Generation request '{0}' created from profile.").format(request.name),
            indicator="green",
            alert=True
        )

        return request.name
