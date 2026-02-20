# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RelatedListingProduct(Document):
    """
    Child DocType for storing related product information.
    Used as a child table in Listing DocType for managing related products.

    Relation types:
    - Related: General related products
    - Similar: Similar products in the same category
    - Accessory: Accessories that complement the main product
    - Replacement: Products that can replace the main product
    - Frequently Bought Together: Products often purchased with the main product
    - Customers Also Viewed: Products viewed by customers who viewed the main product
    """

    def validate(self):
        """Validate related product data before saving."""
        self.validate_no_self_reference()
        self.validate_no_duplicate()

    def validate_no_self_reference(self):
        """Ensure product is not referencing itself."""
        if self.parenttype == "Listing" and self.parent == self.product:
            frappe.throw(
                frappe._("A product cannot be related to itself."),
                title=frappe._("Invalid Related Product")
            )

    def validate_no_duplicate(self):
        """Check for duplicate related products in the same parent."""
        if not self.parent or not self.product:
            return

        # Get siblings (other related products in the same parent)
        siblings = [
            row for row in self.get_parent_doc().get("related_products", [])
            if row.name != self.name and row.product == self.product
        ]

        if siblings:
            frappe.throw(
                frappe._("Product {0} is already added as a related product.").format(self.product),
                title=frappe._("Duplicate Related Product")
            )

    def get_parent_doc(self):
        """Get the parent document."""
        if hasattr(self, "_parent_doc"):
            return self._parent_doc
        return frappe.get_doc(self.parenttype, self.parent)
