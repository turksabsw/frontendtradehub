# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PIMAttributeGroup(Document):
    """
    PIM Attribute Group DocType

    Used for organizing and grouping PIM Attributes for better form organization
    and attribute management. Groups can be collapsed in forms and sorted by order.
    """

    def validate(self):
        """Validate the document before saving"""
        self.validate_group_code()
        self.set_defaults()

    def validate_group_code(self):
        """Ensure group_code is lowercase and contains only valid characters"""
        if self.group_code:
            # Convert to lowercase and replace spaces with underscores
            self.group_code = self.group_code.lower().replace(" ", "_")

            # Check for valid characters (alphanumeric and underscore only)
            import re
            if not re.match(r'^[a-z0-9_]+$', self.group_code):
                frappe.throw(
                    _("Group Code can only contain lowercase letters, numbers, and underscores"),
                    title=_("Invalid Group Code")
                )

    def set_defaults(self):
        """Set default values if not provided"""
        if self.sort_order is None:
            self.sort_order = 0

        if self.is_active is None:
            self.is_active = 1

        if self.is_collapsible is None:
            self.is_collapsible = 1

    def before_rename(self, old_name, new_name, merge=False):
        """Handle rename operations"""
        if merge:
            frappe.throw(
                _("Cannot merge PIM Attribute Groups"),
                title=_("Merge Not Allowed")
            )
