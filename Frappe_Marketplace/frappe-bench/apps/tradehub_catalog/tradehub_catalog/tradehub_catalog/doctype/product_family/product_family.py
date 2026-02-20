# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document


class ProductFamily(Document):
    """
    Product Family DocType - Defines data schema and quality rules for products.

    Product Families define:
    - Attributes that products in this family can have
    - Variant axes for variant generation
    - Completeness rules for quality tracking
    - Media requirements (min/max images, required angles)
    - Default values for new products
    - Channel mappings for export
    - Translatable attribute flags
    - Label overrides for customization
    """

    def validate(self):
        """Validate the Product Family document."""
        self.validate_family_code()
        self.validate_media_requirements()
        self.validate_variant_axes()
        self.validate_completeness_rules()

    def validate_family_code(self):
        """Ensure family_code follows naming conventions (lowercase, alphanumeric, underscores)."""
        if self.family_code:
            pattern = r'^[a-z][a-z0-9_]*$'
            if not re.match(pattern, self.family_code):
                frappe.throw(
                    _("Family Code must start with a lowercase letter and contain only "
                      "lowercase letters, numbers, and underscores.")
                )

    def validate_media_requirements(self):
        """Validate media requirements are sensible."""
        if self.min_images is not None and self.min_images < 0:
            frappe.throw(_("Minimum Images cannot be negative."))

        if self.max_images is not None and self.max_images < 0:
            frappe.throw(_("Maximum Images cannot be negative."))

        if (self.min_images is not None and self.max_images is not None
                and self.min_images > self.max_images):
            frappe.throw(_("Minimum Images cannot be greater than Maximum Images."))

    def validate_variant_axes(self):
        """Validate variant axes configuration."""
        if not self.variant_axes:
            return

        # Check for duplicate attributes in variant axes
        attribute_codes = []
        for axis in self.variant_axes:
            if axis.pim_attribute:
                if axis.pim_attribute in attribute_codes:
                    frappe.throw(
                        _("Duplicate attribute '{0}' in variant axes.").format(axis.pim_attribute)
                    )
                attribute_codes.append(axis.pim_attribute)

        # Check that only one primary axis is defined
        primary_count = sum(1 for axis in self.variant_axes if axis.is_primary_axis)
        if primary_count > 1:
            frappe.throw(_("Only one variant axis can be marked as primary."))

    def validate_completeness_rules(self):
        """Validate completeness rules configuration."""
        if not self.completeness_rules:
            return

        # Validate rule weights are between 0 and 1
        for rule in self.completeness_rules:
            if rule.weight is not None:
                if rule.weight < 0 or rule.weight > 1:
                    frappe.throw(
                        _("Completeness rule weight must be between 0 and 1.")
                    )

    def before_save(self):
        """Actions to perform before saving."""
        self.set_defaults()

    def set_defaults(self):
        """Set default values if not provided."""
        if self.min_images is None:
            self.min_images = 1
        if self.max_images is None:
            self.max_images = 10

    def get_attributes(self, include_details=False):
        """
        Get all PIM Attributes associated with this Product Family.

        Args:
            include_details: If True, return full attribute documents

        Returns:
            list: List of attribute codes or attribute documents
        """
        if not self.family_attributes:
            return []

        if not include_details:
            return [attr.pim_attribute for attr in self.family_attributes if attr.pim_attribute]

        attributes = []
        for attr_link in self.family_attributes:
            if attr_link.pim_attribute:
                try:
                    attr = frappe.get_doc("PIM Attribute", attr_link.pim_attribute)
                    attributes.append({
                        'attribute': attr,
                        'is_required': attr_link.is_required,
                        'is_variant': attr_link.is_variant,
                        'is_unique_per_family': attr_link.is_unique_per_family,
                        'is_filterable': attr_link.is_filterable,
                        'sort_order': attr_link.sort_order
                    })
                except frappe.DoesNotExistError:
                    pass

        return sorted(attributes, key=lambda a: a.get('sort_order', 0))

    def get_required_attributes(self):
        """
        Get list of required attribute codes for this family.

        Returns:
            list: List of required attribute codes
        """
        if not self.family_attributes:
            return []

        return [
            attr.pim_attribute
            for attr in self.family_attributes
            if attr.pim_attribute and attr.is_required
        ]

    def get_variant_axes(self):
        """
        Get variant axes configuration.

        Returns:
            list: List of variant axis configurations sorted by axis_order
        """
        if not self.variant_axes:
            return []

        axes = []
        for axis in self.variant_axes:
            if axis.pim_attribute:
                axes.append({
                    'attribute': axis.pim_attribute,
                    'order': axis.axis_order,
                    'is_primary': axis.is_primary_axis,
                    'show_in_name': axis.show_in_variant_name
                })

        return sorted(axes, key=lambda a: a.get('order', 0))

    def get_variant_attribute_codes(self):
        """
        Get list of attribute codes that are marked as variant attributes.

        Returns:
            list: List of variant attribute codes
        """
        if not self.family_attributes:
            return []

        return [
            attr.pim_attribute
            for attr in self.family_attributes
            if attr.pim_attribute and attr.is_variant
        ]

    def get_completeness_rules(self, channel=None, locale=None):
        """
        Get completeness rules, optionally filtered by channel and/or locale.

        Args:
            channel: Optional channel code to filter by
            locale: Optional locale to filter by

        Returns:
            list: List of completeness rule configurations
        """
        if not self.completeness_rules:
            return []

        rules = []
        for rule in self.completeness_rules:
            if not rule.is_enabled:
                continue

            # Filter by channel if specified
            if channel and rule.channel and rule.channel != channel:
                continue

            # Filter by locale if specified
            if locale and rule.locale and rule.locale != locale:
                continue

            rules.append({
                'rule_type': rule.rule_type,
                'weight': rule.weight,
                'target_attribute': rule.target_attribute,
                'channel': rule.channel,
                'locale': rule.locale,
                'min_value': rule.min_value,
                'max_value': rule.max_value,
                'min_length': rule.min_length,
                'max_length': rule.max_length,
                'min_media_count': rule.min_media_count,
                'max_media_count': rule.max_media_count
            })

        return rules

    def get_required_image_angles(self, channel=None):
        """
        Get required image angles, optionally filtered by channel.

        Args:
            channel: Optional channel code to filter by

        Returns:
            list: List of required image angle configurations
        """
        if not self.required_image_angles:
            return []

        angles = []
        for angle in self.required_image_angles:
            # Filter by channel if specified
            if channel and angle.channel and angle.channel != channel:
                continue

            angles.append({
                'angle_name': angle.angle_name,
                'angle_code': angle.angle_code,
                'is_required': angle.is_required,
                'sort_order': angle.sort_order,
                'min_width': angle.min_width,
                'min_height': angle.min_height,
                'description': angle.description
            })

        return sorted(angles, key=lambda a: a.get('sort_order', 0))

    def get_default_values(self, channel=None, locale=None):
        """
        Get default values for attributes, optionally filtered by channel and/or locale.

        Args:
            channel: Optional channel code to filter by
            locale: Optional locale to filter by

        Returns:
            dict: Dictionary mapping attribute codes to default values
        """
        if not self.default_values:
            return {}

        defaults = {}
        for dv in self.default_values:
            if not dv.pim_attribute:
                continue

            # Filter by channel if specified
            if channel and dv.channel and dv.channel != channel:
                continue

            # Filter by locale if specified
            if locale and dv.locale and dv.locale != locale:
                continue

            defaults[dv.pim_attribute] = {
                'value': dv.default_value,
                'value_type': dv.value_type,
                'channel': dv.channel,
                'locale': dv.locale
            }

        return defaults

    def get_channel_mappings(self, channel=None):
        """
        Get channel field mappings, optionally filtered by channel.

        Args:
            channel: Optional channel code to filter by

        Returns:
            list: List of channel mapping configurations
        """
        if not self.channel_mappings:
            return []

        mappings = []
        for mapping in self.channel_mappings:
            # Filter by channel if specified
            if channel and mapping.channel != channel:
                continue

            mappings.append({
                'attribute': mapping.pim_attribute,
                'channel': mapping.channel,
                'target_field_name': mapping.target_field_name,
                'target_field_code': mapping.target_field_code,
                'transform_type': mapping.transform_type,
                'transform_config': mapping.transform_config,
                'is_required': mapping.is_required_for_channel,
                'sort_order': mapping.sort_order
            })

        return sorted(mappings, key=lambda m: m.get('sort_order', 0))

    def get_translatable_attributes(self):
        """
        Get list of attribute codes that are translatable.

        Returns:
            dict: Dictionary mapping attribute codes to translation config
        """
        if not self.translatable_attributes:
            return {}

        translatable = {}
        for ta in self.translatable_attributes:
            if ta.pim_attribute and ta.is_translatable:
                translatable[ta.pim_attribute] = {
                    'source_locale': ta.source_locale,
                    'required_locales': (ta.required_locales or '').split(',')
                }

        return translatable

    def get_label_override(self, attribute_code, locale=None):
        """
        Get label override for a specific attribute.

        Args:
            attribute_code: The attribute code to get override for
            locale: Optional locale to match

        Returns:
            dict: Label override configuration or None
        """
        if not self.label_overrides:
            return None

        for override in self.label_overrides:
            if override.pim_attribute != attribute_code:
                continue

            # If locale is specified, must match
            if locale and override.locale and override.locale != locale:
                continue

            # Prefer locale-specific override
            if not locale or not override.locale or override.locale == locale:
                return {
                    'label': override.custom_label,
                    'description': override.custom_description,
                    'placeholder': override.custom_placeholder,
                    'locale': override.locale
                }

        return None

    def get_all_label_overrides(self, locale=None):
        """
        Get all label overrides, optionally filtered by locale.

        Args:
            locale: Optional locale to filter by

        Returns:
            dict: Dictionary mapping attribute codes to override configs
        """
        if not self.label_overrides:
            return {}

        overrides = {}
        for override in self.label_overrides:
            if not override.pim_attribute:
                continue

            # Filter by locale if specified
            if locale and override.locale and override.locale != locale:
                continue

            overrides[override.pim_attribute] = {
                'label': override.custom_label,
                'description': override.custom_description,
                'placeholder': override.custom_placeholder,
                'locale': override.locale
            }

        return overrides

    def get_product_class_doc(self):
        """
        Get the linked Product Class document.

        Returns:
            Document: Product Class document or None
        """
        if not self.product_class:
            return None

        try:
            return frappe.get_doc("Product Class", self.product_class)
        except frappe.DoesNotExistError:
            return None

    def get_family_config(self):
        """
        Get complete family configuration for dynamic form rendering.

        Returns:
            dict: Complete family configuration
        """
        return {
            'family_name': self.family_name,
            'family_code': self.family_code,
            'product_class': self.product_class,
            'attributes': self.get_attributes(include_details=True),
            'required_attributes': self.get_required_attributes(),
            'variant_axes': self.get_variant_axes(),
            'variant_attribute_codes': self.get_variant_attribute_codes(),
            'completeness_rules': self.get_completeness_rules(),
            'media_requirements': {
                'min_images': self.min_images,
                'max_images': self.max_images,
                'require_main_image': self.require_main_image,
                'allow_video': self.allow_video,
                'required_angles': self.get_required_image_angles()
            },
            'default_values': self.get_default_values(),
            'translatable_attributes': self.get_translatable_attributes(),
            'label_overrides': self.get_all_label_overrides()
        }
