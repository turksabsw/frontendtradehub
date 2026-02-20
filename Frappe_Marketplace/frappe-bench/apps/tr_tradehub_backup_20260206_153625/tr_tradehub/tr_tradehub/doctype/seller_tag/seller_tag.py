# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tag DocType Controller

Manages tag definitions (badges, achievements) for sellers.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SellerTag(Document):
    """
    Controller for Seller Tag DocType.

    Tags are badges/labels that can be assigned to sellers
    either manually or automatically via rules.
    """

    def before_insert(self):
        """Set initial values."""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.created_at:
            self.created_at = now_datetime()

    def validate(self):
        """Validate tag data."""
        self.validate_tag_code()

    def validate_tag_code(self):
        """Ensure tag code is uppercase and valid."""
        if self.tag_code:
            self.tag_code = self.tag_code.upper().replace(" ", "_")

            # Check for valid characters
            import re
            if not re.match(r'^[A-Z][A-Z0-9_]*$', self.tag_code):
                frappe.throw(
                    _("Tag Code must start with a letter and contain only "
                      "uppercase letters, numbers, and underscores.")
                )

    def on_trash(self):
        """Prevent deletion if tag has assignments."""
        assignments = frappe.db.count(
            "Seller Tag Assignment",
            filters={"tag": self.name}
        )
        if assignments > 0:
            frappe.throw(
                _("Cannot delete tag with {0} existing assignments. "
                  "Remove assignments first or set status to Inactive.").format(assignments)
            )

        rules = frappe.db.count(
            "Seller Tag Rule",
            filters={"target_tag": self.name}
        )
        if rules > 0:
            frappe.throw(
                _("Cannot delete tag with {0} existing rules. "
                  "Remove rules first or set status to Inactive.").format(rules)
            )


def get_active_tags():
    """Get all active tags for display."""
    return frappe.get_all(
        "Seller Tag",
        filters={"status": "Active"},
        fields=["name", "tag_name", "tag_code", "tag_type", "badge_icon",
                "badge_color", "badge_image", "display_priority"],
        order_by="display_priority asc"
    )


def get_seller_tags(seller_id):
    """
    Get all tags assigned to a seller.

    Args:
        seller_id: Seller Profile name

    Returns:
        List of tag details
    """
    assignments = frappe.get_all(
        "Seller Tag Assignment",
        filters={"seller": seller_id},
        fields=["tag"]
    )

    if not assignments:
        return []

    tag_names = [a.tag for a in assignments]

    return frappe.get_all(
        "Seller Tag",
        filters={"name": ["in", tag_names], "status": "Active"},
        fields=["name", "tag_name", "tag_code", "tag_type", "badge_icon",
                "badge_color", "badge_image", "description"],
        order_by="display_priority asc"
    )
