# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tag Assignment DocType Controller

Manages seller-tag relationships with manual override support.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SellerTagAssignment(Document):
    """
    Controller for Seller Tag Assignment DocType.

    Links sellers to tags, tracks assignment source and overrides.
    Priority: Manual > Rule
    """

    def before_insert(self):
        """Set initial values."""
        if not self.assigned_at:
            self.assigned_at = now_datetime()

        if self.source == "Manual" and not self.assigned_by:
            self.assigned_by = frappe.session.user

    def validate(self):
        """Validate assignment data."""
        self.check_duplicate()
        self.validate_override()

    def check_duplicate(self):
        """Check for duplicate assignments."""
        existing = frappe.db.exists(
            "Seller Tag Assignment",
            {
                "seller": self.seller,
                "tag": self.tag,
                "name": ["!=", self.name]
            }
        )
        if existing:
            frappe.throw(
                _("Tag '{0}' is already assigned to this seller").format(self.tag)
            )

    def validate_override(self):
        """Validate override state logic."""
        if self.override_state == "ForcedOff" and self.source == "Manual":
            frappe.throw(
                _("Cannot set ForcedOff override on manual assignments. "
                  "Delete the assignment instead.")
            )

        if self.override_state == "ForcedOn" and self.source == "Rule":
            # This is valid - keeps the tag even if rule no longer matches
            pass

    def on_update(self):
        """Handle assignment updates."""
        # Update tag assignment count
        self.update_tag_stats()

    def on_trash(self):
        """Handle assignment deletion."""
        # Check if forced on
        if self.override_state == "ForcedOn":
            frappe.throw(
                _("Cannot delete a ForcedOn assignment. "
                  "Set override to None first.")
            )

    def update_tag_stats(self):
        """Update statistics on the tag."""
        # This could trigger recalculation of tag statistics
        pass

    @frappe.whitelist()
    def set_override(self, override_state):
        """
        Set the override state for this assignment.

        Args:
            override_state: "None", "ForcedOn", or "ForcedOff"
        """
        if override_state not in ["None", "ForcedOn", "ForcedOff"]:
            frappe.throw(_("Invalid override state"))

        if override_state == "ForcedOff" and self.source == "Manual":
            frappe.throw(
                _("Cannot force off a manual assignment. Delete it instead.")
            )

        self.override_state = override_state
        self.save(ignore_permissions=True)

        return {"success": True, "override_state": self.override_state}


def assign_tag_to_seller(seller, tag, source="Manual", notes=None):
    """
    Helper function to assign a tag to a seller.

    Args:
        seller: Seller Profile name
        tag: Seller Tag name
        source: "Manual" or "Rule"
        notes: Optional notes

    Returns:
        Seller Tag Assignment document
    """
    # Check if already assigned
    existing = frappe.get_all(
        "Seller Tag Assignment",
        filters={"seller": seller, "tag": tag},
        limit=1
    )

    if existing:
        return frappe.get_doc("Seller Tag Assignment", existing[0].name)

    doc = frappe.get_doc({
        "doctype": "Seller Tag Assignment",
        "seller": seller,
        "tag": tag,
        "source": source,
        "notes": notes
    })
    doc.insert(ignore_permissions=True)

    return doc


def remove_tag_from_seller(seller, tag, force=False):
    """
    Remove a tag from a seller.

    Args:
        seller: Seller Profile name
        tag: Seller Tag name
        force: If True, remove even ForcedOn assignments

    Returns:
        True if removed, False if not found
    """
    assignment = frappe.get_all(
        "Seller Tag Assignment",
        filters={"seller": seller, "tag": tag},
        fields=["name", "override_state"],
        limit=1
    )

    if not assignment:
        return False

    if assignment[0].override_state == "ForcedOn" and not force:
        frappe.throw(_("Cannot remove ForcedOn assignment without force=True"))

    frappe.delete_doc("Seller Tag Assignment", assignment[0].name, ignore_permissions=True)
    return True


def get_seller_tags_with_details(seller):
    """
    Get all tags for a seller with full details.

    Args:
        seller: Seller Profile name

    Returns:
        List of tag assignments with tag details
    """
    assignments = frappe.get_all(
        "Seller Tag Assignment",
        filters={"seller": seller},
        fields=["name", "tag", "source", "override_state", "assigned_at", "expires_at"]
    )

    result = []
    for assignment in assignments:
        tag = frappe.get_doc("Seller Tag", assignment.tag)
        if tag.status != "Active":
            continue

        result.append({
            "assignment_name": assignment.name,
            "tag_name": tag.tag_name,
            "tag_code": tag.tag_code,
            "tag_type": tag.tag_type,
            "badge_icon": tag.badge_icon,
            "badge_color": tag.badge_color,
            "badge_image": tag.badge_image,
            "description": tag.description,
            "source": assignment.source,
            "override_state": assignment.override_state,
            "assigned_at": assignment.assigned_at,
            "expires_at": assignment.expires_at
        })

    # Sort by tag display priority
    return sorted(result, key=lambda x: x.get("display_priority", 10))
