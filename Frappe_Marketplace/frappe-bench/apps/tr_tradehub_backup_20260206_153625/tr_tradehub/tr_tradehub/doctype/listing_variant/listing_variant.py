# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime
import json


class ListingVariant(Document):
    """
    Listing Variant DocType for product variations.

    Represents different variants of a listing (e.g., different sizes, colors).
    Each variant:
    - Links to a parent Listing
    - Has its own pricing, inventory, and attributes
    - Can have unique images
    - Syncs to ERPNext Item Variant
    """

    def before_insert(self):
        """Set default values before inserting a new variant."""
        # Generate unique variant code
        if not self.variant_code:
            self.variant_code = self.generate_variant_code()

        # Set seller and tenant from listing
        self.set_from_listing()

        # Initialize images as empty array
        if not self.images:
            self.images = "[]"

    def validate(self):
        """Validate variant data before saving."""
        self.validate_listing()
        self.validate_attributes()
        self.validate_prices()
        self.validate_inventory()
        self.validate_sku()
        self.generate_variant_name()
        self.calculate_available_qty()
        self.update_status_based_on_inventory()

    def on_update(self):
        """Actions after variant is updated."""
        self.update_listing_has_variants()
        self.clear_variant_cache()

        # Sync to ERPNext if linked
        if self.erpnext_item_variant:
            self.sync_to_erpnext_item()

    def after_insert(self):
        """Actions after variant is inserted."""
        self.update_listing_has_variants()

        # Create ERPNext Item Variant if parent has ERPNext Item
        if self.get_listing_erpnext_item():
            self.create_erpnext_item_variant()

    def on_trash(self):
        """Actions before variant is deleted."""
        self.check_linked_documents()

        # Update listing has_variants flag
        remaining_variants = frappe.db.count(
            "Listing Variant",
            {"listing": self.listing, "name": ["!=", self.name]}
        )
        if remaining_variants == 0:
            frappe.db.set_value("Listing", self.listing, "has_variants", 0)

    # Helper Methods
    def generate_variant_code(self):
        """Generate a unique variant code."""
        return f"VAR-{frappe.generate_hash(length=8).upper()}"

    def set_from_listing(self):
        """Set seller and tenant from parent listing."""
        if self.listing:
            listing = frappe.get_cached_doc("Listing", self.listing)
            self.seller = listing.seller
            self.tenant = listing.tenant
            self.currency = listing.currency

            # Inherit tracking settings from listing if not set
            if not self.track_inventory:
                self.track_inventory = listing.track_inventory
            if not self.allow_backorders:
                self.allow_backorders = listing.allow_backorders

    def generate_variant_name(self):
        """Generate variant name from attribute values."""
        if not self.variant_attributes:
            return

        attribute_values = []
        for attr in self.variant_attributes:
            if attr.attribute_value:
                attribute_values.append(attr.attribute_value)

        if attribute_values:
            self.variant_name = " - ".join(attribute_values)
        elif not self.variant_name:
            self.variant_name = f"Variant {self.variant_code}"

    def get_listing_erpnext_item(self):
        """Get ERPNext Item from parent listing."""
        if self.listing:
            return frappe.db.get_value("Listing", self.listing, "erpnext_item")
        return None

    # Validation Methods
    def validate_listing(self):
        """Validate listing link."""
        if not self.listing:
            frappe.throw(_("Listing is required"))

        if not frappe.db.exists("Listing", self.listing):
            frappe.throw(_("Listing {0} does not exist").format(self.listing))

        # Check listing status
        listing_status = frappe.db.get_value("Listing", self.listing, "status")
        if listing_status in ["Archived", "Rejected"]:
            frappe.throw(
                _("Cannot create variant for {0} listing").format(listing_status.lower())
            )

    def validate_attributes(self):
        """Validate variant attributes."""
        if not self.variant_attributes or len(self.variant_attributes) == 0:
            frappe.throw(_("At least one variant attribute is required"))

        # Check for duplicate attributes
        attributes = []
        for attr in self.variant_attributes:
            if attr.attribute in attributes:
                frappe.throw(
                    _("Duplicate attribute {0} in variant").format(attr.attribute)
                )
            attributes.append(attr.attribute)

            # Validate attribute exists and is a variant attribute
            if not frappe.db.exists("Attribute", attr.attribute):
                frappe.throw(_("Attribute {0} does not exist").format(attr.attribute))

            is_variant = frappe.db.get_value("Attribute", attr.attribute, "is_variant")
            if not is_variant:
                frappe.throw(
                    _("Attribute {0} is not marked as a variant attribute").format(
                        attr.attribute
                    )
                )

        # Check for duplicate variant combination
        self.check_duplicate_variant()

    def check_duplicate_variant(self):
        """Check if variant with same attributes already exists."""
        if not self.variant_attributes:
            return

        # Get all variants for this listing
        existing_variants = frappe.get_all(
            "Listing Variant",
            filters={"listing": self.listing, "name": ["!=", self.name or ""]},
            fields=["name"]
        )

        for variant in existing_variants:
            # Get variant attributes
            variant_attrs = frappe.get_all(
                "Listing Variant Attribute",
                filters={"parent": variant.name},
                fields=["attribute", "attribute_value"]
            )

            # Compare attributes
            if self.attributes_match(variant_attrs):
                frappe.throw(
                    _("Variant with same attributes already exists: {0}").format(
                        variant.name
                    )
                )

    def attributes_match(self, other_attrs):
        """Check if current attributes match other attributes."""
        if len(self.variant_attributes) != len(other_attrs):
            return False

        current_attrs = {
            (a.attribute, a.attribute_value) for a in self.variant_attributes
        }
        other_attrs_set = {
            (a["attribute"], a["attribute_value"]) for a in other_attrs
        }

        return current_attrs == other_attrs_set

    def validate_prices(self):
        """Validate pricing fields."""
        # If prices are set, validate them
        if self.base_price and flt(self.base_price) < 0:
            frappe.throw(_("Base Price cannot be negative"))

        if self.selling_price and flt(self.selling_price) < 0:
            frappe.throw(_("Selling Price cannot be negative"))

        if self.selling_price and self.base_price:
            if flt(self.selling_price) > flt(self.base_price):
                frappe.throw(_("Selling Price cannot be greater than Base Price"))

        if self.compare_at_price and self.selling_price:
            if flt(self.compare_at_price) < flt(self.selling_price):
                frappe.throw(
                    _("Compare at Price should be greater than Selling Price")
                )

        if self.cost_price and flt(self.cost_price) < 0:
            frappe.throw(_("Cost Price cannot be negative"))

    def validate_inventory(self):
        """Validate inventory fields."""
        if flt(self.stock_qty) < 0:
            frappe.throw(_("Stock Quantity cannot be negative"))

    def validate_sku(self):
        """Validate SKU uniqueness if provided."""
        if self.sku:
            # Check for duplicate SKU
            existing = frappe.db.get_value(
                "Listing Variant",
                {"sku": self.sku, "name": ["!=", self.name or ""]},
                "name"
            )
            if existing:
                frappe.throw(
                    _("SKU {0} is already used by variant {1}").format(
                        self.sku, existing
                    )
                )

            # Also check in SKU DocType
            if frappe.db.exists("SKU", {"sku_code": self.sku}):
                sku_doc = frappe.db.get_value(
                    "SKU",
                    {"sku_code": self.sku},
                    ["listing_variant"],
                    as_dict=True
                )
                if sku_doc and sku_doc.listing_variant != self.name:
                    frappe.throw(
                        _("SKU {0} is already registered in SKU registry").format(
                            self.sku
                        )
                    )

    def calculate_available_qty(self):
        """Calculate available quantity."""
        self.available_qty = max(0, flt(self.stock_qty) - flt(self.reserved_qty))

    def update_status_based_on_inventory(self):
        """Update status based on inventory levels."""
        if self.status in ["Inactive", "Discontinued"]:
            return

        if self.track_inventory:
            if flt(self.available_qty) <= 0 and not self.allow_backorders:
                self.status = "Out of Stock"
            elif self.status == "Out of Stock" and flt(self.available_qty) > 0:
                self.status = "Active"

    def update_listing_has_variants(self):
        """Update listing has_variants flag."""
        if self.listing:
            variant_count = frappe.db.count(
                "Listing Variant", {"listing": self.listing}
            )
            frappe.db.set_value(
                "Listing", self.listing, "has_variants",
                1 if variant_count > 0 else 0
            )

    # Pricing Methods
    def get_price(self):
        """Get the effective selling price for this variant."""
        if self.selling_price and flt(self.selling_price) > 0:
            return flt(self.selling_price)

        # Fall back to listing price
        if self.listing:
            return flt(frappe.db.get_value("Listing", self.listing, "selling_price"))

        return 0

    def get_base_price(self):
        """Get the effective base price for this variant."""
        if self.base_price and flt(self.base_price) > 0:
            return flt(self.base_price)

        # Fall back to listing base price
        if self.listing:
            return flt(frappe.db.get_value("Listing", self.listing, "base_price"))

        return 0

    def get_discount_percentage(self):
        """Calculate discount percentage."""
        compare_price = flt(self.compare_at_price)
        selling_price = self.get_price()

        if compare_price > 0 and selling_price > 0:
            discount = ((compare_price - selling_price) / compare_price) * 100
            return round(discount, 0)

        return 0

    # Stock Methods
    def update_stock(self, qty_change, reason=None):
        """Update stock quantity."""
        new_qty = flt(self.stock_qty) + flt(qty_change)
        if new_qty < 0:
            frappe.throw(_("Stock quantity cannot go below 0"))

        self.db_set("stock_qty", new_qty)
        self.db_set("available_qty", max(0, new_qty - flt(self.reserved_qty)))

        # Update status based on stock
        if self.track_inventory:
            if new_qty <= 0 and not self.allow_backorders:
                self.db_set("status", "Out of Stock")
            elif self.status == "Out of Stock" and new_qty > 0:
                self.db_set("status", "Active")

        self.clear_variant_cache()

    def reserve_stock(self, qty):
        """Reserve stock for pending orders."""
        if flt(qty) < 0:
            frappe.throw(_("Reserve quantity cannot be negative"))

        if flt(qty) > flt(self.available_qty) and not self.allow_backorders:
            frappe.throw(_("Not enough stock available"))

        self.db_set("reserved_qty", flt(self.reserved_qty) + flt(qty))
        self.db_set(
            "available_qty",
            max(0, flt(self.stock_qty) - flt(self.reserved_qty) - flt(qty))
        )
        self.clear_variant_cache()

    def release_reservation(self, qty):
        """Release reserved stock."""
        new_reserved = max(0, flt(self.reserved_qty) - flt(qty))
        self.db_set("reserved_qty", new_reserved)
        self.db_set("available_qty", max(0, flt(self.stock_qty) - new_reserved))
        self.clear_variant_cache()

    def is_in_stock(self):
        """Check if variant is in stock."""
        if not self.track_inventory:
            return True
        return flt(self.available_qty) > 0 or self.allow_backorders

    def is_low_stock(self):
        """Check if variant is low on stock."""
        if not self.track_inventory:
            return False
        return flt(self.available_qty) <= flt(self.low_stock_threshold)

    # Status Methods
    def activate(self):
        """Activate the variant."""
        if self.status == "Discontinued":
            frappe.throw(_("Cannot activate a discontinued variant"))

        if flt(self.available_qty) <= 0 and self.track_inventory and not self.allow_backorders:
            self.db_set("status", "Out of Stock")
        else:
            self.db_set("status", "Active")
        self.clear_variant_cache()

    def deactivate(self):
        """Deactivate the variant."""
        self.db_set("status", "Inactive")
        self.clear_variant_cache()

    def discontinue(self):
        """Discontinue the variant."""
        self.db_set("status", "Discontinued")
        self.clear_variant_cache()

    def set_as_default(self):
        """Set this variant as the default for the listing."""
        # Unset other defaults
        frappe.db.sql("""
            UPDATE `tabListing Variant`
            SET is_default = 0
            WHERE listing = %s AND name != %s
        """, (self.listing, self.name))

        self.db_set("is_default", 1)
        self.clear_variant_cache()

    # ERPNext Integration
    def create_erpnext_item_variant(self):
        """Create linked ERPNext Item Variant."""
        parent_item = self.get_listing_erpnext_item()
        if not parent_item:
            return

        if not frappe.db.exists("DocType", "Item"):
            return

        try:
            # Build variant attributes for ERPNext
            variant_attrs = {}
            for attr in self.variant_attributes:
                variant_attrs[attr.attribute] = attr.attribute_value

            # Create the variant item
            variant_item_name = f"{parent_item}-{self.variant_code}"

            item_data = {
                "doctype": "Item",
                "item_code": variant_item_name,
                "item_name": self.variant_title or self.variant_name,
                "variant_of": parent_item,
                "stock_uom": frappe.db.get_value("Item", parent_item, "stock_uom"),
                "is_stock_item": cint(self.track_inventory),
                "disabled": 0 if self.status == "Active" else 1,
            }

            # Add weight if specified
            if self.weight:
                item_data["weight_per_unit"] = self.weight
                item_data["weight_uom"] = self.weight_uom

            # Add image
            if self.primary_image:
                item_data["image"] = self.primary_image

            item = frappe.get_doc(item_data)
            item.flags.ignore_permissions = True
            item.insert()

            self.db_set("erpnext_item_variant", item.name)

        except Exception as e:
            frappe.log_error(
                f"Failed to create ERPNext Item Variant for {self.name}: {str(e)}",
                "Listing Variant ERPNext Sync Error"
            )

    def sync_to_erpnext_item(self):
        """Sync variant data to ERPNext Item."""
        if not self.erpnext_item_variant:
            return

        if not frappe.db.exists("Item", self.erpnext_item_variant):
            self.db_set("erpnext_item_variant", None)
            return

        try:
            item = frappe.get_doc("Item", self.erpnext_item_variant)
            item.item_name = self.variant_title or self.variant_name
            item.disabled = 0 if self.status == "Active" else 1

            if self.weight:
                item.weight_per_unit = self.weight
                item.weight_uom = self.weight_uom

            if self.primary_image:
                item.image = self.primary_image

            item.flags.ignore_permissions = True
            item.save()

        except frappe.DoesNotExistError:
            self.db_set("erpnext_item_variant", None)
        except Exception as e:
            frappe.log_error(
                f"Failed to sync ERPNext Item Variant for {self.name}: {str(e)}",
                "Listing Variant ERPNext Sync Error"
            )

    # Statistics Methods
    def increment_view_count(self):
        """Increment view count."""
        frappe.db.set_value(
            "Listing Variant", self.name, "view_count", cint(self.view_count) + 1,
            update_modified=False
        )

    def increment_order_count(self):
        """Increment order count."""
        frappe.db.set_value(
            "Listing Variant", self.name, "order_count", cint(self.order_count) + 1,
            update_modified=False
        )
        frappe.db.set_value(
            "Listing Variant", self.name, "last_sold_at", now_datetime(),
            update_modified=False
        )

    # Helper Methods
    def check_linked_documents(self):
        """Check for linked documents before deletion."""
        # Check for cart lines
        if frappe.db.exists("Cart Line", {"listing_variant": self.name}):
            frappe.throw(
                _("Cannot delete variant with items in shopping carts")
            )

        # Check for order items
        # (would check Order Item or Sub Order Item when implemented)

    def clear_variant_cache(self):
        """Clear cached variant data."""
        cache_key = f"listing_variant:{self.name}"
        frappe.cache().delete_value(cache_key)

        if self.variant_code:
            code_cache_key = f"listing_variant_by_code:{self.variant_code}"
            frappe.cache().delete_value(code_cache_key)

        # Also clear listing cache
        if self.listing:
            listing_cache_key = f"listing:{self.listing}"
            frappe.cache().delete_value(listing_cache_key)

    def get_attributes_dict(self):
        """Get variant attributes as dictionary."""
        attrs = {}
        for attr in self.variant_attributes:
            attrs[attr.attribute] = attr.attribute_value
        return attrs

    def get_display_info(self):
        """Get display information for the variant."""
        return {
            "name": self.name,
            "variant_code": self.variant_code,
            "variant_name": self.variant_name,
            "variant_title": self.variant_title,
            "sku": self.sku,
            "price": self.get_price(),
            "base_price": self.get_base_price(),
            "compare_at_price": flt(self.compare_at_price),
            "discount_percentage": self.get_discount_percentage(),
            "in_stock": self.is_in_stock(),
            "available_qty": flt(self.available_qty),
            "primary_image": self.primary_image,
            "attributes": self.get_attributes_dict(),
            "status": self.status,
        }


# API Endpoints
@frappe.whitelist()
def get_variant(variant_name=None, variant_code=None):
    """
    Get variant details.

    Args:
        variant_name: Name of the variant
        variant_code: Unique variant code

    Returns:
        dict: Variant details
    """
    if not variant_name and not variant_code:
        frappe.throw(_("Either variant_name or variant_code is required"))

    if variant_code and not variant_name:
        variant_name = frappe.db.get_value(
            "Listing Variant", {"variant_code": variant_code}, "name"
        )

    if not variant_name:
        return {"error": _("Variant not found")}

    variant = frappe.get_doc("Listing Variant", variant_name)
    return variant.get_display_info()


@frappe.whitelist()
def get_listing_variants(listing, include_inactive=False):
    """
    Get all variants for a listing.

    Args:
        listing: Listing name
        include_inactive: Include inactive variants

    Returns:
        list: List of variant details
    """
    filters = {"listing": listing}
    if not include_inactive:
        filters["status"] = ["in", ["Active", "Out of Stock"]]

    variants = frappe.get_all(
        "Listing Variant",
        filters=filters,
        fields=[
            "name", "variant_code", "variant_name", "variant_title",
            "sku", "selling_price", "base_price", "compare_at_price",
            "stock_qty", "available_qty", "status", "is_default",
            "primary_image", "currency"
        ],
        order_by="is_default DESC, variant_name ASC"
    )

    # Add attributes for each variant
    for v in variants:
        v["attributes"] = frappe.get_all(
            "Listing Variant Attribute",
            filters={"parent": v["name"]},
            fields=["attribute", "attribute_value"],
            order_by="idx"
        )

    return variants


@frappe.whitelist()
def create_variant(**kwargs):
    """
    Create a new listing variant.

    Returns:
        dict: Created variant details
    """
    required = ["listing", "variant_attributes"]
    for field in required:
        if not kwargs.get(field):
            frappe.throw(_(f"{field} is required"))

    # Check permission
    listing = kwargs.get("listing")
    seller_user = frappe.db.get_value(
        "Seller Profile",
        frappe.db.get_value("Listing", listing, "seller"),
        "user"
    )
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing Variant", "create"):
            frappe.throw(_("Not permitted to create variants for this listing"))

    variant = frappe.get_doc({
        "doctype": "Listing Variant",
        **kwargs
    })
    variant.insert()

    return {
        "status": "success",
        "variant_name": variant.name,
        "variant_code": variant.variant_code,
        "message": _("Variant created successfully")
    }


@frappe.whitelist()
def update_variant_stock(variant_name, qty_change, reason=None):
    """
    Update variant stock quantity.

    Args:
        variant_name: Name of the variant
        qty_change: Quantity to add (positive) or subtract (negative)
        reason: Reason for stock change

    Returns:
        dict: Updated stock info
    """
    variant = frappe.get_doc("Listing Variant", variant_name)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", variant.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing Variant", "write"):
            frappe.throw(_("Not permitted to update stock for this variant"))

    variant.update_stock(flt(qty_change), reason)

    return {
        "status": "success",
        "stock_qty": variant.stock_qty,
        "available_qty": variant.available_qty,
        "reserved_qty": variant.reserved_qty,
        "variant_status": variant.status
    }


@frappe.whitelist()
def set_default_variant(variant_name):
    """
    Set a variant as the default for its listing.

    Args:
        variant_name: Name of the variant

    Returns:
        dict: Success status
    """
    variant = frappe.get_doc("Listing Variant", variant_name)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", variant.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing Variant", "write"):
            frappe.throw(_("Not permitted to update this variant"))

    variant.set_as_default()

    return {
        "status": "success",
        "message": _("Variant set as default")
    }


@frappe.whitelist()
def get_variant_by_attributes(listing, attributes):
    """
    Find a variant by its attributes.

    Args:
        listing: Listing name
        attributes: Dict of attribute name -> value

    Returns:
        dict: Variant details or None
    """
    if isinstance(attributes, str):
        attributes = json.loads(attributes)

    # Get all variants for this listing
    variants = frappe.get_all(
        "Listing Variant",
        filters={"listing": listing, "status": ["in", ["Active", "Out of Stock"]]},
        fields=["name"]
    )

    for variant in variants:
        # Get variant attributes
        variant_attrs = frappe.get_all(
            "Listing Variant Attribute",
            filters={"parent": variant.name},
            fields=["attribute", "attribute_value"]
        )

        # Check if attributes match
        variant_attrs_dict = {a["attribute"]: a["attribute_value"] for a in variant_attrs}

        if variant_attrs_dict == attributes:
            return get_variant(variant.name)

    return None
