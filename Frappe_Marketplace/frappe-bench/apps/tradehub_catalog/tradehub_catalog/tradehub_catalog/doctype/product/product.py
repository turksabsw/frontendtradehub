# Copyright (c) 2024, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Product(Document):
    """
    Product DocType for Product Information Management (PIM).
    Represents a master product in the catalog.
    """

    def validate(self):
        """Validate product data before save."""
        self.validate_product_name()
        self.validate_product_code()

    def validate_product_name(self):
        """Ensure product name is properly formatted."""
        if self.product_name:
            self.product_name = self.product_name.strip()

    def validate_product_code(self):
        """Generate product code if not provided."""
        if not self.product_code and self.product_name:
            self.product_code = frappe.scrub(self.product_name).upper()[:20]

    def before_insert(self):
        """Set default values before inserting."""
        if not self.status:
            self.status = "Draft"

    def on_update(self):
        """Clear cache after product update."""
        frappe.cache().delete_key(f"product_{self.name}")
