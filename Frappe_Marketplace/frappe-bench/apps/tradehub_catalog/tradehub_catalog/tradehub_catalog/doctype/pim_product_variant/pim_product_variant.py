# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PIMProductVariant(Document):
    """
    PIM Product Variant DocType Controller

    Represents a specific variant of a product defined by axis values
    (e.g., Color: Red, Size: XL). Contains variant-specific pricing,
    inventory, dimensions, and marketplace identifiers.
    """

    def before_insert(self):
        """Set defaults before insert"""
        if not self.variant_name:
            self.generate_variant_name()

    def validate(self):
        """Validation hooks"""
        self.validate_variant_code()
        self.validate_identifiers()
        self.validate_pricing()
        self.validate_dimensions()
        self.validate_inventory()
        self.calculate_available_qty()

    def before_save(self):
        """Before save processing"""
        self.update_main_image()
        self.update_stock_status()

    def validate_variant_code(self):
        """Validate variant code format"""
        if not self.variant_code:
            return

        # Allow lowercase, numbers, underscores, and hyphens
        pattern = r'^[a-z0-9_\-]+$'
        if not re.match(pattern, self.variant_code):
            frappe.throw(
                _("Variant Code must contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Variant Code")
            )

        # Minimum length
        if len(self.variant_code) < 3:
            frappe.throw(
                _("Variant Code must be at least 3 characters long"),
                title=_("Invalid Variant Code")
            )

    def validate_identifiers(self):
        """Validate product identifiers format"""
        # GTIN validation (8, 12, 13, or 14 digits)
        if self.gtin:
            gtin_clean = self.gtin.replace(" ", "").replace("-", "")
            if not gtin_clean.isdigit() or len(gtin_clean) not in [8, 12, 13, 14]:
                frappe.throw(
                    _("GTIN must be 8, 12, 13, or 14 digits"),
                    title=_("Invalid GTIN")
                )

    def validate_pricing(self):
        """Validate pricing fields"""
        for field in ['price_override', 'sale_price', 'cost_price', 'compare_at_price']:
            value = getattr(self, field, None)
            if value and flt(value) < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.replace('_', ' ').title()),
                    title=_("Invalid Price")
                )

        # Sale price should be lower than price_override
        if self.sale_price and self.price_override:
            if flt(self.sale_price) > flt(self.price_override):
                frappe.msgprint(
                    _("Sale Price is higher than Price Override. This may not show discount correctly."),
                    indicator="orange"
                )

        # Compare at price should be higher than price_override
        if self.compare_at_price and self.price_override:
            if flt(self.compare_at_price) < flt(self.price_override):
                frappe.msgprint(
                    _("Compare At Price is lower than Price Override. This may not show discount correctly."),
                    indicator="orange"
                )

    def validate_dimensions(self):
        """Validate dimension fields"""
        dimension_fields = [
            'weight', 'length', 'width', 'height',
            'package_weight', 'package_length', 'package_width', 'package_height'
        ]
        for field in dimension_fields:
            value = getattr(self, field, None)
            if value and flt(value) < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.replace('_', ' ').title()),
                    title=_("Invalid Dimension")
                )

    def validate_inventory(self):
        """Validate inventory fields"""
        inventory_fields = ['stock_qty', 'safety_stock', 'reorder_level', 'reserved_qty']
        for field in inventory_fields:
            value = getattr(self, field, None)
            if value and flt(value) < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.replace('_', ' ').title()),
                    title=_("Invalid Inventory")
                )

        # Reorder level should be >= safety stock
        if self.reorder_level and self.safety_stock:
            if flt(self.reorder_level) < flt(self.safety_stock):
                frappe.msgprint(
                    _("Reorder Level is lower than Safety Stock. This may not trigger reorder correctly."),
                    indicator="orange"
                )

    def calculate_available_qty(self):
        """Calculate available quantity (stock - reserved)"""
        self.available_qty = flt(self.stock_qty) - flt(self.reserved_qty)
        if self.available_qty < 0:
            self.available_qty = 0

    def update_main_image(self):
        """Sync main image from images table"""
        if not self.images:
            return

        for image in self.images:
            if image.is_main and image.file:
                self.main_image = image.file
                return

        # If no main image set, use first image
        for image in self.images:
            if image.media_type == "Image" and image.file:
                self.main_image = image.file
                return

    def update_stock_status(self):
        """Update is_in_stock based on available quantity"""
        if flt(self.available_qty) > 0:
            self.is_in_stock = 1
        elif self.backorder_allowed:
            self.is_in_stock = 1
        else:
            self.is_in_stock = 0

    def generate_variant_name(self):
        """Generate variant name from product name and axis values"""
        if not self.product:
            return

        # Get parent product name
        product_name = frappe.db.get_value("PIM Product", self.product, "product_name")
        if not product_name:
            return

        # Collect axis value labels
        axis_parts = []
        for axis_value in self.axis_values:
            label = axis_value.value_label or axis_value.value
            if label:
                axis_parts.append(label)

        if axis_parts:
            self.variant_name = f"{product_name} - {' / '.join(axis_parts)}"
        else:
            self.variant_name = product_name

    # ---- Helper Methods ----

    def get_parent_product(self):
        """Get the parent PIM Product document"""
        if not self.product:
            return None
        return frappe.get_doc("PIM Product", self.product)

    def get_effective_price(self):
        """
        Get effective selling price (priority: sale_price > price_override > parent base_price)

        Returns:
            Float: The effective selling price
        """
        if self.sale_price and flt(self.sale_price) > 0:
            return flt(self.sale_price)

        if self.price_override and flt(self.price_override) > 0:
            return flt(self.price_override)

        # Fall back to parent product price
        if self.product:
            parent_price = frappe.db.get_value("PIM Product", self.product, "base_price")
            if parent_price:
                return flt(parent_price)

        return 0

    def get_axis_value(self, attribute_code):
        """
        Get axis value by attribute code

        Args:
            attribute_code: The attribute code to look up

        Returns:
            The axis value or None
        """
        for axis_value in self.axis_values:
            if axis_value.attribute_code == attribute_code:
                return axis_value.value
        return None

    def get_axis_values_dict(self):
        """
        Get all axis values as a dictionary

        Returns:
            Dict of attribute_code: value
        """
        return {
            av.attribute_code: av.value
            for av in self.axis_values
        }

    def needs_reorder(self):
        """
        Check if variant stock is below reorder level

        Returns:
            Boolean indicating if reorder is needed
        """
        if not self.reorder_level:
            return False
        return flt(self.available_qty) <= flt(self.reorder_level)

    def is_low_stock(self):
        """
        Check if variant stock is at or below safety stock

        Returns:
            Boolean indicating if stock is low
        """
        if not self.safety_stock:
            return False
        return flt(self.available_qty) <= flt(self.safety_stock)

    def reserve_stock(self, qty):
        """
        Reserve stock for an order

        Args:
            qty: Quantity to reserve

        Returns:
            Boolean indicating success
        """
        if flt(qty) <= 0:
            frappe.throw(_("Quantity must be positive"), title=_("Invalid Quantity"))

        if flt(qty) > flt(self.available_qty):
            if not self.backorder_allowed:
                frappe.throw(
                    _("Not enough stock available. Available: {0}, Requested: {1}").format(
                        self.available_qty, qty
                    ),
                    title=_("Insufficient Stock")
                )

        self.reserved_qty = flt(self.reserved_qty) + flt(qty)
        self.calculate_available_qty()
        self.update_stock_status()
        self.save()
        return True

    def release_stock(self, qty):
        """
        Release reserved stock

        Args:
            qty: Quantity to release

        Returns:
            Boolean indicating success
        """
        if flt(qty) <= 0:
            frappe.throw(_("Quantity must be positive"), title=_("Invalid Quantity"))

        if flt(qty) > flt(self.reserved_qty):
            frappe.throw(
                _("Cannot release more than reserved. Reserved: {0}, Requested: {1}").format(
                    self.reserved_qty, qty
                ),
                title=_("Invalid Release")
            )

        self.reserved_qty = flt(self.reserved_qty) - flt(qty)
        self.calculate_available_qty()
        self.update_stock_status()
        self.save()
        return True

    def adjust_stock(self, qty, reason=None):
        """
        Adjust stock quantity

        Args:
            qty: Quantity to add (positive) or remove (negative)
            reason: Optional reason for adjustment

        Returns:
            Boolean indicating success
        """
        new_qty = flt(self.stock_qty) + flt(qty)
        if new_qty < 0:
            frappe.throw(
                _("Stock cannot be negative. Current: {0}, Adjustment: {1}").format(
                    self.stock_qty, qty
                ),
                title=_("Invalid Adjustment")
            )

        self.stock_qty = new_qty
        self.calculate_available_qty()
        self.update_stock_status()
        self.save()

        # Log the adjustment (if logging is set up)
        if reason:
            frappe.logger().info(
                f"Stock adjusted for {self.name}: {qty} ({reason})"
            )

        return True

    def get_images_list(self):
        """
        Get list of variant images

        Returns:
            List of image file paths sorted by sort_order
        """
        images = []
        for media in self.images:
            if media.media_type == "Image" and media.file:
                images.append({
                    "file": media.file,
                    "is_main": media.is_main,
                    "alt_text": media.alt_text,
                    "sort_order": media.sort_order
                })

        # Sort by sort_order, main first
        images.sort(key=lambda x: (0 if x["is_main"] else 1, x["sort_order"]))
        return images

    def inherit_from_parent(self, fields=None):
        """
        Inherit field values from parent product

        Args:
            fields: List of field names to inherit (default: dimensions and weight)
        """
        if not self.product:
            return

        default_fields = [
            'weight', 'weight_uom', 'length', 'width', 'height', 'dimension_uom'
        ]
        fields_to_inherit = fields or default_fields

        parent = self.get_parent_product()
        if not parent:
            return

        for field in fields_to_inherit:
            parent_value = getattr(parent, field, None)
            current_value = getattr(self, field, None)
            if parent_value and not current_value:
                setattr(self, field, parent_value)
