# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class AttributeSet(Document):
    """
    Attribute Set DocType for TR-TradeHub marketplace.

    Attribute Sets group related attributes together and can be
    assigned to product categories to define what specifications
    products in that category should have.

    Features:
    - Group multiple attributes
    - Override attribute settings per category context
    - Inherit attributes from parent attribute sets
    - Define required/optional attributes
    - Control variant and filter behavior
    """

    def validate(self):
        """Validate attribute set data before saving."""
        self.validate_attributes()
        self.validate_inheritance()
        self.set_attribute_labels()

    def on_update(self):
        """Actions after attribute set is updated."""
        self.clear_attribute_set_cache()

    def on_trash(self):
        """Prevent deletion if attribute set is in use."""
        self.check_usage()

    def validate_attributes(self):
        """Validate attribute assignments."""
        if not self.attributes or len(self.attributes) == 0:
            frappe.throw(_("At least one attribute is required"))

        # Check for duplicate attributes
        attribute_names = [attr.attribute for attr in self.attributes]
        if len(attribute_names) != len(set(attribute_names)):
            frappe.throw(_("Duplicate attributes are not allowed in an Attribute Set"))

        # Validate each attribute exists and is active
        for attr in self.attributes:
            attribute = frappe.get_doc("Attribute", attr.attribute)
            if not attribute.is_active:
                frappe.throw(_("Attribute '{0}' is not active").format(attr.attribute))

    def validate_inheritance(self):
        """Validate inheritance settings to prevent circular references."""
        if self.inherit_from:
            # Can't inherit from self
            if self.inherit_from == self.name:
                frappe.throw(_("Attribute Set cannot inherit from itself"))

            # Check for circular inheritance
            visited = set()
            current = self.inherit_from
            while current:
                if current in visited:
                    frappe.throw(_("Circular inheritance detected"))
                if current == self.name:
                    frappe.throw(_("Circular inheritance detected"))
                visited.add(current)
                parent = frappe.db.get_value("Attribute Set", current, "inherit_from")
                current = parent

    def set_attribute_labels(self):
        """Set attribute labels from linked attributes."""
        for attr in self.attributes:
            if not attr.attribute_label:
                attr.attribute_label = frappe.db.get_value(
                    "Attribute", attr.attribute, "attribute_label"
                ) or attr.attribute

    def clear_attribute_set_cache(self):
        """Clear cached attribute set data."""
        frappe.cache().delete_value("all_attribute_sets")
        frappe.cache().delete_value(f"attribute_set:{self.name}")

    def check_usage(self):
        """Check if attribute set is used in any categories."""
        usage_count = frappe.db.count("Category", {"attribute_set": self.name})
        if usage_count:
            frappe.throw(
                _("Cannot delete Attribute Set '{0}' as it is used in {1} Category(ies). "
                  "Remove it from Categories first.").format(self.name, usage_count)
            )

    def get_all_attributes(self, include_inherited=True):
        """
        Get all attributes in this set, optionally including inherited ones.

        Args:
            include_inherited: Whether to include attributes from parent sets

        Returns:
            list: List of attribute dictionaries
        """
        attributes = []
        attribute_names = set()

        # Add own attributes first
        for attr in self.attributes:
            attr_doc = frappe.get_doc("Attribute", attr.attribute)
            attributes.append({
                "attribute": attr.attribute,
                "attribute_name": attr_doc.attribute_name,
                "attribute_label": attr.attribute_label or attr_doc.attribute_label,
                "attribute_type": attr_doc.attribute_type,
                "is_required": cint(attr.is_required),
                "is_variant": cint(attr.is_variant),
                "is_filterable": cint(attr.is_filterable),
                "display_order": attr.display_order,
                "default_value": attr.default_value,
                "source": "direct",
                "values": attr_doc.get_display_values() if attr_doc.attribute_type in ["Select", "Color"] else []
            })
            attribute_names.add(attr.attribute)

        # Add inherited attributes if enabled
        if include_inherited and self.inherit_from and self.auto_include_inherited:
            parent_set = frappe.get_doc("Attribute Set", self.inherit_from)
            parent_attributes = parent_set.get_all_attributes(include_inherited=True)

            for parent_attr in parent_attributes:
                if parent_attr["attribute"] not in attribute_names:
                    parent_attr["source"] = "inherited"
                    attributes.append(parent_attr)
                    attribute_names.add(parent_attr["attribute"])

        # Sort by display order
        attributes.sort(key=lambda x: x["display_order"])

        return attributes

    def get_required_attributes(self):
        """Get list of required attributes in this set."""
        return [
            attr for attr in self.get_all_attributes()
            if attr["is_required"]
        ]

    def get_variant_attributes(self):
        """Get list of variant attributes in this set."""
        return [
            attr for attr in self.get_all_attributes()
            if attr["is_variant"]
        ]

    def get_filterable_attributes(self):
        """Get list of filterable attributes in this set."""
        return [
            attr for attr in self.get_all_attributes()
            if attr["is_filterable"]
        ]

    def validate_product_attributes(self, product_attributes):
        """
        Validate product attribute values against this attribute set.

        Args:
            product_attributes: dict of {attribute_name: value}

        Returns:
            tuple: (is_valid, list of error messages)
        """
        errors = []
        all_attributes = self.get_all_attributes()

        for attr in all_attributes:
            attr_name = attr["attribute"]
            value = product_attributes.get(attr_name)

            # Check required
            if attr["is_required"] and not value:
                errors.append(_("'{0}' is required").format(attr["attribute_label"]))
                continue

            # Validate value if provided
            if value:
                attribute_doc = frappe.get_doc("Attribute", attr_name)
                is_valid, error = attribute_doc.validate_value(value)
                if not is_valid:
                    errors.append(error)

        return len(errors) == 0, errors


@frappe.whitelist()
def get_attribute_set_attributes(attribute_set_name, include_inherited=True):
    """
    Get all attributes for an attribute set.

    Args:
        attribute_set_name: Name of the attribute set
        include_inherited: Whether to include inherited attributes

    Returns:
        list: List of attribute dictionaries
    """
    if not frappe.has_permission("Attribute Set", "read"):
        frappe.throw(_("Not permitted"))

    attribute_set = frappe.get_doc("Attribute Set", attribute_set_name)
    return attribute_set.get_all_attributes(include_inherited=cint(include_inherited))


@frappe.whitelist()
def get_category_attributes(category_name, include_inherited=True):
    """
    Get all attributes for a category based on its attribute set.

    Args:
        category_name: Name of the category
        include_inherited: Whether to include inherited attributes

    Returns:
        list: List of attribute dictionaries, or empty list if no attribute set
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"))

    attribute_set_name = frappe.db.get_value("Category", category_name, "attribute_set")
    if not attribute_set_name:
        return []

    attribute_set = frappe.get_doc("Attribute Set", attribute_set_name)
    return attribute_set.get_all_attributes(include_inherited=cint(include_inherited))


@frappe.whitelist()
def validate_product_attributes(category_name, product_attributes):
    """
    Validate product attributes for a category.

    Args:
        category_name: Name of the category
        product_attributes: JSON string or dict of {attribute_name: value}

    Returns:
        dict: {"valid": bool, "errors": list}
    """
    if not frappe.has_permission("Category", "read"):
        frappe.throw(_("Not permitted"))

    import json
    if isinstance(product_attributes, str):
        product_attributes = json.loads(product_attributes)

    attribute_set_name = frappe.db.get_value("Category", category_name, "attribute_set")
    if not attribute_set_name:
        return {"valid": True, "errors": []}

    attribute_set = frappe.get_doc("Attribute Set", attribute_set_name)
    is_valid, errors = attribute_set.validate_product_attributes(product_attributes)

    return {"valid": is_valid, "errors": errors}


@frappe.whitelist()
def get_all_attribute_sets():
    """
    Get all active attribute sets.

    Returns:
        list: List of attribute set dictionaries
    """
    return frappe.get_all(
        "Attribute Set",
        filters={"is_active": 1},
        fields=["name", "attribute_set_name", "description", "inherit_from"],
        order_by="attribute_set_name asc"
    )
