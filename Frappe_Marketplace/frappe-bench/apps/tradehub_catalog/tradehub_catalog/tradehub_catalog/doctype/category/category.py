# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.utils.nestedset import NestedSet


class Category(NestedSet):
    """
    Category DocType with hierarchical structure for TR-TradeHub marketplace.

    Categories support:
    - Nested hierarchy (parent/child relationships)
    - Commission rate settings per category
    - SEO metadata for category pages
    - Integration with ERPNext Item Groups
    - Attribute Sets for product specifications
    """

    nsm_parent_field = "parent_category"
    website = frappe._dict()

    def before_insert(self):
        """Actions before inserting a new category."""
        self.generate_route()

    def validate(self):
        """Validate category data before saving."""
        self.validate_commission_rates()
        self.validate_parent_category()
        self.generate_route()

    def on_update(self):
        """Actions after category is updated."""
        super().on_update()
        self.clear_category_cache()
        self.update_children_routes()

    def on_trash(self):
        """Prevent deletion of category with products or children."""
        self.check_linked_documents()
        super().on_trash()

    def validate_commission_rates(self):
        """Validate commission rate settings."""
        if flt(self.commission_rate) < 0:
            frappe.throw(_("Commission Rate cannot be negative"))
        if flt(self.commission_rate) > 100:
            frappe.throw(_("Commission Rate cannot exceed 100%"))

        if flt(self.min_commission) < 0:
            frappe.throw(_("Minimum Commission cannot be negative"))

        if self.max_commission and flt(self.max_commission) < flt(self.min_commission):
            frappe.throw(_("Maximum Commission cannot be less than Minimum Commission"))

        if flt(self.fixed_commission) < 0:
            frappe.throw(_("Fixed Commission cannot be negative"))

    def validate_parent_category(self):
        """Validate parent category assignment."""
        if self.parent_category:
            # Prevent circular references
            if self.parent_category == self.name:
                frappe.throw(_("Category cannot be its own parent"))

            # Check that parent exists and is active
            parent = frappe.get_doc("Category", self.parent_category)
            if not parent.is_active:
                frappe.throw(_("Parent category must be active"))

    def generate_route(self):
        """Generate URL route for category page if not set."""
        if not self.route:
            route_parts = ["shop"]

            # Build path including parent categories
            ancestors = self.get_ancestors()
            for ancestor_name in reversed(ancestors):
                ancestor = frappe.get_cached_doc("Category", ancestor_name)
                route_parts.append(frappe.scrub(ancestor.category_name))

            route_parts.append(frappe.scrub(self.category_name))
            self.route = "/".join(route_parts)

    def update_children_routes(self):
        """Update routes of child categories when parent route changes."""
        children = frappe.get_all(
            "Category",
            filters={"parent_category": self.name},
            pluck="name"
        )
        for child_name in children:
            child = frappe.get_doc("Category", child_name)
            child.route = None  # Force regeneration
            child.save()

    def clear_category_cache(self):
        """Clear cached category data."""
        frappe.cache().delete_value("all_categories")
        frappe.cache().delete_value(f"category:{self.name}")
        frappe.cache().delete_value("category_tree")

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for child categories
        children = frappe.db.count("Category", {"parent_category": self.name})
        if children:
            frappe.throw(
                _("Cannot delete Category with {0} child categories. Please delete or move child categories first.").format(children)
            )

        # Check for linked listings
        listings_count = frappe.db.count("Listing", {"category": self.name})
        if listings_count:
            frappe.throw(
                _("Cannot delete Category with {0} linked listings. Please move or delete listings first.").format(listings_count)
            )

    def get_ancestors(self):
        """Get list of ancestor category names."""
        ancestors = []
        parent = self.parent_category
        while parent:
            ancestors.append(parent)
            parent_doc = frappe.get_cached_doc("Category", parent)
            parent = parent_doc.parent_category
        return ancestors

    def get_descendants(self, include_self=False):
        """Get list of descendant category names."""
        descendants = []
        if include_self:
            descendants.append(self.name)

        children = frappe.get_all(
            "Category",
            filters={"parent_category": self.name},
            pluck="name"
        )

        for child_name in children:
            child = frappe.get_doc("Category", child_name)
            descendants.extend(child.get_descendants(include_self=True))

        return descendants

    def get_effective_commission_rate(self):
        """
        Get effective commission rate for this category.
        Falls back to parent category if not set, or default rate.
        """
        if self.commission_rate and flt(self.commission_rate) > 0:
            return flt(self.commission_rate)

        if self.parent_category:
            parent = frappe.get_cached_doc("Category", self.parent_category)
            return parent.get_effective_commission_rate()

        # Default commission rate
        return flt(frappe.db.get_single_value("TR TradeHub Settings", "default_commission_rate") or 10.0)

    def calculate_commission(self, amount):
        """
        Calculate commission for a given amount.

        Args:
            amount: Transaction amount

        Returns:
            Commission amount after applying rate, min, max, and fixed
        """
        commission_rate = self.get_effective_commission_rate()
        calculated = flt(amount) * flt(commission_rate) / 100

        # Apply minimum commission
        if self.min_commission and calculated < flt(self.min_commission):
            calculated = flt(self.min_commission)

        # Apply maximum commission
        if self.max_commission and calculated > flt(self.max_commission):
            calculated = flt(self.max_commission)

        # Add fixed commission
        if self.fixed_commission:
            calculated += flt(self.fixed_commission)

        return calculated

    def get_product_count(self):
        """Get count of products/listings in this category."""
        return frappe.db.count("Listing", {"category": self.name})

    def get_total_product_count(self):
        """Get count of products in this category and all descendants."""
        categories = self.get_descendants(include_self=True)
        return frappe.db.count("Listing", {"category": ["in", categories]})


@frappe.whitelist()
def get_category_tree(parent=None, include_inactive=False):
    """
    Get category tree structure.

    Args:
        parent: Parent category name (None for root categories)
        include_inactive: Whether to include inactive categories

    Returns:
        list: List of category dictionaries with children
    """
    filters = {"parent_category": parent or ""}
    if not include_inactive:
        filters["is_active"] = 1

    categories = frappe.get_all(
        "Category",
        filters=filters,
        fields=[
            "name", "category_name", "parent_category",
            "is_active", "display_order", "image",
            "commission_rate", "route"
        ],
        order_by="display_order asc, category_name asc"
    )

    for category in categories:
        category["children"] = get_category_tree(
            parent=category["name"],
            include_inactive=include_inactive
        )
        category["product_count"] = frappe.db.count(
            "Listing",
            {"category": category["name"]}
        )
        category["expandable"] = bool(category["children"])

    return categories


@frappe.whitelist()
def get_category_path(category_name):
    """
    Get breadcrumb path for a category.

    Args:
        category_name: Name of the category

    Returns:
        list: List of category dictionaries from root to current
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"))

    path = []
    current = category_name

    while current:
        category = frappe.get_cached_doc("Category", current)
        path.append({
            "name": category.name,
            "category_name": category.category_name,
            "route": category.route
        })
        current = category.parent_category

    return list(reversed(path))


@frappe.whitelist()
def get_all_categories_flat(include_inactive=False):
    """
    Get all categories as a flat list with hierarchy info.

    Args:
        include_inactive: Whether to include inactive categories

    Returns:
        list: List of category dictionaries with level info
    """
    filters = {}
    if not include_inactive:
        filters["is_active"] = 1

    categories = frappe.get_all(
        "Category",
        filters=filters,
        fields=[
            "name", "category_name", "parent_category",
            "is_active", "display_order", "commission_rate",
            "lft", "rgt"
        ],
        order_by="lft asc"
    )

    # Calculate levels based on lft/rgt
    for category in categories:
        ancestors = frappe.db.count(
            "Category",
            {"lft": ["<", category["lft"]], "rgt": [">", category["rgt"]]}
        )
        category["level"] = ancestors
        category["indent_label"] = "—" * category["level"] + " " + category["category_name"] if category["level"] > 0 else category["category_name"]

    return categories


@frappe.whitelist()
def move_category(category_name, new_parent):
    """
    Move a category to a new parent.

    Args:
        category_name: Name of category to move
        new_parent: Name of new parent category (or empty for root)
    """
    if not frappe.has_permission("Category", "write"):
        frappe.throw(_("Not permitted"))

    category = frappe.get_doc("Category", category_name)

    # Validate new parent
    if new_parent and new_parent in category.get_descendants():
        frappe.throw(_("Cannot move category under its own descendant"))

    category.parent_category = new_parent if new_parent else ""
    category.route = None  # Force route regeneration
    category.save()

    return {"success": True, "message": _("Category moved successfully")}
