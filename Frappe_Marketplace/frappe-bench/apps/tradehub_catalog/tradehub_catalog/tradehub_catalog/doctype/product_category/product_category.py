# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Product Category DocType for Trade Hub B2B Marketplace.

This module implements the Product Category DocType with hierarchical tree structure
using Frappe's Nested Set Model (NSM). Categories can be organized in parent-child
relationships allowing for multi-level category trees.

Key Features:
- Tree structure with parent-child relationships
- Multi-tenant support (categories can be global or tenant-specific)
- SEO metadata for category pages
- URL slug generation for SEO-friendly URLs
- Level and path tracking for navigation
"""

import re
import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.nestedset import NestedSet


class ProductCategory(NestedSet):
    """
    Product Category DocType with hierarchical tree structure.

    Extends NestedSet for efficient tree operations (parent-child relationships,
    ancestors, descendants) using Frappe's Nested Set Model implementation.
    """

    # Nested Set Model parent field name
    nsm_parent_field = "parent_product_category"

    def before_insert(self):
        """Set default values before inserting a new category."""
        self.set_level()
        self.generate_url_slug()
        self.set_full_path()

    def validate(self):
        """Validate category data before saving."""
        self.validate_category_name()
        self.validate_parent_category()
        self.validate_tenant_consistency()
        self.validate_circular_reference()
        self.validate_seo_fields()

        # Update computed fields
        self.set_level()
        self.generate_url_slug()
        self.set_full_path()

    def on_update(self):
        """Actions after category is updated."""
        # Update children's full_path if category name changed
        self.update_children_paths()
        # Clear category cache
        self.clear_category_cache()

    def on_trash(self):
        """Prevent deletion of category with products or children."""
        self.check_linked_documents()

    def after_rename(self, old_name, new_name, merge=False):
        """Update related records after category rename."""
        # Update full_path for all descendants
        for child in self.get_descendants():
            child_doc = frappe.get_doc("Product Category", child.name)
            child_doc.set_full_path()
            child_doc.db_update()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_category_name(self):
        """Validate category name is not empty and follows naming conventions."""
        if not self.category_name:
            frappe.throw(_("Category Name is required"))

        # Check for invalid characters
        if any(char in self.category_name for char in ['<', '>', '"', '\\']):
            frappe.throw(_("Category Name contains invalid characters"))

        # Check length
        if len(self.category_name) > 140:
            frappe.throw(_("Category Name cannot exceed 140 characters"))

    def validate_parent_category(self):
        """Validate parent category relationship."""
        if self.parent_product_category:
            # Cannot be its own parent
            if self.parent_product_category == self.name:
                frappe.throw(_("Category cannot be its own parent"))

            # Validate parent exists
            if not frappe.db.exists("Product Category", self.parent_product_category):
                frappe.throw(
                    _("Parent category {0} does not exist").format(
                        self.parent_product_category
                    )
                )

            # Parent must be a group
            parent_is_group = frappe.db.get_value(
                "Product Category",
                self.parent_product_category,
                "is_group"
            )
            if not parent_is_group:
                frappe.throw(
                    _("Parent category {0} must be a group to have children").format(
                        self.parent_product_category
                    )
                )

    def validate_tenant_consistency(self):
        """Ensure tenant consistency in category hierarchy."""
        if self.parent_product_category and not self.is_global:
            parent_tenant = frappe.db.get_value(
                "Product Category",
                self.parent_product_category,
                "tenant"
            )
            parent_is_global = frappe.db.get_value(
                "Product Category",
                self.parent_product_category,
                "is_global"
            )

            # If parent is not global, child must be in same tenant
            if not parent_is_global and parent_tenant:
                if self.tenant and self.tenant != parent_tenant:
                    frappe.throw(
                        _("Category must belong to the same tenant as its parent, "
                          "or parent must be a global category")
                    )

    def validate_circular_reference(self):
        """Prevent circular references in category tree."""
        if not self.parent_product_category:
            return

        # Get all ancestors of the parent
        ancestors = self.get_ancestors()
        if self.name in [a.name for a in ancestors]:
            frappe.throw(
                _("Circular reference detected: category cannot be its own ancestor")
            )

    def validate_seo_fields(self):
        """Validate SEO field lengths."""
        if self.seo_title and len(self.seo_title) > 60:
            frappe.msgprint(
                _("SEO Title exceeds recommended length of 60 characters"),
                indicator="orange"
            )

        if self.seo_description and len(self.seo_description) > 160:
            frappe.msgprint(
                _("SEO Description exceeds recommended length of 160 characters"),
                indicator="orange"
            )

    # =========================================================================
    # COMPUTED FIELD METHODS
    # =========================================================================

    def set_level(self):
        """Calculate and set the level (depth) in the category tree."""
        if not self.parent_product_category:
            self.level = 0
        else:
            parent_level = frappe.db.get_value(
                "Product Category",
                self.parent_product_category,
                "level"
            ) or 0
            self.level = cint(parent_level) + 1

    def generate_url_slug(self):
        """Generate SEO-friendly URL slug from category name."""
        if not self.url_slug and self.category_name:
            # Convert to lowercase and replace special characters
            slug = self.category_name.lower()

            # Turkish character replacements
            turkish_map = {
                'ı': 'i', 'ğ': 'g', 'ü': 'u', 'ş': 's', 'ö': 'o', 'ç': 'c',
                'İ': 'i', 'Ğ': 'g', 'Ü': 'u', 'Ş': 's', 'Ö': 'o', 'Ç': 'c'
            }
            for tr_char, en_char in turkish_map.items():
                slug = slug.replace(tr_char, en_char)

            # Replace spaces and special chars with hyphens
            slug = re.sub(r'[^a-z0-9\-]', '-', slug)
            # Remove consecutive hyphens
            slug = re.sub(r'-+', '-', slug)
            # Remove leading/trailing hyphens
            slug = slug.strip('-')

            # Ensure uniqueness
            base_slug = slug
            counter = 1
            while frappe.db.exists("Product Category", {"url_slug": slug, "name": ("!=", self.name or "")}):
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.url_slug = slug

    def set_full_path(self):
        """Set the full path from root to this category."""
        if not self.parent_product_category:
            self.full_path = self.category_name
        else:
            # Get ancestor names
            ancestors = []
            current_parent = self.parent_product_category
            while current_parent:
                parent_name = frappe.db.get_value(
                    "Product Category",
                    current_parent,
                    "category_name"
                )
                if parent_name:
                    ancestors.insert(0, parent_name)
                current_parent = frappe.db.get_value(
                    "Product Category",
                    current_parent,
                    "parent_product_category"
                )

            ancestors.append(self.category_name)
            self.full_path = " > ".join(ancestors)

    # =========================================================================
    # TREE OPERATIONS
    # =========================================================================

    def get_children(self):
        """
        Get immediate children of this category.

        Returns:
            list: List of child category documents
        """
        return frappe.get_all(
            "Product Category",
            filters={"parent_product_category": self.name},
            fields=["name", "category_name", "is_group", "enabled"],
            order_by="display_order asc, category_name asc"
        )

    def get_descendants(self):
        """
        Get all descendants (children, grandchildren, etc.) of this category.

        Returns:
            list: List of all descendant category documents
        """
        return frappe.get_all(
            "Product Category",
            filters=[
                ["lft", ">", self.lft],
                ["rgt", "<", self.rgt]
            ],
            fields=["name", "category_name", "level", "is_group", "enabled"],
            order_by="lft"
        )

    def get_ancestors(self):
        """
        Get all ancestors (parent, grandparent, etc.) of this category.

        Returns:
            list: List of ancestor category documents from root to parent
        """
        return frappe.get_all(
            "Product Category",
            filters=[
                ["lft", "<", self.lft],
                ["rgt", ">", self.rgt]
            ],
            fields=["name", "category_name", "level", "is_group"],
            order_by="lft"
        )

    def get_breadcrumbs(self):
        """
        Get breadcrumb navigation data for this category.

        Returns:
            list: List of dicts with name, category_name, and url_slug
        """
        breadcrumbs = []
        for ancestor in self.get_ancestors():
            ancestor_doc = frappe.get_doc("Product Category", ancestor.name)
            breadcrumbs.append({
                "name": ancestor_doc.name,
                "category_name": ancestor_doc.category_name,
                "url_slug": ancestor_doc.url_slug
            })
        breadcrumbs.append({
            "name": self.name,
            "category_name": self.category_name,
            "url_slug": self.url_slug
        })
        return breadcrumbs

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for child categories
        children = self.get_children()
        if children:
            frappe.throw(
                _("Cannot delete category with {0} sub-categories. "
                  "Please delete or move sub-categories first.").format(len(children))
            )

        # Check for linked products
        product_count = frappe.db.count("SKU Product", {"category": self.name})
        if product_count > 0:
            frappe.throw(
                _("Cannot delete category with {0} linked product(s). "
                  "Please reassign products to another category first.").format(
                    product_count
                )
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_category_cache(self):
        """Clear cached category data."""
        cache_keys = [
            "category_tree",
            f"category:{self.name}",
            f"category_children:{self.name}",
            f"category_ancestors:{self.name}",
        ]
        if self.tenant:
            cache_keys.append(f"category_tree:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    def update_children_paths(self):
        """Update full_path for all children when category name changes."""
        if self.has_value_changed("category_name"):
            for child in self.get_descendants():
                child_doc = frappe.get_doc("Product Category", child.name)
                child_doc.set_full_path()
                child_doc.db_update()

    # =========================================================================
    # PRODUCT COUNT METHODS
    # =========================================================================

    def get_product_count(self, include_descendants=False):
        """
        Get count of products in this category.

        Args:
            include_descendants: If True, include products from all child categories

        Returns:
            int: Number of products
        """
        if include_descendants:
            # Get products in this category and all descendants
            descendant_names = [d.name for d in self.get_descendants()]
            descendant_names.append(self.name)
            return frappe.db.count(
                "SKU Product",
                filters={"category": ["in", descendant_names], "status": "Active"}
            )
        else:
            return frappe.db.count(
                "SKU Product",
                filters={"category": self.name, "status": "Active"}
            )


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_category_tree(tenant=None, include_disabled=False):
    """
    Get the full category tree structure.

    Args:
        tenant: Optional tenant filter (None = global categories only)
        include_disabled: Include disabled categories

    Returns:
        list: Nested tree structure of categories
    """
    filters = {}
    if not include_disabled:
        filters["enabled"] = 1

    if tenant:
        # Include tenant-specific and global categories
        filters_list = [
            ["tenant", "=", tenant],
            ["is_global", "=", 1]
        ]
        categories = frappe.get_all(
            "Product Category",
            or_filters=filters_list,
            filters=filters,
            fields=[
                "name", "category_name", "parent_product_category",
                "is_group", "level", "image", "url_slug", "display_order"
            ],
            order_by="lft"
        )
    else:
        # Only global categories
        filters["is_global"] = 1
        categories = frappe.get_all(
            "Product Category",
            filters=filters,
            fields=[
                "name", "category_name", "parent_product_category",
                "is_group", "level", "image", "url_slug", "display_order"
            ],
            order_by="lft"
        )

    return build_tree(categories)


def build_tree(categories):
    """
    Build nested tree structure from flat category list.

    Args:
        categories: Flat list of categories

    Returns:
        list: Nested tree structure
    """
    # Create a mapping of name to category with children list
    cat_map = {}
    for cat in categories:
        cat["children"] = []
        cat_map[cat["name"]] = cat

    # Build tree
    tree = []
    for cat in categories:
        parent = cat.get("parent_product_category")
        if parent and parent in cat_map:
            cat_map[parent]["children"].append(cat)
        else:
            tree.append(cat)

    return tree


@frappe.whitelist()
def get_category_breadcrumbs(category_name):
    """
    Get breadcrumb navigation for a category.

    Args:
        category_name: Name of the category

    Returns:
        list: List of breadcrumb items
    """
    if not frappe.db.exists("Product Category", category_name):
        frappe.throw(_("Category {0} not found").format(category_name))

    category = frappe.get_doc("Product Category", category_name)
    return category.get_breadcrumbs()


@frappe.whitelist()
def get_category_products(category_name, include_subcategories=False, limit=20, offset=0):
    """
    Get products in a category.

    Args:
        category_name: Name of the category
        include_subcategories: Include products from child categories
        limit: Number of products to return
        offset: Pagination offset

    Returns:
        dict: Products list and total count
    """
    if not frappe.db.exists("Product Category", category_name):
        frappe.throw(_("Category {0} not found").format(category_name))

    category = frappe.get_doc("Product Category", category_name)

    if include_subcategories:
        category_names = [d.name for d in category.get_descendants()]
        category_names.append(category_name)
        filters = {"category": ["in", category_names], "status": "Active"}
    else:
        filters = {"category": category_name, "status": "Active"}

    total = frappe.db.count("SKU Product", filters=filters)
    products = frappe.get_all(
        "SKU Product",
        filters=filters,
        fields=[
            "name", "sku_code", "product_name", "base_price", "currency",
            "thumbnail", "url_slug", "seller_name"
        ],
        limit_page_length=cint(limit),
        limit_start=cint(offset),
        order_by="modified desc"
    )

    return {
        "products": products,
        "total": total,
        "limit": cint(limit),
        "offset": cint(offset)
    }


@frappe.whitelist()
def get_category_by_slug(slug):
    """
    Get category by URL slug.

    Args:
        slug: The URL slug of the category

    Returns:
        dict: Category data
    """
    category = frappe.db.get_value(
        "Product Category",
        {"url_slug": slug, "enabled": 1},
        ["name", "category_name", "description", "image",
         "seo_title", "seo_description", "seo_keywords",
         "parent_product_category", "is_group", "level"],
        as_dict=True
    )

    if not category:
        frappe.throw(_("Category not found"))

    return category
