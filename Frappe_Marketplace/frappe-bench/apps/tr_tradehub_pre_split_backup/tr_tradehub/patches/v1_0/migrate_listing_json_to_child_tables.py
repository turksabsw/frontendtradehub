# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Migration patch to convert Listing JSON fields to Child Tables:
- attributes (JSON) -> attribute_values (Table: Listing Attribute Value)
- images (JSON) -> listing_images (Table: Listing Image)
- bulk_pricing_tiers (JSON) -> pricing_tiers (Table: Listing Bulk Pricing Tier)
"""

import json
import frappe
from frappe.utils import cint, flt


def execute():
    """Execute the migration patch."""
    # Reload DocTypes to ensure schema is up to date
    frappe.reload_doc("tr_tradehub", "doctype", "listing_image")
    frappe.reload_doc("tr_tradehub", "doctype", "listing_attribute_value")
    frappe.reload_doc("tr_tradehub", "doctype", "listing_bulk_pricing_tier")
    frappe.reload_doc("tr_tradehub", "doctype", "listing")

    # Get all listings with JSON data in the old fields
    listings = frappe.get_all(
        "Listing",
        filters={},
        fields=["name", "attributes", "images", "bulk_pricing_tiers"],
        limit_page_length=0
    )

    migrated_count = 0
    error_count = 0

    for listing_data in listings:
        try:
            # Skip if no JSON data to migrate
            has_data = (
                listing_data.attributes or
                listing_data.images or
                listing_data.bulk_pricing_tiers
            )
            if not has_data:
                continue

            listing = frappe.get_doc("Listing", listing_data.name)
            modified = False

            # Migrate attributes
            if listing_data.attributes and not listing.get("attribute_values"):
                modified = migrate_attributes(listing, listing_data.attributes) or modified

            # Migrate images
            if listing_data.images and not listing.get("listing_images"):
                modified = migrate_images(listing, listing_data.images) or modified

            # Migrate bulk pricing tiers
            if listing_data.bulk_pricing_tiers and not listing.get("pricing_tiers"):
                modified = migrate_pricing_tiers(listing, listing_data.bulk_pricing_tiers) or modified

            if modified:
                # Use flags to skip validation during migration
                listing.flags.ignore_validate = True
                listing.flags.ignore_permissions = True
                listing.flags.ignore_links = True
                listing.save()
                migrated_count += 1

        except Exception as e:
            error_count += 1
            frappe.log_error(
                message=f"Error migrating Listing {listing_data.name}: {str(e)}",
                title="Listing JSON Migration Error"
            )

    # Log summary
    frappe.logger().info(
        f"Listing JSON Migration Complete: {migrated_count} migrated, {error_count} errors"
    )

    if migrated_count > 0:
        frappe.db.commit()


def migrate_attributes(listing, attributes_json):
    """Migrate attributes JSON to Listing Attribute Value child table."""
    try:
        attributes = parse_json(attributes_json)
        if not attributes:
            return False

        # Handle different JSON structures
        # Structure 1: {"color": "red", "size": "large"}
        # Structure 2: [{"attribute": "color", "value": "red"}, ...]
        # Structure 3: [{"name": "color", "value": "red"}, ...]

        if isinstance(attributes, dict):
            # Structure 1: key-value pairs
            for idx, (attr_name, attr_value) in enumerate(attributes.items()):
                listing.append("attribute_values", {
                    "attribute": find_or_create_attribute(attr_name),
                    "attribute_name": attr_name,
                    "value": str(attr_value) if attr_value else "",
                    "sort_order": idx
                })
        elif isinstance(attributes, list):
            for idx, attr in enumerate(attributes):
                if isinstance(attr, dict):
                    # Structure 2 or 3
                    attr_name = attr.get("attribute") or attr.get("name") or attr.get("attribute_name") or ""
                    attr_value = attr.get("value") or attr.get("attribute_value") or ""
                    unit = attr.get("unit") or attr.get("uom") or ""

                    listing.append("attribute_values", {
                        "attribute": find_or_create_attribute(attr_name) if attr_name else None,
                        "attribute_name": attr_name,
                        "value": str(attr_value) if attr_value else "",
                        "unit": unit,
                        "sort_order": attr.get("sort_order", idx),
                        "is_variant_attribute": cint(attr.get("is_variant", 0))
                    })

        return True
    except Exception as e:
        frappe.log_error(
            message=f"Error migrating attributes for Listing {listing.name}: {str(e)}",
            title="Attribute Migration Error"
        )
        return False


def migrate_images(listing, images_json):
    """Migrate images JSON to Listing Image child table."""
    try:
        images = parse_json(images_json)
        if not images:
            return False

        # Handle different JSON structures
        # Structure 1: ["url1", "url2", ...]
        # Structure 2: [{"url": "...", "alt": "..."}, ...]

        if isinstance(images, list):
            for idx, img in enumerate(images):
                if isinstance(img, str):
                    # Structure 1: simple URL array
                    listing.append("listing_images", {
                        "image": img,
                        "sort_order": idx,
                        "is_primary": 0
                    })
                elif isinstance(img, dict):
                    # Structure 2: object array
                    listing.append("listing_images", {
                        "image": img.get("url") or img.get("image") or img.get("src") or "",
                        "alt_text": img.get("alt") or img.get("alt_text") or img.get("title") or "",
                        "sort_order": img.get("sort_order", idx),
                        "is_primary": cint(img.get("is_primary", 0)),
                        "image_angle": img.get("angle") or img.get("image_angle") or ""
                    })

        return True
    except Exception as e:
        frappe.log_error(
            message=f"Error migrating images for Listing {listing.name}: {str(e)}",
            title="Image Migration Error"
        )
        return False


def migrate_pricing_tiers(listing, pricing_json):
    """Migrate bulk_pricing_tiers JSON to Listing Bulk Pricing Tier child table."""
    try:
        tiers = parse_json(pricing_json)
        if not tiers:
            return False

        # Expected structure: [{"min_qty": 10, "max_qty": 50, "price": 9.99}, ...]

        if isinstance(tiers, list):
            for tier in tiers:
                if isinstance(tier, dict):
                    min_qty = cint(tier.get("min_qty", 0))
                    max_qty = cint(tier.get("max_qty", 0))
                    price = flt(tier.get("price", 0))

                    if min_qty > 0 and price > 0:
                        # Calculate discount percentage if base price is available
                        discount_pct = 0
                        if listing.selling_price and listing.selling_price > 0:
                            discount_pct = ((listing.selling_price - price) / listing.selling_price) * 100

                        listing.append("pricing_tiers", {
                            "min_qty": min_qty,
                            "max_qty": max_qty if max_qty > 0 else None,
                            "price": price,
                            "discount_percentage": flt(discount_pct, 2) if discount_pct > 0 else 0,
                            "is_active": 1
                        })

        return True
    except Exception as e:
        frappe.log_error(
            message=f"Error migrating pricing tiers for Listing {listing.name}: {str(e)}",
            title="Pricing Tier Migration Error"
        )
        return False


def parse_json(json_str):
    """Safely parse JSON string."""
    if not json_str:
        return None

    if isinstance(json_str, (dict, list)):
        return json_str

    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None


def find_or_create_attribute(attr_name):
    """Find existing Attribute or return None (don't create during migration)."""
    if not attr_name:
        return None

    # Try to find existing attribute by name
    attr = frappe.db.get_value("Attribute", {"attribute_name": attr_name}, "name")
    if attr:
        return attr

    # Try to find by code
    attr_code = attr_name.lower().replace(" ", "_").replace("-", "_")
    attr = frappe.db.get_value("Attribute", {"attribute_code": attr_code}, "name")
    if attr:
        return attr

    # Return None - don't auto-create attributes during migration
    return None
