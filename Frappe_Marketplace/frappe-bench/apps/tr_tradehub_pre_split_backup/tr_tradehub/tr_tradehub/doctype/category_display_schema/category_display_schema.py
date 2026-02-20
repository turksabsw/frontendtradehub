# -*- coding: utf-8 -*-
# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CategoryDisplaySchema(Document):
    """
    Category Display Schema DocType

    Defines how products are displayed within category listing pages.
    Controls view type, grid layout, display options, filters, and sorting.
    """

    def validate(self):
        """Validate schema settings before save"""
        self.validate_schema_name()
        self.validate_default_schema()
        self.validate_columns()
        self.validate_items_per_page()
        self.validate_filters()
        self.validate_sort_options()

    def validate_schema_name(self):
        """Validate schema name is not empty and properly formatted"""
        if not self.schema_name:
            frappe.throw(_("Schema Name is required"))

        # Clean schema name
        self.schema_name = self.schema_name.strip()

        if len(self.schema_name) < 3:
            frappe.throw(_("Schema Name must be at least 3 characters long"))

    def validate_default_schema(self):
        """Ensure only one default schema exists"""
        if self.is_default:
            # Check if another default exists
            existing_default = frappe.db.get_value(
                "Category Display Schema",
                {"is_default": 1, "name": ("!=", self.name)},
                "name"
            )
            if existing_default:
                frappe.msgprint(
                    _("Removing default status from '{0}' as only one default schema is allowed").format(existing_default)
                )
                frappe.db.set_value("Category Display Schema", existing_default, "is_default", 0)

    def validate_columns(self):
        """Validate column settings are reasonable"""
        if self.view_type in ["Grid", "Card", "Masonry"]:
            desktop = int(self.desktop_columns or 4)
            tablet = int(self.tablet_columns or 3)
            mobile = int(self.mobile_columns or 2)

            if desktop < tablet:
                frappe.msgprint(
                    _("Desktop columns ({0}) should typically be greater than or equal to tablet columns ({1})").format(
                        desktop, tablet
                    ),
                    indicator="orange"
                )

            if tablet < mobile:
                frappe.msgprint(
                    _("Tablet columns ({0}) should typically be greater than or equal to mobile columns ({1})").format(
                        tablet, mobile
                    ),
                    indicator="orange"
                )

    def validate_items_per_page(self):
        """Validate items per page is reasonable"""
        items = int(self.items_per_page or 24)

        if items < 1:
            frappe.throw(_("Items Per Page must be at least 1"))

        if items > 100:
            frappe.msgprint(
                _("Items Per Page ({0}) is quite high and may affect page load performance").format(items),
                indicator="orange"
            )

    def validate_filters(self):
        """Validate filter configuration"""
        if self.show_filters and self.available_filters:
            filters = [f.strip() for f in self.available_filters.split(",") if f.strip()]

            # Valid filter fields
            valid_filters = [
                "price", "brand", "color", "size", "category", "seller",
                "rating", "condition", "availability", "discount",
                "material", "warranty", "shipping", "location"
            ]

            invalid_filters = [f for f in filters if f not in valid_filters]
            if invalid_filters:
                frappe.msgprint(
                    _("Unrecognized filters: {0}. These may not work as expected.").format(
                        ", ".join(invalid_filters)
                    ),
                    indicator="orange"
                )

    def validate_sort_options(self):
        """Validate sort configuration"""
        if self.show_sort and self.available_sort_options:
            options = [o.strip() for o in self.available_sort_options.split(",") if o.strip()]

            # Valid sort options
            valid_options = [
                "relevance", "price_low", "price_high", "newest", "oldest",
                "rating", "best_selling", "name_asc", "name_desc",
                "discount", "popularity", "reviews"
            ]

            invalid_options = [o for o in options if o not in valid_options]
            if invalid_options:
                frappe.msgprint(
                    _("Unrecognized sort options: {0}. These may not work as expected.").format(
                        ", ".join(invalid_options)
                    ),
                    indicator="orange"
                )

            # Ensure default sort is in available options
            if self.default_sort_field and options and self.default_sort_field not in options:
                frappe.msgprint(
                    _("Default sort field '{0}' is not in available sort options. Adding it.").format(
                        self.default_sort_field
                    ),
                    indicator="orange"
                )
                options.insert(0, self.default_sort_field)
                self.available_sort_options = ", ".join(options)

    def before_save(self):
        """Auto-set fields before save"""
        # Clean up filter and sort option lists
        if self.available_filters:
            filters = [f.strip() for f in self.available_filters.split(",") if f.strip()]
            self.available_filters = ", ".join(filters)

        if self.available_sort_options:
            options = [o.strip() for o in self.available_sort_options.split(",") if o.strip()]
            self.available_sort_options = ", ".join(options)

        # Clean up category list
        if self.specific_categories:
            categories = [c.strip() for c in self.specific_categories.split(",") if c.strip()]
            self.specific_categories = ", ".join(categories)

    def get_display_config(self):
        """
        Get the complete display configuration as a dictionary

        Returns:
            dict: Display configuration suitable for frontend rendering
        """
        return {
            "schema_name": self.schema_name,
            "view_type": self.view_type,
            "template": self.template,
            "pagination": {
                "items_per_page": self.items_per_page,
                "enable_pagination": self.enable_pagination,
                "infinite_scroll": self.infinite_scroll
            },
            "grid": {
                "desktop_columns": int(self.desktop_columns or 4),
                "tablet_columns": int(self.tablet_columns or 3),
                "mobile_columns": int(self.mobile_columns or 2),
                "gap": self.grid_gap,
                "card_style": self.card_style
            },
            "display": {
                "show_image": self.show_image,
                "image_position": self.image_position,
                "image_aspect_ratio": self.image_aspect_ratio,
                "show_title": self.show_title,
                "show_description": self.show_description,
                "description_lines": self.description_lines,
                "show_price": self.show_price,
                "show_original_price": self.show_original_price,
                "show_discount_badge": self.show_discount_badge,
                "show_seller": self.show_seller,
                "show_rating": self.show_rating,
                "show_stock_status": self.show_stock_status,
                "show_category_badge": self.show_category_badge,
                "show_quick_view": self.show_quick_view,
                "show_add_to_cart": self.show_add_to_cart,
                "show_wishlist": self.show_wishlist,
                "show_compare": self.show_compare,
                "show_sku": self.show_sku
            },
            "filters": {
                "show_filters": self.show_filters,
                "filter_position": self.filter_position,
                "collapsible_filters": self.collapsible_filters,
                "available_filters": self.get_filter_list(),
                "max_filter_options": self.max_filter_options
            },
            "sort": {
                "show_sort": self.show_sort,
                "default_sort_field": self.default_sort_field,
                "default_sort_order": self.default_sort_order,
                "available_sort_options": self.get_sort_list()
            },
            "custom": {
                "css": self.custom_css,
                "js": self.custom_js
            }
        }

    def get_filter_list(self):
        """Get available filters as a list"""
        if not self.available_filters:
            return ["price", "brand", "rating", "availability"]
        return [f.strip() for f in self.available_filters.split(",") if f.strip()]

    def get_sort_list(self):
        """Get available sort options as a list"""
        if not self.available_sort_options:
            return ["relevance", "price_low", "price_high", "newest", "rating"]
        return [o.strip() for o in self.available_sort_options.split(",") if o.strip()]

    def applies_to_category(self, category_name):
        """
        Check if this schema applies to a specific category

        Args:
            category_name: Name of the category to check

        Returns:
            bool: True if this schema applies to the category
        """
        if not self.is_active:
            return False

        if self.apply_to_all_categories:
            return True

        if not self.specific_categories:
            return False

        categories = [c.strip() for c in self.specific_categories.split(",")]

        if category_name in categories:
            return True

        # Check if parent category matches and inherit_to_children is enabled
        if self.inherit_to_children:
            category_doc = frappe.get_doc("Category", category_name)
            ancestors = category_doc.get_ancestors() if hasattr(category_doc, 'get_ancestors') else []
            for ancestor in ancestors:
                if ancestor in categories:
                    return True

        return False


@frappe.whitelist()
def get_schema_for_category(category_name):
    """
    Get the appropriate display schema for a category

    Args:
        category_name: Name of the category

    Returns:
        dict: Display configuration for the category
    """
    # First, check if category has a direct schema link
    category_schema = frappe.db.get_value("Category", category_name, "display_schema")
    if category_schema:
        schema_doc = frappe.get_doc("Category Display Schema", category_schema)
        if schema_doc.is_active:
            return schema_doc.get_display_config()

    # Find applicable schemas sorted by priority
    schemas = frappe.get_all(
        "Category Display Schema",
        filters={"is_active": 1},
        fields=["name", "priority", "apply_to_all_categories", "specific_categories", "inherit_to_children"],
        order_by="priority desc"
    )

    for schema in schemas:
        schema_doc = frappe.get_doc("Category Display Schema", schema.name)
        if schema_doc.applies_to_category(category_name):
            return schema_doc.get_display_config()

    # Fall back to default schema
    default_schema = frappe.db.get_value(
        "Category Display Schema",
        {"is_default": 1, "is_active": 1},
        "name"
    )

    if default_schema:
        return frappe.get_doc("Category Display Schema", default_schema).get_display_config()

    # Return a basic default configuration
    return get_default_display_config()


@frappe.whitelist()
def get_default_display_config():
    """Get default display configuration when no schema is found"""
    return {
        "schema_name": "Default",
        "view_type": "Grid",
        "template": None,
        "pagination": {
            "items_per_page": 24,
            "enable_pagination": True,
            "infinite_scroll": False
        },
        "grid": {
            "desktop_columns": 4,
            "tablet_columns": 3,
            "mobile_columns": 2,
            "gap": 16,
            "card_style": "Shadow"
        },
        "display": {
            "show_image": True,
            "image_position": "Top",
            "image_aspect_ratio": "1:1",
            "show_title": True,
            "show_description": True,
            "description_lines": 2,
            "show_price": True,
            "show_original_price": True,
            "show_discount_badge": True,
            "show_seller": True,
            "show_rating": True,
            "show_stock_status": True,
            "show_category_badge": False,
            "show_quick_view": True,
            "show_add_to_cart": True,
            "show_wishlist": True,
            "show_compare": False,
            "show_sku": False
        },
        "filters": {
            "show_filters": True,
            "filter_position": "Left",
            "collapsible_filters": True,
            "available_filters": ["price", "brand", "rating", "availability"],
            "max_filter_options": 10
        },
        "sort": {
            "show_sort": True,
            "default_sort_field": "relevance",
            "default_sort_order": "DESC",
            "available_sort_options": ["relevance", "price_low", "price_high", "newest", "rating"]
        },
        "custom": {
            "css": None,
            "js": None
        }
    }


@frappe.whitelist()
def get_all_active_schemas():
    """Get all active display schemas for management UI"""
    schemas = frappe.get_all(
        "Category Display Schema",
        filters={"is_active": 1},
        fields=["name", "schema_name", "view_type", "is_default", "priority", "apply_to_all_categories"],
        order_by="priority desc, schema_name asc"
    )
    return schemas


@frappe.whitelist()
def duplicate_schema(schema_name, new_name):
    """
    Duplicate an existing schema with a new name

    Args:
        schema_name: Name of the schema to duplicate
        new_name: Name for the new schema

    Returns:
        str: Name of the new schema
    """
    if not frappe.has_permission("Category Display Schema", "create"):
        frappe.throw(_("You don't have permission to create Category Display Schema"))

    source = frappe.get_doc("Category Display Schema", schema_name)
    new_doc = frappe.copy_doc(source)
    new_doc.schema_name = new_name
    new_doc.is_default = 0  # Don't copy default status
    new_doc.insert()

    frappe.msgprint(_("Schema '{0}' duplicated as '{1}'").format(schema_name, new_name))
    return new_doc.name
