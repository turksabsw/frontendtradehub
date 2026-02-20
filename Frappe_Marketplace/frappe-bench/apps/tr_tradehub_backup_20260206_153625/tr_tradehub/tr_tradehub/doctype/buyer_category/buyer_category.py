# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet
from frappe.utils import now_datetime, cint, flt


class BuyerCategory(NestedSet):
    """
    Buyer Category DocType for classifying and categorizing buyers.
    Supports hierarchical organization via Nested Set Model (tree structure).
    """
    nsm_parent_field = "parent_buyer_category"

    def validate(self):
        """Validate the buyer category before saving."""
        self.validate_category_name()
        self.validate_category_code()
        self.validate_default_category()
        self.validate_qualification_criteria()
        self.validate_benefits()
        self.set_display_name()

    def validate_category_name(self):
        """Ensure category name is not empty and follows naming conventions."""
        if not self.category_name:
            frappe.throw(_("Category Name is required"))

        # Trim whitespace
        self.category_name = self.category_name.strip()

        if len(self.category_name) < 2:
            frappe.throw(_("Category Name must be at least 2 characters long"))

        if len(self.category_name) > 140:
            frappe.throw(_("Category Name must not exceed 140 characters"))

    def validate_category_code(self):
        """Validate and format category code."""
        if self.category_code:
            # Auto-format: uppercase, no spaces, alphanumeric with underscores
            self.category_code = self.category_code.strip().upper().replace(" ", "_")

            # Validate format
            import re
            if not re.match(r'^[A-Z][A-Z0-9_]*$', self.category_code):
                frappe.throw(_("Category Code must start with a letter and contain only letters, numbers, and underscores"))

            # Check uniqueness (excluding self)
            if frappe.db.exists("Buyer Category", {
                "category_code": self.category_code,
                "name": ("!=", self.name)
            }):
                frappe.throw(_("Category Code '{0}' already exists").format(self.category_code))

    def validate_default_category(self):
        """Ensure only one default category exists."""
        if self.is_default:
            # Check if another default exists
            existing_default = frappe.db.get_value(
                "Buyer Category",
                {"is_default": 1, "name": ("!=", self.name)},
                "name"
            )
            if existing_default:
                frappe.throw(
                    _("Default category already exists: {0}. Please unset it first.").format(existing_default)
                )

    def validate_qualification_criteria(self):
        """Validate qualification criteria based on qualification type."""
        if self.qualification_type == "Purchase Amount" and self.auto_assign:
            if not self.min_order_amount or flt(self.min_order_amount) <= 0:
                frappe.throw(_("Minimum Order Amount must be greater than 0 for Purchase Amount qualification type"))

        if self.qualification_type == "Order Count" and self.auto_assign:
            if not self.min_order_count or cint(self.min_order_count) <= 0:
                frappe.throw(_("Minimum Order Count must be greater than 0 for Order Count qualification type"))

        if self.qualification_type == "Industry" and self.auto_assign:
            if not self.industry_tags:
                frappe.throw(_("Industry Tags are required for Industry qualification type"))

    def validate_benefits(self):
        """Validate benefit settings."""
        if self.discount_percentage and (flt(self.discount_percentage) < 0 or flt(self.discount_percentage) > 100):
            frappe.throw(_("Discount percentage must be between 0 and 100"))

        if self.extended_credit_days and cint(self.extended_credit_days) < 0:
            frappe.throw(_("Extended Credit Days cannot be negative"))

    def set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.category_name

    def on_update(self):
        """After saving, update related caches."""
        super().on_update()
        self.clear_cache()

    def on_trash(self):
        """Before deletion, check for dependencies."""
        super().on_trash()
        self.check_if_has_buyers()
        self.check_if_has_children()

    def check_if_has_buyers(self):
        """Prevent deletion if buyers are assigned to this category."""
        buyer_count = frappe.db.count("Buyer Profile", {"buyer_category": self.name})
        if buyer_count > 0:
            frappe.throw(
                _("Cannot delete category '{0}' as it has {1} buyer(s) assigned. Please reassign them first.").format(
                    self.category_name, buyer_count
                )
            )

    def check_if_has_children(self):
        """Prevent deletion if category has child categories."""
        children = frappe.db.get_all(
            "Buyer Category",
            filters={"parent_buyer_category": self.name},
            pluck="name"
        )
        if children:
            frappe.throw(
                _("Cannot delete category '{0}' as it has child categories: {1}").format(
                    self.category_name, ", ".join(children)
                )
            )

    def clear_cache(self):
        """Clear any cached data related to buyer categories."""
        frappe.cache().delete_value("buyer_categories")
        frappe.cache().delete_value(f"buyer_category_{self.name}")

    def get_children(self):
        """Get all direct child categories."""
        return frappe.get_all(
            "Buyer Category",
            filters={"parent_buyer_category": self.name},
            fields=["name", "category_name", "category_code", "status", "display_order", "icon"],
            order_by="display_order asc"
        )

    def get_all_descendants(self):
        """Get all descendant categories (children, grandchildren, etc.)."""
        descendants = []
        children = self.get_children()
        for child in children:
            descendants.append(child)
            child_doc = frappe.get_doc("Buyer Category", child.name)
            descendants.extend(child_doc.get_all_descendants())
        return descendants

    def get_ancestors(self):
        """Get all ancestor categories up to root."""
        ancestors = []
        current = self
        while current.parent_buyer_category:
            parent = frappe.get_doc("Buyer Category", current.parent_buyer_category)
            ancestors.append({
                "name": parent.name,
                "category_name": parent.category_name,
                "category_code": parent.category_code
            })
            current = parent
        return list(reversed(ancestors))

    def get_full_path(self):
        """Get full category path from root to current."""
        ancestors = self.get_ancestors()
        path = [a["category_name"] for a in ancestors]
        path.append(self.category_name)
        return " > ".join(path)

    def is_leaf(self):
        """Check if this is a leaf category (no children)."""
        return not frappe.db.exists("Buyer Category", {"parent_buyer_category": self.name})

    def get_benefits_summary(self):
        """Get a summary of category benefits."""
        benefits = []
        if self.discount_percentage:
            benefits.append(_("{0}% Discount").format(self.discount_percentage))
        if self.priority_support:
            benefits.append(_("Priority Support"))
        if self.dedicated_account_manager:
            benefits.append(_("Dedicated Account Manager"))
        if self.custom_payment_terms:
            benefits.append(_("Custom Payment Terms"))
        if self.extended_credit_days:
            benefits.append(_("{0} Extra Credit Days").format(self.extended_credit_days))
        return benefits

    def update_buyer_count(self):
        """Update the count of buyers in this category."""
        count = frappe.db.count("Buyer Profile", {"buyer_category": self.name})
        self.db_set("buyer_count", count, update_modified=False)
        self.db_set("last_calculated_at", now_datetime(), update_modified=False)

    def evaluate_buyer(self, buyer_profile):
        """
        Evaluate if a buyer qualifies for this category.

        Args:
            buyer_profile: Buyer Profile document or name

        Returns:
            bool: True if buyer qualifies, False otherwise
        """
        if not self.auto_assign:
            return False

        if isinstance(buyer_profile, str):
            buyer_profile = frappe.get_doc("Buyer Profile", buyer_profile)

        if self.qualification_type == "Purchase Amount":
            # Get total purchase amount
            total_amount = frappe.db.sql("""
                SELECT COALESCE(SUM(grand_total), 0) as total
                FROM `tabMarketplace Order`
                WHERE buyer = %s AND docstatus = 1
            """, buyer_profile.user, as_dict=True)[0].total
            return flt(total_amount) >= flt(self.min_order_amount)

        elif self.qualification_type == "Order Count":
            # Get total order count
            order_count = frappe.db.count(
                "Marketplace Order",
                {"buyer": buyer_profile.user, "docstatus": 1}
            )
            return cint(order_count) >= cint(self.min_order_count)

        elif self.qualification_type == "Industry":
            # Check if buyer's industry matches any tag
            if not self.industry_tags:
                return False
            tags = [t.strip().lower() for t in self.industry_tags.split(",")]
            buyer_industry = (buyer_profile.get("industry") or "").lower()
            return buyer_industry in tags

        return False


@frappe.whitelist()
def get_children(doctype, parent=None, is_root=False, **kwargs):
    """
    Get child categories for tree view.
    Used by Frappe's tree view component.
    """
    if parent and parent != "All Buyer Categories":
        filters = {"parent_buyer_category": parent}
    else:
        filters = {"parent_buyer_category": ("is", "not set")}

    categories = frappe.get_all(
        "Buyer Category",
        filters=filters,
        fields=[
            "name as value",
            "category_name as title",
            "category_code",
            "status",
            "icon",
            "icon_color",
            "is_default",
            "buyer_count",
            "parent_buyer_category as parent"
        ],
        order_by="display_order asc, category_name asc"
    )

    # Add expandable flag based on whether category has children
    for cat in categories:
        cat["expandable"] = frappe.db.exists(
            "Buyer Category",
            {"parent_buyer_category": cat["value"]}
        )

    return categories


@frappe.whitelist()
def add_node():
    """Add a new category node in tree view."""
    from frappe.desk.treeview import make_tree_args
    args = make_tree_args(**frappe.form_dict)

    if args.parent_buyer_category == "All Buyer Categories":
        args.parent_buyer_category = None

    doc = frappe.get_doc({
        "doctype": "Buyer Category",
        "category_name": args.category_name,
        "parent_buyer_category": args.parent_buyer_category
    })
    doc.insert()

    return doc.name


@frappe.whitelist()
def get_buyer_category(category_name):
    """Get buyer category details by name."""
    if not frappe.db.exists("Buyer Category", category_name):
        frappe.throw(_("Buyer Category '{0}' not found").format(category_name))

    return frappe.get_doc("Buyer Category", category_name)


@frappe.whitelist()
def get_default_category():
    """Get the default buyer category."""
    default = frappe.db.get_value(
        "Buyer Category",
        {"is_default": 1, "status": "Active"},
        ["name", "category_name", "category_code"],
        as_dict=True
    )
    return default


@frappe.whitelist()
def get_all_categories(status=None, include_inactive=False):
    """
    Get all buyer categories.

    Args:
        status: Filter by status (Active, Inactive, Deprecated)
        include_inactive: Include inactive categories

    Returns:
        List of buyer categories
    """
    filters = {}
    if status:
        filters["status"] = status
    elif not include_inactive:
        filters["status"] = "Active"

    return frappe.get_all(
        "Buyer Category",
        filters=filters,
        fields=[
            "name", "category_name", "category_code", "parent_buyer_category",
            "status", "icon", "icon_color", "display_name", "description",
            "buyer_count", "display_order", "is_default"
        ],
        order_by="display_order asc, category_name asc"
    )


@frappe.whitelist()
def get_category_tree():
    """
    Get complete category tree structure.

    Returns:
        Hierarchical dict of categories
    """
    def build_tree(parent=None):
        filters = {"status": "Active"}
        if parent:
            filters["parent_buyer_category"] = parent
        else:
            filters["parent_buyer_category"] = ("is", "not set")

        categories = frappe.get_all(
            "Buyer Category",
            filters=filters,
            fields=["name", "category_name", "category_code", "icon", "icon_color", "buyer_count"],
            order_by="display_order asc"
        )

        for cat in categories:
            cat["children"] = build_tree(cat["name"])

        return categories

    return build_tree()


@frappe.whitelist()
def get_categories_for_registration():
    """Get categories that can be selected during buyer registration."""
    return frappe.get_all(
        "Buyer Category",
        filters={
            "status": "Active",
            "show_in_registration": 1,
            "is_public": 1
        },
        fields=[
            "name", "category_name", "category_code", "display_name",
            "public_description", "icon", "icon_color", "badge_text",
            "requires_approval"
        ],
        order_by="display_order asc"
    )


@frappe.whitelist()
def evaluate_buyer_for_categories(buyer_profile):
    """
    Evaluate which categories a buyer qualifies for.

    Args:
        buyer_profile: Buyer Profile document name

    Returns:
        List of qualified category names
    """
    qualified = []
    categories = frappe.get_all(
        "Buyer Category",
        filters={"status": "Active", "auto_assign": 1},
        pluck="name"
    )

    for cat_name in categories:
        cat_doc = frappe.get_doc("Buyer Category", cat_name)
        if cat_doc.evaluate_buyer(buyer_profile):
            qualified.append({
                "name": cat_name,
                "category_name": cat_doc.category_name,
                "category_code": cat_doc.category_code
            })

    return qualified


@frappe.whitelist()
def update_all_buyer_counts():
    """Update buyer counts for all categories."""
    categories = frappe.get_all("Buyer Category", pluck="name")
    for cat_name in categories:
        cat_doc = frappe.get_doc("Buyer Category", cat_name)
        cat_doc.update_buyer_count()

    frappe.msgprint(_("Updated buyer counts for {0} categories").format(len(categories)))


def get_buyer_category_permission_query(user):
    """
    Permission query for buyer category access.
    System Manager can access all, others can only view active public categories.
    """
    if "System Manager" in frappe.get_roles(user):
        return ""

    # All users can view active public categories
    return "`tabBuyer Category`.status = 'Active' AND `tabBuyer Category`.is_public = 1"
