# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Filter Config DocType for Trade Hub B2B Marketplace.

This module implements the Filter Configuration DocType for defining
category-based dynamic filters. It allows administrators to configure
which filters appear for each product category, their display types,
and SEO-friendly URL parameters.

Key Features:
- Category-based filter configuration
- Multiple filter types (Attribute, Price, Brand, Seller, etc.)
- Flexible display options (Checkbox, Slider, Swatch, etc.)
- SEO-friendly URL parameter generation
- Multi-tenant support (configs can be global or tenant-specific)
- Inheritance to subcategories
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class FilterConfig(Document):
    """
    Filter Config DocType for defining category-based dynamic filters.

    Filter configurations define which filters appear for each product category,
    their display types, and URL parameters. Configurations can inherit to
    subcategories and support multi-tenant isolation.
    """

    def before_insert(self):
        """Set default values before inserting a new configuration."""
        self.set_tenant_from_user()
        self.generate_url_parameter()
        self.set_filter_label()

    def validate(self):
        """Validate configuration data before saving."""
        self.validate_category_requirement()
        self.validate_filter_type_fields()
        self.validate_tenant_consistency()
        self.validate_display_type_compatibility()
        self.validate_range_settings()
        self.generate_url_parameter()
        self.set_filter_label()

    def on_update(self):
        """Actions after configuration is updated."""
        self.clear_filter_cache()

    def on_trash(self):
        """Actions before configuration is deleted."""
        self.clear_filter_cache()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_tenant_from_user(self):
        """Set tenant from current user if not already set."""
        if not self.tenant and not self.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant:
                self.tenant = user_tenant

    def generate_url_parameter(self):
        """Generate URL parameter from filter type and attribute if not provided."""
        if not self.url_parameter:
            if self.filter_type == "Attribute" and self.attribute:
                # Use attribute code as URL parameter
                attr_code = frappe.db.get_value(
                    "Product Attribute", self.attribute, "attribute_code"
                )
                self.url_parameter = attr_code.lower() if attr_code else self.attribute.lower()
            elif self.filter_type == "Price":
                self.url_parameter = "price"
            elif self.filter_type == "Brand":
                self.url_parameter = "brand"
            elif self.filter_type == "Seller":
                self.url_parameter = "seller"
            elif self.filter_type == "Certificate":
                self.url_parameter = "certificate"
            elif self.filter_type == "Rating":
                self.url_parameter = "rating"
            elif self.filter_type == "Stock Status":
                self.url_parameter = "in_stock"
            elif self.filter_type == "Custom Field" and self.source_field:
                # Convert field name to URL-friendly parameter
                self.url_parameter = self.source_field.lower().replace("_", "-")
            else:
                # Fallback to config name slug
                self.url_parameter = self._slugify(self.config_name)

        # Ensure URL parameter is valid
        self.url_parameter = self._slugify(self.url_parameter)

    def set_filter_label(self):
        """Set filter label from attribute name or filter type if not provided."""
        if not self.filter_label:
            if self.filter_type == "Attribute" and self.attribute_name:
                self.filter_label = self.attribute_name
            elif self.filter_type == "Price":
                self.filter_label = _("Price")
            elif self.filter_type == "Brand":
                self.filter_label = _("Brand")
            elif self.filter_type == "Seller":
                self.filter_label = _("Seller")
            elif self.filter_type == "Certificate":
                self.filter_label = _("Certificates")
            elif self.filter_type == "Rating":
                self.filter_label = _("Rating")
            elif self.filter_type == "Stock Status":
                self.filter_label = _("Availability")
            elif self.filter_type == "Custom Field" and self.source_field:
                # Convert field name to label
                self.filter_label = self.source_field.replace("_", " ").title()
            else:
                self.filter_label = self.config_name

    def _slugify(self, text):
        """Convert text to URL-friendly slug."""
        if not text:
            return ""

        slug = text.lower()

        # Turkish character replacements
        turkish_map = {
            'i': 'i', 'g': 'g', 'u': 'u', 's': 's', 'o': 'o', 'c': 'c',
            'I': 'i', 'G': 'g', 'U': 'u', 'S': 's', 'O': 'o', 'C': 'c'
        }
        for tr_char, en_char in turkish_map.items():
            slug = slug.replace(tr_char, en_char)

        # Replace spaces and special chars with hyphens
        slug = re.sub(r'[^a-z0-9_-]', '-', slug)
        # Remove consecutive hyphens
        slug = re.sub(r'-+', '-', slug)
        # Remove leading/trailing hyphens
        slug = slug.strip('-')

        return slug

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_category_requirement(self):
        """Validate that category is set unless this is a default config."""
        if not self.is_default and not self.category:
            frappe.throw(
                _("Category is required unless marked as default configuration")
            )

        if self.is_default and self.category:
            # Default configs should not have category
            frappe.msgprint(
                _("Default configurations apply to all categories. "
                  "Category field will be ignored."),
                indicator="blue"
            )

    def validate_filter_type_fields(self):
        """Validate that required fields are set for each filter type."""
        if self.filter_type == "Attribute" and not self.attribute:
            frappe.throw(_("Product Attribute is required for Attribute filter type"))

        if self.filter_type == "Custom Field" and not self.source_field:
            frappe.throw(_("Source Field is required for Custom Field filter type"))

    def validate_tenant_consistency(self):
        """Ensure tenant consistency for configurations."""
        # Global configs should not have tenant
        if self.is_global and self.tenant:
            self.tenant = None
            self.tenant_name = None

        # Non-global configs need tenant
        if not self.is_global and not self.tenant:
            # Only admin can create global configs
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Please select a tenant or mark the configuration as global")
                )

    def validate_display_type_compatibility(self):
        """Validate display type is compatible with filter type."""
        # Define compatible display types for each filter type
        compatibility_map = {
            "Attribute": [
                "Checkbox", "Radio Button", "Dropdown", "Multi-Select Dropdown",
                "Color Swatch", "Image Swatch", "Button Group", "Text Search"
            ],
            "Price": ["Range Slider", "Price Range", "Checkbox"],
            "Brand": ["Checkbox", "Dropdown", "Multi-Select Dropdown", "Text Search"],
            "Seller": ["Checkbox", "Dropdown", "Multi-Select Dropdown", "Text Search"],
            "Certificate": ["Checkbox", "Multi-Select Dropdown"],
            "Rating": ["Checkbox", "Radio Button", "Button Group"],
            "Stock Status": ["Checkbox", "Radio Button"],
            "Custom Field": [
                "Checkbox", "Radio Button", "Dropdown", "Multi-Select Dropdown",
                "Range Slider", "Text Search"
            ]
        }

        valid_types = compatibility_map.get(self.filter_type, [])
        if self.display_type not in valid_types:
            # Auto-correct to default display type
            default_types = {
                "Attribute": "Checkbox",
                "Price": "Price Range",
                "Brand": "Checkbox",
                "Seller": "Checkbox",
                "Certificate": "Checkbox",
                "Rating": "Checkbox",
                "Stock Status": "Checkbox",
                "Custom Field": "Checkbox"
            }
            self.display_type = default_types.get(self.filter_type, "Checkbox")
            frappe.msgprint(
                _("Display type adjusted to {0} for {1} filter type").format(
                    self.display_type, self.filter_type
                ),
                indicator="blue"
            )

    def validate_range_settings(self):
        """Validate range settings for slider display types."""
        if self.display_type in ["Range Slider", "Price Range"]:
            # Validate min/max if both set
            if self.min_value is not None and self.max_value is not None:
                if self.min_value >= self.max_value:
                    frappe.throw(
                        _("Minimum value must be less than maximum value")
                    )

            # Ensure step value is positive
            if self.step_value is not None and self.step_value <= 0:
                self.step_value = 1
                frappe.msgprint(
                    _("Step value must be positive. Set to 1."),
                    indicator="blue"
                )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_filter_cache(self):
        """Clear cached filter data."""
        cache_keys = [
            "filter_config_list",
            f"filter_config:{self.name}"
        ]

        if self.category:
            cache_keys.append(f"category_filters:{self.category}")

        if self.tenant:
            cache_keys.append(f"filter_config_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_filter_values(self):
        """
        Get available values for this filter.

        Returns:
            list: List of filter values with counts
        """
        if self.filter_type == "Attribute" and self.attribute:
            return self._get_attribute_values()
        elif self.filter_type == "Brand":
            return self._get_brand_values()
        elif self.filter_type == "Seller":
            return self._get_seller_values()
        elif self.filter_type == "Certificate":
            return self._get_certificate_values()
        elif self.filter_type == "Rating":
            return self._get_rating_values()
        elif self.filter_type == "Stock Status":
            return self._get_stock_status_values()
        elif self.filter_type == "Price":
            return self._get_price_range()
        else:
            return []

    def _get_attribute_values(self):
        """Get values for attribute-based filter."""
        values = frappe.get_all(
            "Product Attribute Value",
            filters={
                "attribute": self.attribute,
                "enabled": 1
            },
            fields=[
                "name", "value_name", "value_code",
                "color_code", "image", "display_order"
            ],
            order_by="display_order asc, value_name asc"
        )
        return values

    def _get_brand_values(self):
        """Get available brands for filter."""
        filters = {"enabled": 1}
        if self.tenant and not self.is_global:
            filters["tenant"] = self.tenant

        return frappe.get_all(
            "Brand",
            filters=filters,
            fields=["name", "brand_name", "logo"],
            order_by="brand_name asc"
        )

    def _get_seller_values(self):
        """Get available sellers for filter."""
        filters = {"verification_status": "Verified"}
        if self.tenant and not self.is_global:
            filters["tenant"] = self.tenant

        return frappe.get_all(
            "Seller Profile",
            filters=filters,
            fields=["name", "seller_name", "company_name"],
            order_by="seller_name asc"
        )

    def _get_certificate_values(self):
        """Get available certificate types for filter."""
        filters = {"enabled": 1}

        return frappe.get_all(
            "Certificate Type",
            filters=filters,
            fields=["name", "certificate_name", "certificate_code"],
            order_by="certificate_name asc"
        )

    def _get_rating_values(self):
        """Get rating options for filter."""
        return [
            {"value": "5", "label": "5 Stars"},
            {"value": "4", "label": "4 Stars & Up"},
            {"value": "3", "label": "3 Stars & Up"},
            {"value": "2", "label": "2 Stars & Up"},
            {"value": "1", "label": "1 Star & Up"}
        ]

    def _get_stock_status_values(self):
        """Get stock status options for filter."""
        return [
            {"value": "in_stock", "label": _("In Stock")},
            {"value": "out_of_stock", "label": _("Out of Stock")}
        ]

    def _get_price_range(self):
        """Get price range for price filter."""
        # Return configured or auto-detected range
        return {
            "min": self.min_value or 0,
            "max": self.max_value or 100000,
            "step": self.step_value or 1,
            "unit": self.unit_label or ""
        }

    def increment_usage_count(self):
        """Increment the usage count for this filter."""
        frappe.db.set_value(
            "Filter Config", self.name, "usage_count",
            cint(self.usage_count) + 1, update_modified=False
        )


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_filters_for_category(category, tenant=None, include_inherited=True):
    """
    Get all filter configurations for a category.

    Args:
        category: Product Category name
        tenant: Optional tenant filter
        include_inherited: Include filters from parent categories

    Returns:
        list: List of filter configurations
    """
    if not frappe.db.exists("Product Category", category):
        frappe.throw(_("Category {0} not found").format(category))

    filters = []
    processed_types = set()

    # Get direct filters for category
    category_filters = _get_category_filters(category, tenant)
    for f in category_filters:
        key = (f.filter_type, f.attribute or f.source_field or "")
        if key not in processed_types:
            filters.append(f)
            processed_types.add(key)

    # Get inherited filters from parent categories
    if include_inherited:
        parent = frappe.db.get_value("Product Category", category, "parent_product_category")
        while parent:
            parent_filters = _get_category_filters(parent, tenant, inherited_only=True)
            for f in parent_filters:
                key = (f.filter_type, f.attribute or f.source_field or "")
                if key not in processed_types:
                    f["inherited_from"] = parent
                    filters.append(f)
                    processed_types.add(key)
            parent = frappe.db.get_value("Product Category", parent, "parent_product_category")

    # Get default filters (apply to all categories)
    default_filters = _get_default_filters(tenant)
    for f in default_filters:
        key = (f.filter_type, f.attribute or f.source_field or "")
        if key not in processed_types:
            f["is_default_filter"] = True
            filters.append(f)
            processed_types.add(key)

    # Sort by display order
    filters.sort(key=lambda x: x.get("display_order", 0))

    return filters


def _get_category_filters(category, tenant=None, inherited_only=False):
    """Get filters for a specific category."""
    base_filters = {
        "category": category,
        "enabled": 1,
        "is_default": 0
    }

    if inherited_only:
        base_filters["apply_to_subcategories"] = 1

    if tenant:
        # Include tenant-specific and global configs
        configs = frappe.get_all(
            "Filter Config",
            or_filters=[
                ["tenant", "=", tenant],
                ["is_global", "=", 1]
            ],
            filters=base_filters,
            fields=[
                "name", "config_name", "filter_type", "filter_source",
                "attribute", "attribute_name", "source_field",
                "filter_label", "display_type", "display_order",
                "collapsed_by_default", "show_count", "max_visible_options",
                "min_value", "max_value", "step_value", "unit_label",
                "url_parameter", "seo_friendly_url", "apply_to_subcategories"
            ],
            order_by="display_order asc"
        )
    else:
        # Only global configs
        base_filters["is_global"] = 1
        configs = frappe.get_all(
            "Filter Config",
            filters=base_filters,
            fields=[
                "name", "config_name", "filter_type", "filter_source",
                "attribute", "attribute_name", "source_field",
                "filter_label", "display_type", "display_order",
                "collapsed_by_default", "show_count", "max_visible_options",
                "min_value", "max_value", "step_value", "unit_label",
                "url_parameter", "seo_friendly_url", "apply_to_subcategories"
            ],
            order_by="display_order asc"
        )

    return configs


def _get_default_filters(tenant=None):
    """Get default filter configurations."""
    base_filters = {
        "is_default": 1,
        "enabled": 1
    }

    if tenant:
        configs = frappe.get_all(
            "Filter Config",
            or_filters=[
                ["tenant", "=", tenant],
                ["is_global", "=", 1]
            ],
            filters=base_filters,
            fields=[
                "name", "config_name", "filter_type", "filter_source",
                "attribute", "attribute_name", "source_field",
                "filter_label", "display_type", "display_order",
                "collapsed_by_default", "show_count", "max_visible_options",
                "min_value", "max_value", "step_value", "unit_label",
                "url_parameter", "seo_friendly_url"
            ],
            order_by="display_order asc"
        )
    else:
        base_filters["is_global"] = 1
        configs = frappe.get_all(
            "Filter Config",
            filters=base_filters,
            fields=[
                "name", "config_name", "filter_type", "filter_source",
                "attribute", "attribute_name", "source_field",
                "filter_label", "display_type", "display_order",
                "collapsed_by_default", "show_count", "max_visible_options",
                "min_value", "max_value", "step_value", "unit_label",
                "url_parameter", "seo_friendly_url"
            ],
            order_by="display_order asc"
        )

    return configs


@frappe.whitelist()
def get_filter_with_values(filter_name):
    """
    Get a filter configuration with all its available values.

    Args:
        filter_name: Name of the filter configuration

    Returns:
        dict: Filter configuration with values list
    """
    if not frappe.db.exists("Filter Config", filter_name):
        frappe.throw(_("Filter configuration {0} not found").format(filter_name))

    config = frappe.get_doc("Filter Config", filter_name)

    # Check tenant permission
    if config.tenant and not config.is_global:
        user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
        if config.tenant != user_tenant:
            frappe.throw(_("Access denied: Tenant isolation violation"))

    return {
        "name": config.name,
        "config_name": config.config_name,
        "filter_type": config.filter_type,
        "filter_label": config.filter_label,
        "display_type": config.display_type,
        "url_parameter": config.url_parameter,
        "collapsed_by_default": config.collapsed_by_default,
        "show_count": config.show_count,
        "max_visible_options": config.max_visible_options,
        "values": config.get_filter_values()
    }


@frappe.whitelist()
def create_standard_filters(category=None, tenant=None):
    """
    Create standard filter configurations (Price, Brand, Rating, Stock).
    Intended to be called during initial setup.

    Args:
        category: Optional category to apply filters to (None = default filters)
        tenant: Optional tenant

    Returns:
        dict: Created configurations
    """
    # Check permission
    if not frappe.has_permission("Filter Config", "create"):
        frappe.throw(_("Insufficient permissions to create filter configurations"))

    standard_filters = [
        {
            "config_name": "Price Filter",
            "filter_type": "Price",
            "display_type": "Price Range",
            "display_order": 1,
            "show_count": 0,
            "url_parameter": "price",
            "unit_label": "USD",
            "is_default": 1 if not category else 0,
            "category": category,
            "is_global": 1 if not tenant else 0,
            "tenant": tenant
        },
        {
            "config_name": "Brand Filter",
            "filter_type": "Brand",
            "display_type": "Checkbox",
            "display_order": 2,
            "show_count": 1,
            "url_parameter": "brand",
            "is_default": 1 if not category else 0,
            "category": category,
            "is_global": 1 if not tenant else 0,
            "tenant": tenant
        },
        {
            "config_name": "Rating Filter",
            "filter_type": "Rating",
            "display_type": "Checkbox",
            "display_order": 3,
            "show_count": 1,
            "url_parameter": "rating",
            "is_default": 1 if not category else 0,
            "category": category,
            "is_global": 1 if not tenant else 0,
            "tenant": tenant
        },
        {
            "config_name": "Stock Status Filter",
            "filter_type": "Stock Status",
            "display_type": "Checkbox",
            "display_order": 4,
            "show_count": 1,
            "url_parameter": "in_stock",
            "is_default": 1 if not category else 0,
            "category": category,
            "is_global": 1 if not tenant else 0,
            "tenant": tenant
        }
    ]

    created = []
    for filter_data in standard_filters:
        # Check if similar filter already exists
        existing = frappe.db.exists(
            "Filter Config",
            {
                "filter_type": filter_data["filter_type"],
                "category": filter_data.get("category"),
                "is_default": filter_data.get("is_default", 0)
            }
        )

        if not existing:
            config = frappe.get_doc({
                "doctype": "Filter Config",
                **filter_data
            })
            config.insert(ignore_permissions=True)
            created.append(config.name)

    frappe.db.commit()

    return {"created": created, "count": len(created)}


@frappe.whitelist()
def create_attribute_filter(attribute, category=None, tenant=None, display_type=None):
    """
    Create a filter configuration for a product attribute.

    Args:
        attribute: Product Attribute name
        category: Optional category (None = default filter)
        tenant: Optional tenant
        display_type: Optional display type (auto-detected if not provided)

    Returns:
        dict: Created configuration
    """
    if not frappe.db.exists("Product Attribute", attribute):
        frappe.throw(_("Product Attribute {0} not found").format(attribute))

    attr_doc = frappe.get_doc("Product Attribute", attribute)

    # Auto-detect display type based on attribute type
    if not display_type:
        type_display_map = {
            "Select": "Checkbox",
            "Multi-Select": "Checkbox",
            "Text": "Text Search",
            "Number": "Range Slider",
            "Boolean": "Checkbox"
        }
        display_type = type_display_map.get(attr_doc.attribute_type, "Checkbox")

        # Use swatches for color attributes
        if attr_doc.display_type in ["Color Swatch", "Image Swatch"]:
            display_type = attr_doc.display_type

    # Check for existing filter
    existing = frappe.db.exists(
        "Filter Config",
        {
            "filter_type": "Attribute",
            "attribute": attribute,
            "category": category,
            "is_default": 1 if not category else 0
        }
    )

    if existing:
        return {"name": existing, "created": False, "message": "Filter already exists"}

    config = frappe.get_doc({
        "doctype": "Filter Config",
        "config_name": f"{attr_doc.attribute_name} Filter",
        "filter_type": "Attribute",
        "attribute": attribute,
        "display_type": display_type,
        "display_order": attr_doc.display_order or 10,
        "show_count": 1,
        "is_default": 1 if not category else 0,
        "category": category,
        "is_global": 1 if not tenant else 0,
        "tenant": tenant
    })
    config.insert()
    frappe.db.commit()

    return {"name": config.name, "created": True}


@frappe.whitelist()
def track_filter_usage(filter_name):
    """
    Track usage of a filter (increment usage count).

    Args:
        filter_name: Name of the filter configuration

    Returns:
        dict: Updated usage count
    """
    if not frappe.db.exists("Filter Config", filter_name):
        return {"success": False, "message": "Filter not found"}

    config = frappe.get_doc("Filter Config", filter_name)
    config.increment_usage_count()

    return {"success": True, "usage_count": cint(config.usage_count) + 1}


@frappe.whitelist()
def get_filter_url_params(category, selected_filters):
    """
    Generate SEO-friendly URL parameters for selected filters.

    Args:
        category: Product Category name
        selected_filters: Dict of filter values {url_param: [values]}

    Returns:
        dict: URL path and query string
    """
    import json

    if isinstance(selected_filters, str):
        selected_filters = json.loads(selected_filters)

    # Get filter configs for the category
    configs = get_filters_for_category(category)

    url_parts = []
    query_params = []

    for config in configs:
        param = config.get("url_parameter")
        if param in selected_filters:
            values = selected_filters[param]
            if not isinstance(values, list):
                values = [values]

            if config.get("seo_friendly_url"):
                # SEO-friendly path segment
                for val in values:
                    url_parts.append(f"{param}-{_slugify_value(val)}")
            else:
                # Query parameter
                for val in values:
                    query_params.append(f"{param}={val}")

    result = {
        "path_segment": "/".join(url_parts) if url_parts else "",
        "query_string": "&".join(query_params) if query_params else ""
    }

    return result


def _slugify_value(value):
    """Convert filter value to URL-friendly slug."""
    if not value:
        return ""

    slug = str(value).lower()

    # Turkish character replacements
    turkish_map = {
        'i': 'i', 'g': 'g', 'u': 'u', 's': 's', 'o': 'o', 'c': 'c'
    }
    for tr_char, en_char in turkish_map.items():
        slug = slug.replace(tr_char, en_char)

    slug = re.sub(r'[^a-z0-9]', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')

    return slug
