# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
PIM API Endpoints

Provides whitelisted API endpoints for Product Information Management operations.
All endpoints use @frappe.whitelist() decorator for external access.

Endpoints:
    - get_product_with_attributes: GET product with all attribute values
    - save_product_attributes: POST update product attributes
    - get_family_config: GET family configuration for dynamic form rendering
    - generate_variants: POST create variant combinations
    - get_variant_matrix: GET variant grid data
    - get_completeness_report: GET completeness status
    - export_to_channel: POST trigger channel export
    - bulk_update_attributes: POST batch attribute updates
    - bulk_assign_family: POST batch family assignment
"""

import json
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

# Import PIM modules
from tradehub_catalog.tradehub_catalog.pim.completeness import (
    calculate_completeness,
    calculate_channel_completeness,
    bulk_calculate_completeness
)
from tradehub_catalog.tradehub_catalog.pim.variant_generator import (
    generate_variants as _generate_variants,
    get_variant_matrix as _get_variant_matrix,
    preview_variants,
    bulk_generate_variants,
    delete_variants,
    regenerate_variants
)
from tradehub_catalog.tradehub_catalog.pim.channel_export import (
    export_to_channel as _export_to_channel,
    get_channel_export_data,
    validate_channel_export,
    bulk_export_to_channel,
    get_channel_mapping_preview,
    get_available_channels_for_product
)


@frappe.whitelist()
def get_product_with_attributes(product: str, locale: Optional[str] = None, channel: Optional[str] = None) -> Dict:
    """
    Get a PIM Product with all its attribute values.

    Args:
        product: PIM Product name or product_code
        locale: Optional locale to filter attribute values
        channel: Optional channel to filter attribute values

    Returns:
        dict: Product data with attributes, media, prices, descriptions, and metadata
    """
    try:
        # Get product document
        product_doc = frappe.get_doc("PIM Product", product)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product '{0}' not found").format(product), frappe.DoesNotExistError)

    # Build response with core product data
    result = {
        "name": product_doc.name,
        "product_name": product_doc.product_name,
        "product_code": product_doc.product_code,
        "product_family": product_doc.product_family,
        "product_class": product_doc.product_class,
        "status": product_doc.status,
        "is_active": product_doc.is_active,
        "is_published": product_doc.is_published,
        "brand": product_doc.brand,
        "sku": product_doc.sku,
        "barcode": product_doc.barcode,
        "gtin": product_doc.gtin,
        "mpn": product_doc.mpn,
        "base_price": product_doc.base_price,
        "cost_price": product_doc.cost_price,
        "currency": product_doc.currency,
        "main_image": product_doc.main_image,
        "short_description": product_doc.short_description,
        "url_slug": product_doc.url_slug,
        "completeness_score": product_doc.completeness_score,
        "completeness_status": product_doc.completeness_status
    }

    # Build attributes dictionary with scoping
    attributes = {}
    for attr_val in product_doc.attribute_values:
        # Apply locale/channel filter if specified
        if locale and attr_val.locale and attr_val.locale != locale:
            continue
        if channel and attr_val.channel and attr_val.channel != channel:
            continue

        attr_code = attr_val.attribute_code
        value = product_doc.get_attribute_value(attr_code, locale=attr_val.locale, channel=attr_val.channel)

        # Store with scope info
        key = attr_code
        if attr_val.locale:
            key = f"{attr_code}:{attr_val.locale}"
        if attr_val.channel:
            key = f"{key}@{attr_val.channel}"

        attributes[key] = {
            "attribute_code": attr_code,
            "attribute_type": attr_val.attribute_type,
            "value": value,
            "locale": attr_val.locale,
            "channel": attr_val.channel
        }

    result["attributes"] = attributes

    # Include descriptions
    descriptions = []
    for desc in product_doc.descriptions:
        if locale and desc.locale and desc.locale != locale:
            continue
        if channel and desc.channel and desc.channel != channel:
            continue
        descriptions.append({
            "description_type": desc.description_type,
            "description": desc.description,
            "locale": desc.locale,
            "channel": desc.channel,
            "word_count": desc.word_count,
            "character_count": desc.character_count
        })
    result["descriptions"] = descriptions

    # Include media
    media = []
    for m in product_doc.media:
        media.append({
            "media_type": m.media_type,
            "file": m.file,
            "alt_text": m.alt_text,
            "is_main": m.is_main,
            "sort_order": m.sort_order,
            "image_angle": m.image_angle
        })
    result["media"] = media

    # Include prices
    prices = []
    for p in product_doc.prices:
        if channel and p.channel and p.channel != channel:
            continue
        prices.append({
            "price_type": p.price_type,
            "price": p.price,
            "currency": p.currency,
            "channel": p.channel,
            "min_quantity": p.min_quantity,
            "valid_from": str(p.valid_from) if p.valid_from else None,
            "valid_to": str(p.valid_to) if p.valid_to else None
        })
    result["prices"] = prices

    # Include categories
    categories = []
    for cat in product_doc.categories:
        categories.append({
            "category": cat.category,
            "category_name": cat.category_name,
            "is_primary": cat.is_primary,
            "channel": cat.channel
        })
    result["categories"] = categories

    # Include family config if available
    if product_doc.product_family:
        try:
            family_doc = frappe.get_doc("Product Family", product_doc.product_family)
            result["family_config"] = family_doc.get_family_config()
        except frappe.DoesNotExistError:
            result["family_config"] = None

    return result


@frappe.whitelist()
def save_product_attributes(product: str, attributes: Union[str, Dict, List]) -> Dict:
    """
    Update product attribute values.

    Args:
        product: PIM Product name or product_code
        attributes: Dict or List of attribute values to update
            Format (dict): {"attr_code": value, ...}
            Format (list): [{"attribute_code": "...", "value": "...", "locale": "...", "channel": "..."}, ...]

    Returns:
        dict: Result with updated attribute count and any errors
    """
    # Parse attributes if string
    if isinstance(attributes, str):
        try:
            attributes = json.loads(attributes)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid JSON format for attributes"))

    try:
        product_doc = frappe.get_doc("PIM Product", product)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product '{0}' not found").format(product), frappe.DoesNotExistError)

    result = {
        "product": product_doc.name,
        "updated": 0,
        "errors": []
    }

    # Handle dict format: {"attr_code": value, ...}
    if isinstance(attributes, dict):
        for attr_code, value in attributes.items():
            try:
                product_doc.set_attribute_value(attr_code, value)
                result["updated"] += 1
            except Exception as e:
                result["errors"].append({
                    "attribute_code": attr_code,
                    "error": str(e)
                })

    # Handle list format: [{"attribute_code": "...", "value": "...", ...}, ...]
    elif isinstance(attributes, list):
        for attr_data in attributes:
            attr_code = attr_data.get("attribute_code")
            if not attr_code:
                continue

            value = attr_data.get("value")
            locale = attr_data.get("locale")
            channel = attr_data.get("channel")

            try:
                product_doc.set_attribute_value(attr_code, value, locale=locale, channel=channel)
                result["updated"] += 1
            except Exception as e:
                result["errors"].append({
                    "attribute_code": attr_code,
                    "locale": locale,
                    "channel": channel,
                    "error": str(e)
                })

    # Save product
    try:
        product_doc.save()
        result["success"] = True
    except Exception as e:
        result["success"] = False
        result["save_error"] = str(e)

    return result


@frappe.whitelist()
def get_family_config(family: str) -> Dict:
    """
    Get complete family configuration for dynamic form rendering.

    This endpoint is called by the Product form client script when
    the product_family field is changed, to dynamically rebuild
    attribute sections.

    Args:
        family: Product Family name or family_code

    Returns:
        dict: Complete family configuration including:
            - attributes: List of attribute definitions with metadata
            - required_attributes: List of required attribute codes
            - variant_axes: Variant axis configurations
            - completeness_rules: Completeness rule configurations
            - media_requirements: Image/video requirements
            - default_values: Default attribute values
            - translatable_attributes: Translation configurations
            - label_overrides: Custom label overrides
    """
    try:
        family_doc = frappe.get_doc("Product Family", family)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product Family '{0}' not found").format(family), frappe.DoesNotExistError)

    # Get full family config using the DocType method
    config = family_doc.get_family_config()

    # Enhance attributes with full PIM Attribute details
    enhanced_attributes = []
    for attr_info in config.get("attributes", []):
        attr_doc = attr_info.get("attribute")
        if attr_doc:
            # Get attribute options if applicable
            options = []
            if hasattr(attr_doc, "options") and attr_doc.options:
                for opt in attr_doc.options:
                    options.append({
                        "value": opt.option_value,
                        "label": opt.option_label or opt.option_value,
                        "color_hex": opt.color_hex,
                        "image": opt.image,
                        "sort_order": opt.sort_order
                    })

            enhanced_attributes.append({
                "attribute_code": attr_doc.attribute_code,
                "attribute_name": attr_doc.attribute_name,
                "attribute_type": attr_doc.attribute_type,
                "attribute_group": attr_doc.attribute_group,
                "description": attr_doc.description,
                "placeholder": attr_doc.placeholder,
                "default_value": attr_doc.default_value,
                "is_required": attr_info.get("is_required", False),
                "is_variant": attr_info.get("is_variant", False),
                "is_unique_per_family": attr_info.get("is_unique_per_family", False),
                "is_filterable": attr_info.get("is_filterable", False),
                "is_localizable": attr_doc.is_localizable,
                "is_scopable": attr_doc.is_scopable,
                "sort_order": attr_info.get("sort_order", 0),
                "options": options,
                # Type-specific configs
                "min_value": attr_doc.min_value,
                "max_value": attr_doc.max_value,
                "min_length": attr_doc.min_length,
                "max_length": attr_doc.max_length,
                "validation_regex": attr_doc.validation_regex,
                "linked_doctype": attr_doc.linked_doctype,
                "unit_of_measure": attr_doc.unit_of_measure
            })

    config["attributes"] = enhanced_attributes

    # Add attribute groups for UI organization
    attribute_groups = {}
    for attr in enhanced_attributes:
        group = attr.get("attribute_group") or "General"
        if group not in attribute_groups:
            # Get group details
            try:
                group_doc = frappe.get_doc("PIM Attribute Group", group)
                attribute_groups[group] = {
                    "group_name": group_doc.group_name,
                    "group_code": group_doc.group_code,
                    "sort_order": group_doc.sort_order,
                    "icon": group_doc.icon,
                    "is_collapsible": group_doc.is_collapsible,
                    "attributes": []
                }
            except frappe.DoesNotExistError:
                attribute_groups[group] = {
                    "group_name": group,
                    "group_code": group.lower().replace(" ", "_"),
                    "sort_order": 999,
                    "attributes": []
                }

        attribute_groups[group]["attributes"].append(attr["attribute_code"])

    config["attribute_groups"] = list(attribute_groups.values())
    config["attribute_groups"].sort(key=lambda g: g.get("sort_order", 999))

    return config


@frappe.whitelist()
def generate_variants(
    product: str,
    axis_values: Optional[str] = None,
    skip_existing: bool = True,
    preview_only: bool = False
) -> Dict:
    """
    Generate variants for a PIM Product based on its Family's variant axes.

    Args:
        product: PIM Product name or product_code
        axis_values: Optional JSON string of axis values override
            Format: {"color": ["red", "blue"], "size": ["S", "M", "L"]}
        skip_existing: If True, skip variants that already exist
        preview_only: If True, return preview without creating variants

    Returns:
        dict: Generation result with counts and variant list
            - success: bool
            - total_combinations: int
            - created: int (or preview count if preview_only)
            - skipped: int
            - errors: int
            - variants: list of variant data
    """
    # Parse axis_values if provided as JSON string
    axis_values_dict = None
    if axis_values:
        if isinstance(axis_values, str):
            try:
                axis_values_dict = json.loads(axis_values)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid JSON format for axis_values"))
        else:
            axis_values_dict = axis_values

    # Preview only mode
    if cint(preview_only):
        previews = preview_variants(product, axis_values=axis_values_dict)
        return {
            "success": True,
            "preview_only": True,
            "total_combinations": len(previews),
            "variants": previews
        }

    # Generate variants
    result = _generate_variants(
        product,
        axis_values=axis_values_dict,
        save=True,
        skip_existing=cint(skip_existing)
    )

    return result


@frappe.whitelist()
def get_variant_matrix(product: str) -> Dict:
    """
    Get variant matrix data for UI display (grid/table view).

    Returns a structure suitable for rendering variant grids in the UI,
    supporting 1D, 2D, and multi-axis variant displays.

    Args:
        product: PIM Product name or product_code

    Returns:
        dict: Matrix data including:
            - product: Product name
            - product_name: Product display name
            - family: Family name
            - axes: List of axis definitions with values
            - existing_variants: List of existing variant data
            - possible_combinations: Total possible variant count
            - existing_count: Current variant count
            - matrix: Nested structure for grid display
    """
    return _get_variant_matrix(product)


@frappe.whitelist()
def get_completeness_report(
    product: str,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    include_channel_breakdown: bool = False
) -> Dict:
    """
    Get completeness report for a PIM Product.

    Args:
        product: PIM Product name or product_code
        channel: Optional channel to evaluate for
        locale: Optional locale to evaluate for
        include_channel_breakdown: If True, include completeness for all channels

    Returns:
        dict: Completeness report including:
            - score: 0-100 completeness percentage
            - status: Incomplete/Partial/Complete/Enriched
            - detail: Detailed breakdown of rules and categories
            - channel_completeness: Optional per-channel scores
    """
    result = calculate_completeness(
        product,
        channel=channel,
        locale=locale,
        update_product=False
    )

    if cint(include_channel_breakdown):
        result["channel_completeness"] = calculate_channel_completeness(product)

    return result


@frappe.whitelist()
def export_to_channel(
    product: str,
    channel: str,
    locale: Optional[str] = None,
    include_images: bool = True,
    include_prices: bool = True,
    preview_only: bool = False
) -> Dict:
    """
    Export product data to a Sales Channel.

    Args:
        product: PIM Product name or product_code
        channel: Sales Channel name or channel_code
        locale: Optional locale for attribute values
        include_images: Include product images in export
        include_prices: Include product prices in export
        preview_only: If True, return preview without logging

    Returns:
        dict: Export result with transformed data and status
            - success: bool
            - product: Product name
            - channel: Channel name
            - data: Transformed field data
            - images: List of images for channel
            - prices: Price data for channel
            - errors: List of any errors
            - warnings: List of any warnings
    """
    if cint(preview_only):
        # Preview mode - just get transformed data
        return get_channel_export_data(product, channel, locale=locale)

    return _export_to_channel(
        product,
        channel,
        locale=locale,
        include_images=cint(include_images),
        include_prices=cint(include_prices),
        save_log=True
    )


@frappe.whitelist()
def bulk_update_attributes(products: Union[str, List], attributes: Union[str, Dict]) -> Dict:
    """
    Batch update attributes for multiple products.

    Args:
        products: JSON string or list of product names/codes
        attributes: JSON string or dict of attribute values to set
            Format: {"attr_code": value, ...}

    Returns:
        dict: Bulk update result
            - total: Total products processed
            - successful: Number of successful updates
            - failed: Number of failed updates
            - details: Per-product results
    """
    # Parse products
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid JSON format for products"))

    # Parse attributes
    if isinstance(attributes, str):
        try:
            attributes = json.loads(attributes)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid JSON format for attributes"))

    result = {
        "total": len(products),
        "successful": 0,
        "failed": 0,
        "details": []
    }

    for product_name in products:
        try:
            update_result = save_product_attributes(product_name, attributes)

            if update_result.get("success"):
                result["successful"] += 1
                result["details"].append({
                    "product": product_name,
                    "status": "success",
                    "updated": update_result.get("updated", 0)
                })
            else:
                result["failed"] += 1
                result["details"].append({
                    "product": product_name,
                    "status": "failed",
                    "error": update_result.get("save_error") or update_result.get("errors")
                })

        except Exception as e:
            result["failed"] += 1
            result["details"].append({
                "product": product_name,
                "status": "failed",
                "error": str(e)
            })

    return result


@frappe.whitelist()
def bulk_assign_family(products: Union[str, List], family: str, apply_defaults: bool = True) -> Dict:
    """
    Batch assign a Product Family to multiple products.

    Args:
        products: JSON string or list of product names/codes
        family: Product Family name or family_code to assign
        apply_defaults: If True, apply family default values to products

    Returns:
        dict: Bulk assignment result
            - total: Total products processed
            - successful: Number of successful assignments
            - failed: Number of failed assignments
            - details: Per-product results
    """
    # Parse products
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid JSON format for products"))

    # Verify family exists
    try:
        family_doc = frappe.get_doc("Product Family", family)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product Family '{0}' not found").format(family))

    # Get family defaults if applying
    defaults = {}
    if cint(apply_defaults):
        defaults = family_doc.get_default_values()

    result = {
        "total": len(products),
        "successful": 0,
        "failed": 0,
        "family": family_doc.name,
        "details": []
    }

    for product_name in products:
        try:
            product_doc = frappe.get_doc("PIM Product", product_name)

            # Update family
            product_doc.product_family = family_doc.name

            # Apply defaults
            if defaults:
                for attr_code, default_config in defaults.items():
                    value = default_config.get("value")
                    locale = default_config.get("locale")
                    channel = default_config.get("channel")

                    # Only set if no existing value
                    existing = product_doc.get_attribute_value(attr_code, locale=locale, channel=channel)
                    if existing is None or existing == "":
                        product_doc.set_attribute_value(attr_code, value, locale=locale, channel=channel)

            product_doc.save()

            result["successful"] += 1
            result["details"].append({
                "product": product_name,
                "status": "success",
                "defaults_applied": bool(defaults)
            })

        except frappe.DoesNotExistError:
            result["failed"] += 1
            result["details"].append({
                "product": product_name,
                "status": "failed",
                "error": "Product not found"
            })
        except Exception as e:
            result["failed"] += 1
            result["details"].append({
                "product": product_name,
                "status": "failed",
                "error": str(e)
            })

    return result


# Additional utility endpoints

@frappe.whitelist()
def recalculate_completeness(product: str, update_product: bool = True) -> Dict:
    """
    Recalculate and optionally update completeness score for a product.

    Args:
        product: PIM Product name or product_code
        update_product: If True, update the product's completeness fields

    Returns:
        dict: Completeness result
    """
    return calculate_completeness(product, update_product=cint(update_product))


@frappe.whitelist()
def delete_product_variants(product: str, variant_codes: Optional[str] = None, delete_all: bool = False) -> Dict:
    """
    Delete variants for a product.

    Args:
        product: PIM Product name or product_code
        variant_codes: Optional JSON list of specific variant codes to delete
        delete_all: If True, delete all variants for the product

    Returns:
        dict: Deletion result with count
    """
    codes = None
    if variant_codes:
        if isinstance(variant_codes, str):
            try:
                codes = json.loads(variant_codes)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid JSON format for variant_codes"))
        else:
            codes = variant_codes

    return delete_variants(product, variant_codes=codes, delete_all=cint(delete_all))


@frappe.whitelist()
def regenerate_product_variants(product: str, axis_values: Optional[str] = None) -> Dict:
    """
    Regenerate all variants for a product (delete existing and create new).

    Args:
        product: PIM Product name or product_code
        axis_values: Optional JSON string of axis values override

    Returns:
        dict: Combined deletion and generation result
    """
    axis_values_dict = None
    if axis_values:
        if isinstance(axis_values, str):
            try:
                axis_values_dict = json.loads(axis_values)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid JSON format for axis_values"))
        else:
            axis_values_dict = axis_values

    return regenerate_variants(product, axis_values=axis_values_dict, delete_existing=True)


@frappe.whitelist()
def validate_export(product: str, channel: str, locale: Optional[str] = None) -> Dict:
    """
    Validate product export data before sending to channel.

    Args:
        product: PIM Product name or product_code
        channel: Sales Channel name or channel_code
        locale: Optional locale

    Returns:
        dict: Validation result with errors and warnings
    """
    return validate_channel_export(product, channel, locale=locale)


@frappe.whitelist()
def get_export_preview(product: str, channel: str, locale: Optional[str] = None) -> List[Dict]:
    """
    Get a preview of how each mapping would transform data.

    Args:
        product: PIM Product name or product_code
        channel: Sales Channel name or channel_code
        locale: Optional locale

    Returns:
        list: Preview of each mapping with source and target values
    """
    return get_channel_mapping_preview(product, channel, locale=locale)


@frappe.whitelist()
def get_product_channels(product: str) -> List[Dict]:
    """
    Get list of channels that have mappings for a product's family.

    Args:
        product: PIM Product name or product_code

    Returns:
        list: Available channels with mapping info
    """
    return get_available_channels_for_product(product)
