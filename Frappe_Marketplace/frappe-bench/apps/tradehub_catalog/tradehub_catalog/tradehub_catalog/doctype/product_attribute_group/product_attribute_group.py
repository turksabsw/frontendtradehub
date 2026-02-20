# Copyright (c) 2024, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductAttributeGroup(Document):
    """
    Product Attribute Group DocType for organizing product attributes.
    Groups related attributes for display and management.
    """

    def validate(self):
        """Validate group data before save."""
        self.validate_group_name()

    def validate_group_name(self):
        """Ensure group name is properly formatted."""
        if self.group_name:
            self.group_name = self.group_name.strip()

    def before_insert(self):
        """Set default values before inserting."""
        if not self.status:
            self.status = "Active"

    def on_update(self):
        """Clear cache after group update."""
        frappe.cache().delete_key(f"product_attribute_group_{self.name}")
