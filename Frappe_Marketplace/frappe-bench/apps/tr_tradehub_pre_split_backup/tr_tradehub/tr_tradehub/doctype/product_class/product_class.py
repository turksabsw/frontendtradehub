# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import json
import frappe
from frappe import _
from frappe.model.document import Document


class ProductClass(Document):
    """
    Product Class DocType - Defines structural and behavioral identity for products.

    Product Classes define:
    - Shared attribute groups that products of this class inherit
    - Custom field definitions specific to this class
    - Workflow and status management
    - Commerce rules (pricing, inventory, variants)
    - URL/SEO patterns
    - Search configuration
    - Role-based permissions
    - ERPNext and marketplace integration settings
    """

    def validate(self):
        """Validate the Product Class document."""
        self.validate_class_code()
        self.validate_form_layout()
        self.validate_default_status()
        self.validate_pricing_rules()
        self.validate_url_patterns()

    def validate_class_code(self):
        """Ensure class_code follows naming conventions (lowercase, alphanumeric, underscores)."""
        if self.class_code:
            pattern = r'^[a-z][a-z0-9_]*$'
            if not re.match(pattern, self.class_code):
                frappe.throw(
                    _("Class Code must start with a lowercase letter and contain only "
                      "lowercase letters, numbers, and underscores.")
                )

    def validate_form_layout(self):
        """Validate form_layout is valid JSON if provided."""
        if self.form_layout:
            try:
                layout = json.loads(self.form_layout)
                if not isinstance(layout, (dict, list)):
                    frappe.throw(_("Form Layout must be a JSON object or array."))
            except json.JSONDecodeError as e:
                frappe.throw(_("Form Layout is not valid JSON: {0}").format(str(e)))

    def validate_default_status(self):
        """Ensure default_status matches one of the allowed statuses."""
        if self.default_status and self.allowed_statuses:
            status_codes = [s.status_code for s in self.allowed_statuses]
            if self.default_status not in status_codes:
                frappe.throw(
                    _("Default Status '{0}' must match one of the allowed statuses: {1}").format(
                        self.default_status, ', '.join(status_codes)
                    )
                )

    def validate_pricing_rules(self):
        """Validate pricing rules make sense."""
        if self.min_margin_percent and self.min_margin_percent < 0:
            frappe.throw(_("Minimum Margin % cannot be negative."))

        if self.max_discount_percent:
            if self.max_discount_percent < 0:
                frappe.throw(_("Maximum Discount % cannot be negative."))
            if self.max_discount_percent > 100:
                frappe.throw(_("Maximum Discount % cannot exceed 100%."))

    def validate_url_patterns(self):
        """Basic validation of Jinja URL patterns."""
        url_fields = ['url_pattern', 'meta_title_template', 'meta_description_template',
                      'canonical_url_pattern']
        for field in url_fields:
            value = getattr(self, field, None)
            if value:
                # Check for basic Jinja syntax errors
                if value.count('{{') != value.count('}}'):
                    frappe.throw(
                        _("Invalid Jinja template in {0}: mismatched braces.").format(
                            self.meta.get_label(field)
                        )
                    )

    def before_save(self):
        """Actions to perform before saving."""
        self.set_default_status_if_empty()

    def set_default_status_if_empty(self):
        """Set default status from allowed statuses if not set."""
        if not self.default_status and self.allowed_statuses:
            # Find the status marked as default, or use the first one
            for status in self.allowed_statuses:
                if status.is_default:
                    self.default_status = status.status_code
                    break
            if not self.default_status:
                self.default_status = self.allowed_statuses[0].status_code

    def get_attribute_groups(self):
        """
        Get all PIM Attribute Groups associated with this Product Class.

        Returns:
            list: List of PIM Attribute Group documents
        """
        groups = []
        for group_link in self.shared_attribute_groups:
            if group_link.attribute_group:
                try:
                    group = frappe.get_doc("PIM Attribute Group", group_link.attribute_group)
                    groups.append(group)
                except frappe.DoesNotExistError:
                    pass
        return sorted(groups, key=lambda g: g.sort_order or 0)

    def get_custom_fields(self):
        """
        Get all custom field definitions for this Product Class.

        Returns:
            list: List of custom field dictionaries
        """
        fields = []
        for field in self.custom_field_definitions:
            fields.append({
                'fieldname': field.field_name,
                'label': field.field_label,
                'fieldtype': field.fieldtype,
                'options': field.options,
                'reqd': field.is_required,
                'default': field.default_value,
                'description': field.description,
                'depends_on': field.depends_on,
                'read_only': field.read_only,
                'sort_order': field.sort_order
            })
        return sorted(fields, key=lambda f: f.get('sort_order', 0))

    def get_display_config(self, location=None):
        """
        Get display field configuration, optionally filtered by location.

        Args:
            location: Optional filter for display location

        Returns:
            list: List of display field configurations
        """
        configs = []
        for field in self.card_display_fields:
            if location is None or field.display_location == location:
                configs.append({
                    'field_name': field.field_name,
                    'label': field.field_label or field.field_name,
                    'location': field.display_location,
                    'sort_order': field.sort_order,
                    'format_template': field.format_template,
                    'show_label': field.show_label,
                    'css_class': field.css_class
                })
        return sorted(configs, key=lambda c: c.get('sort_order', 0))

    def get_allowed_status_codes(self):
        """
        Get list of allowed status codes.

        Returns:
            list: List of status codes
        """
        return [s.status_code for s in self.allowed_statuses]

    def get_status_config(self, status_code):
        """
        Get configuration for a specific status.

        Args:
            status_code: The status code to look up

        Returns:
            dict: Status configuration or None if not found
        """
        for status in self.allowed_statuses:
            if status.status_code == status_code:
                return {
                    'name': status.status_name,
                    'code': status.status_code,
                    'color': status.color,
                    'is_default': status.is_default,
                    'is_active_status': status.is_active_status,
                    'allows_editing': status.allows_editing,
                    'allows_deletion': status.allows_deletion,
                    'allowed_transitions': (status.allowed_transitions or '').split(','),
                    'auto_transition_after': status.auto_transition_after,
                    'auto_transition_to': status.auto_transition_to
                }
        return None

    def get_role_permissions(self, role=None):
        """
        Get role permissions, optionally filtered by role.

        Args:
            role: Optional role name to filter by

        Returns:
            list: List of permission configurations
        """
        permissions = []
        for perm in self.role_permissions:
            if role is None or perm.role == role:
                permissions.append({
                    'role': perm.role,
                    'can_read': perm.can_read,
                    'can_write': perm.can_write,
                    'can_create': perm.can_create,
                    'can_delete': perm.can_delete,
                    'can_export': perm.can_export,
                    'can_import': perm.can_import,
                    'can_change_status': perm.can_change_status,
                    'allowed_statuses': (perm.allowed_statuses or '').split(',')
                })
        return permissions

    def get_search_config(self):
        """
        Get search configuration for this product class.

        Returns:
            dict: Search configuration with filterable, sortable, and faceted fields
        """
        config = {
            'searchable': [],
            'filterable': [],
            'sortable': [],
            'faceted': []
        }

        for search in self.search_configs:
            if not search.is_enabled:
                continue

            field_config = {
                'field_name': search.field_name,
                'label': search.field_label or search.field_name,
                'search_type': search.search_type,
                'boost_weight': search.boost_weight,
                'filter_widget': search.filter_widget,
                'sort_order': search.sort_order,
                'default_sort_direction': search.default_sort_direction
            }

            config['searchable'].append(field_config)

            if search.is_filterable:
                config['filterable'].append(field_config)
            if search.is_sortable:
                config['sortable'].append(field_config)
            if search.is_faceted:
                config['faceted'].append(field_config)

        return config

    def render_url(self, product_doc):
        """
        Render product URL using the URL pattern template.

        Args:
            product_doc: Product document or dict

        Returns:
            str: Rendered URL
        """
        if not self.url_pattern:
            return None

        from jinja2 import Template
        try:
            template = Template(self.url_pattern)
            return template.render(doc=product_doc)
        except Exception:
            return None

    def render_meta_title(self, product_doc):
        """
        Render SEO meta title using the template.

        Args:
            product_doc: Product document or dict

        Returns:
            str: Rendered meta title
        """
        if not self.meta_title_template:
            return None

        from jinja2 import Template
        try:
            template = Template(self.meta_title_template)
            return template.render(doc=product_doc)
        except Exception:
            return None

    def render_meta_description(self, product_doc):
        """
        Render SEO meta description using the template.

        Args:
            product_doc: Product document or dict

        Returns:
            str: Rendered meta description
        """
        if not self.meta_description_template:
            return None

        from jinja2 import Template
        try:
            template = Template(self.meta_description_template)
            return template.render(doc=product_doc)
        except Exception:
            return None

    def is_channel_allowed(self, channel_code):
        """
        Check if a sales channel is allowed for this product class.

        Args:
            channel_code: The channel code to check

        Returns:
            bool: True if channel is allowed
        """
        if not self.allowed_channels:
            return True  # Empty means all channels allowed

        allowed = [c.strip() for c in self.allowed_channels.split(',')]
        return channel_code in allowed
