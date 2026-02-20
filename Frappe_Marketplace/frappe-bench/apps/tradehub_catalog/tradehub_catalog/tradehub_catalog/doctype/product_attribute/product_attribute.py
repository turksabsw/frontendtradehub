# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Product Attribute DocType for Trade Hub B2B Marketplace.

This module implements the Product Attribute DocType for defining variant
attributes like Color, Size, Material, etc. Attributes can be global or
tenant-specific, and support various types (Select, Multi-Select, Text, Number).

Key Features:
- Multiple attribute types for different use cases
- Display type options (Dropdown, Swatch, Button, etc.)
- Multi-tenant support (attributes can be global or tenant-specific)
- Validation rules for text and number attributes
- Statistics tracking (value count, product count)
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class ProductAttribute(Document):
    """
    Product Attribute DocType for defining variant attributes.

    Attributes define the characteristics that differentiate product variants,
    such as Color, Size, Material, etc. Each attribute can have multiple values
    defined in the Product Attribute Value DocType.
    """

    def before_insert(self):
        """Set default values before inserting a new attribute."""
        self.generate_attribute_code()
        self.set_tenant_from_user()

    def validate(self):
        """Validate attribute data before saving."""
        self.validate_attribute_name()
        self.validate_tenant_consistency()
        self.validate_type_settings()
        self.validate_validation_rules()
        self.generate_attribute_code()

    def on_update(self):
        """Actions after attribute is updated."""
        self.clear_attribute_cache()

    def on_trash(self):
        """Prevent deletion of attribute with linked values or products."""
        self.check_linked_values()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def generate_attribute_code(self):
        """Generate attribute code from attribute name if not provided."""
        if not self.attribute_code and self.attribute_name:
            # Convert to uppercase and replace special characters
            code = self.attribute_name.upper()

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

            self.attribute_code = code

    def set_tenant_from_user(self):
        """Set tenant from current user if not already set."""
        if not self.tenant and not self.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant:
                self.tenant = user_tenant

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_attribute_name(self):
        """Validate attribute name is not empty and follows naming conventions."""
        if not self.attribute_name:
            frappe.throw(_("Attribute Name is required"))

        # Check for invalid characters
        if any(char in self.attribute_name for char in ['<', '>', '"', '\\']):
            frappe.throw(_("Attribute Name contains invalid characters"))

        # Check length
        if len(self.attribute_name) > 140:
            frappe.throw(_("Attribute Name cannot exceed 140 characters"))

        # Trim whitespace
        self.attribute_name = self.attribute_name.strip()

    def validate_tenant_consistency(self):
        """Ensure tenant consistency for attributes."""
        # Global attributes should not have tenant
        if self.is_global and self.tenant:
            self.tenant = None
            self.tenant_name = None

        # Non-global attributes need tenant
        if not self.is_global and not self.tenant:
            # Only admin can create global attributes
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Please select a tenant or mark the attribute as global")
                )

    def validate_type_settings(self):
        """Validate attribute type and display type compatibility."""
        # Ensure display type is compatible with attribute type
        type_display_map = {
            "Select": ["Dropdown", "Radio Button", "Color Swatch", "Image Swatch", "Button"],
            "Multi-Select": ["Checkbox", "Dropdown", "Button"],
            "Text": ["Text Input", "Dropdown"],
            "Number": ["Number Input", "Dropdown"],
            "Boolean": ["Checkbox", "Radio Button"]
        }

        valid_displays = type_display_map.get(self.attribute_type, [])
        if self.display_type not in valid_displays:
            # Auto-correct to default display type for the attribute type
            default_displays = {
                "Select": "Dropdown",
                "Multi-Select": "Checkbox",
                "Text": "Text Input",
                "Number": "Number Input",
                "Boolean": "Checkbox"
            }
            self.display_type = default_displays.get(self.attribute_type, "Dropdown")
            frappe.msgprint(
                _("Display type adjusted to {0} for {1} attribute type").format(
                    self.display_type, self.attribute_type
                ),
                indicator="blue"
            )

    def validate_validation_rules(self):
        """Validate validation rules for text and number attributes."""
        # Validate number range
        if self.attribute_type == "Number":
            if self.min_value is not None and self.max_value is not None:
                if self.min_value > self.max_value:
                    frappe.throw(_("Minimum value cannot be greater than maximum value"))

        # Validate regex pattern
        if self.regex_pattern:
            try:
                re.compile(self.regex_pattern)
            except re.error as e:
                frappe.throw(_("Invalid regex pattern: {0}").format(str(e)))

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_values(self):
        """Check for linked attribute values before allowing deletion."""
        value_count = frappe.db.count("Product Attribute Value", {"attribute": self.name})
        if value_count > 0:
            frappe.throw(
                _("Cannot delete attribute with {0} linked value(s). "
                  "Please delete all values first.").format(value_count)
            )

    # =========================================================================
    # STATISTICS METHODS
    # =========================================================================

    def update_value_count(self):
        """Update the value count for this attribute."""
        count = frappe.db.count(
            "Product Attribute Value",
            filters={"attribute": self.name, "enabled": 1}
        )
        self.db_set("value_count", count, update_modified=False)

    def get_values(self, include_disabled=False):
        """
        Get all values for this attribute.

        Args:
            include_disabled: Include disabled values

        Returns:
            list: List of attribute value documents
        """
        filters = {"attribute": self.name}
        if not include_disabled:
            filters["enabled"] = 1

        return frappe.get_all(
            "Product Attribute Value",
            filters=filters,
            fields=[
                "name", "value_name", "value_code", "color_code",
                "image", "display_order", "enabled"
            ],
            order_by="display_order asc, value_name asc"
        )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_attribute_cache(self):
        """Clear cached attribute data."""
        cache_keys = [
            "attribute_list",
            f"attribute:{self.name}",
            f"attribute_values:{self.name}"
        ]
        if self.tenant:
            cache_keys.append(f"attribute_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_attribute_list(tenant=None, include_disabled=False, variant_only=False):
    """
    Get list of product attributes.

    Args:
        tenant: Optional tenant filter (None = global attributes only)
        include_disabled: Include disabled attributes
        variant_only: Only include variant attributes

    Returns:
        list: List of attribute documents
    """
    filters = {}

    if not include_disabled:
        filters["enabled"] = 1

    if variant_only:
        filters["is_variant_attribute"] = 1

    if tenant:
        # Include tenant-specific and global attributes
        attributes = frappe.get_all(
            "Product Attribute",
            or_filters=[
                ["tenant", "=", tenant],
                ["is_global", "=", 1]
            ],
            filters=filters,
            fields=[
                "name", "attribute_name", "attribute_code", "attribute_type",
                "display_type", "is_variant_attribute", "is_required",
                "is_filterable", "display_order", "value_count"
            ],
            order_by="display_order asc, attribute_name asc"
        )
    else:
        # Only global attributes
        filters["is_global"] = 1
        attributes = frappe.get_all(
            "Product Attribute",
            filters=filters,
            fields=[
                "name", "attribute_name", "attribute_code", "attribute_type",
                "display_type", "is_variant_attribute", "is_required",
                "is_filterable", "display_order", "value_count"
            ],
            order_by="display_order asc, attribute_name asc"
        )

    return attributes


@frappe.whitelist()
def get_attribute_with_values(attribute_name, include_disabled=False):
    """
    Get attribute with all its values.

    Args:
        attribute_name: Name of the attribute
        include_disabled: Include disabled values

    Returns:
        dict: Attribute data with values list
    """
    if not frappe.db.exists("Product Attribute", attribute_name):
        frappe.throw(_("Attribute {0} not found").format(attribute_name))

    attribute = frappe.get_doc("Product Attribute", attribute_name)

    # Check tenant permission
    if attribute.tenant and not attribute.is_global:
        user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
        if attribute.tenant != user_tenant:
            frappe.throw(_("Access denied: Tenant isolation violation"))

    return {
        "name": attribute.name,
        "attribute_name": attribute.attribute_name,
        "attribute_code": attribute.attribute_code,
        "attribute_type": attribute.attribute_type,
        "display_type": attribute.display_type,
        "is_variant_attribute": attribute.is_variant_attribute,
        "is_required": attribute.is_required,
        "is_filterable": attribute.is_filterable,
        "description": attribute.description,
        "help_text": attribute.help_text,
        "values": attribute.get_values(include_disabled)
    }


@frappe.whitelist()
def get_variant_attributes(tenant=None):
    """
    Get all variant attributes for variant matrix generation.

    Args:
        tenant: Optional tenant filter

    Returns:
        list: List of variant attributes with their values
    """
    attributes = get_attribute_list(tenant=tenant, variant_only=True)

    result = []
    for attr in attributes:
        attr_with_values = get_attribute_with_values(attr.name)
        result.append(attr_with_values)

    return result


@frappe.whitelist()
def update_attribute_counts():
    """
    Update value counts for all attributes.
    Intended to be called via scheduler or manually.

    Returns:
        dict: Number of attributes updated
    """
    attributes = frappe.get_all("Product Attribute", fields=["name"])
    updated = 0

    for attr_data in attributes:
        attr = frappe.get_doc("Product Attribute", attr_data.name)
        old_count = attr.value_count or 0
        attr.update_value_count()
        if cint(attr.value_count) != old_count:
            updated += 1

    frappe.db.commit()

    return {"updated_count": updated, "total_attributes": len(attributes)}


@frappe.whitelist()
def create_standard_attributes():
    """
    Create standard product attributes (Color, Size, Material).
    Intended to be called during initial setup.

    Returns:
        dict: Created attributes
    """
    # Check permission
    if not frappe.has_permission("Product Attribute", "create"):
        frappe.throw(_("Insufficient permissions to create attributes"))

    standard_attributes = [
        {
            "attribute_name": "Color",
            "attribute_type": "Select",
            "display_type": "Color Swatch",
            "is_variant_attribute": 1,
            "is_filterable": 1,
            "is_global": 1,
            "description": "Product color variant"
        },
        {
            "attribute_name": "Size",
            "attribute_type": "Select",
            "display_type": "Button",
            "is_variant_attribute": 1,
            "is_filterable": 1,
            "is_global": 1,
            "description": "Product size variant"
        },
        {
            "attribute_name": "Material",
            "attribute_type": "Select",
            "display_type": "Dropdown",
            "is_variant_attribute": 1,
            "is_filterable": 1,
            "is_global": 1,
            "description": "Product material variant"
        },
        {
            "attribute_name": "Packaging",
            "attribute_type": "Select",
            "display_type": "Dropdown",
            "is_variant_attribute": 0,
            "is_filterable": 0,
            "is_global": 1,
            "description": "Product packaging type"
        }
    ]

    created = []
    for attr_data in standard_attributes:
        if not frappe.db.exists("Product Attribute", attr_data["attribute_name"]):
            attr = frappe.get_doc({
                "doctype": "Product Attribute",
                **attr_data
            })
            attr.insert(ignore_permissions=True)
            created.append(attr.name)

    frappe.db.commit()

    return {"created": created, "count": len(created)}
