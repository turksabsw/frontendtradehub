# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Listing & Catalog API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Listing CRUD operations (create, read, update, delete)
- Listing search and discovery
- Listing variants management
- SKU management
- Media asset management
- Import/Export operations
- Inventory management
- Listing moderation
- Listing statistics and analytics

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.listing.<function_name>

All endpoints follow Frappe conventions and patterns.
"""

import json
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import (
    cint,
    cstr,
    flt,
    getdate,
    nowdate,
    now_datetime,
    add_days,
    random_string,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "listing_create": {"limit": 50, "window": 3600},  # 50 per hour
    "listing_update": {"limit": 100, "window": 300},  # 100 per 5 min
    "listing_search": {"limit": 200, "window": 60},  # 200 per min
    "bulk_import": {"limit": 5, "window": 3600},  # 5 per hour
    "media_upload": {"limit": 100, "window": 3600},  # 100 per hour
}

# Default pagination settings
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# =============================================================================
# RATE LIMITING
# =============================================================================


def check_rate_limit(
    action: str,
    identifier: Optional[str] = None,
    throw: bool = True,
) -> bool:
    """
    Check if an action is rate limited.

    Args:
        action: The action to check
        identifier: User/IP identifier (defaults to session user)
        throw: If True, raises exception when rate limited

    Returns:
        bool: True if allowed, False if rate limited

    Raises:
        frappe.TooManyRequestsError: If throw=True and rate limited
    """
    if action not in RATE_LIMITS:
        return True

    config = RATE_LIMITS[action]

    # Get identifier (use session user by default)
    if not identifier:
        identifier = frappe.session.user or "unknown"

    cache_key = f"rate_limit:listing:{action}:{identifier}"

    # Get current count
    current = frappe.cache().get_value(cache_key)
    if current is None:
        frappe.cache().set_value(cache_key, 1, expires_in_sec=config["window"])
        return True

    current = cint(current)
    if current >= config["limit"]:
        if throw:
            frappe.throw(
                _("Too many requests. Please try again later."),
                exc=frappe.TooManyRequestsError,
            )
        return False

    frappe.cache().set_value(cache_key, current + 1, expires_in_sec=config["window"])
    return True


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_current_seller() -> Optional[str]:
    """
    Get the seller profile for the current user.

    Returns:
        str or None: Seller profile name or None if not a seller
    """
    user = frappe.session.user
    if user == "Guest":
        return None

    return frappe.db.get_value("Seller Profile", {"user": user}, "name")


def require_seller(func):
    """Decorator to require seller profile for API endpoints."""
    def wrapper(*args, **kwargs):
        seller = get_current_seller()
        if not seller:
            frappe.throw(_("You must be a seller to access this resource"))
        kwargs["_seller"] = seller
        return func(*args, **kwargs)
    return wrapper


def validate_listing_ownership(listing_name: str, seller: Optional[str] = None) -> bool:
    """
    Validate that the current user owns the listing.

    Args:
        listing_name: Name of the listing
        seller: Optional seller name to check against

    Returns:
        bool: True if user owns the listing or has write permission

    Raises:
        frappe.PermissionError: If user doesn't have permission
    """
    listing_seller = frappe.db.get_value("Listing", listing_name, "seller")

    if not listing_seller:
        frappe.throw(_("Listing not found"))

    if seller:
        if listing_seller == seller:
            return True

    seller_user = frappe.db.get_value("Seller Profile", listing_seller, "user")

    if seller_user == frappe.session.user:
        return True

    if frappe.has_permission("Listing", "write"):
        return True

    frappe.throw(_("Not permitted to access this listing"))


def _log_listing_event(
    event_type: str,
    user: str,
    details: Dict[str, Any],
) -> None:
    """Log listing-related events for audit trail."""
    try:
        ip_address = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
        except Exception:
            pass

        frappe.get_doc(
            {
                "doctype": "Activity Log",
                "user": user,
                "operation": f"listing_{event_type}",
                "status": "Success",
                "content": frappe.as_json(details),
                "ip_address": ip_address,
            }
        ).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Listing event logging error: {str(e)}", "Listing API")


# =============================================================================
# LISTING CRUD ENDPOINTS
# =============================================================================


@frappe.whitelist()
def create_listing(
    title: str,
    category: str,
    selling_price: float,
    seller: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a new marketplace listing.

    Args:
        title: Listing title
        category: Product category
        selling_price: Selling price
        seller: Seller profile name (optional, defaults to current user's seller)
        **kwargs: Additional listing fields

    Returns:
        dict: Created listing information

    Example:
        POST /api/method/tr_tradehub.api.v1.listing.create_listing
        {
            "title": "iPhone 15 Pro Max",
            "category": "Electronics",
            "selling_price": 45000,
            "description": "Latest iPhone model..."
        }
    """
    check_rate_limit("listing_create")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to create listings"))

    # Get seller profile
    if not seller:
        seller = get_current_seller()

    if not seller:
        frappe.throw(_("No seller profile found. Apply to become a seller first."))

    # Verify seller can create listing for this profile
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if seller_user != user and not frappe.has_permission("Listing", "create"):
        frappe.throw(_("Not permitted to create listings for this seller"))

    # Validate required fields
    if not title or not title.strip():
        frappe.throw(_("Title is required"))

    if not category:
        frappe.throw(_("Category is required"))

    if flt(selling_price) <= 0:
        frappe.throw(_("Selling price must be greater than 0"))

    # Build listing data
    listing_data = {
        "doctype": "Listing",
        "title": title.strip(),
        "category": category,
        "selling_price": flt(selling_price),
        "seller": seller,
    }

    # Add base price if not provided (defaults to selling price)
    listing_data["base_price"] = flt(kwargs.get("base_price", selling_price))

    # Add optional fields
    optional_fields = [
        "subcategory", "brand", "short_description", "description",
        "listing_type", "status", "sku", "barcode", "mpn", "gtin",
        "stock_qty", "min_order_qty", "max_order_qty", "stock_uom",
        "track_inventory", "allow_backorders", "weight", "weight_uom",
        "length", "width", "height", "dimension_uom", "primary_image",
        "images", "video_url", "attributes", "condition", "condition_notes",
        "currency", "cost_price", "compare_at_price", "tax_rate",
        "tax_included", "b2b_enabled", "wholesale_price", "wholesale_min_qty",
        "bulk_pricing_enabled", "bulk_pricing_tiers", "is_on_sale",
        "sale_start_date", "sale_end_date", "is_auction", "auction_start_date",
        "auction_end_date", "starting_bid", "reserve_price", "buy_now_price",
        "bid_increment", "auto_extend", "extension_minutes", "visibility_start_date",
        "visibility_end_date", "is_visible", "meta_title", "meta_description",
        "meta_keywords", "og_image", "shipping_enabled", "free_shipping",
        "shipping_class", "shipping_weight", "handling_time_days",
        "origin_country", "warranty_type", "warranty_period_months",
        "return_allowed", "return_period_days", "return_policy_notes",
        "tenant", "attribute_set", "requires_approval",
    ]

    for field in optional_fields:
        if field in kwargs and kwargs[field] is not None:
            listing_data[field] = kwargs[field]

    # Create listing
    try:
        listing = frappe.get_doc(listing_data)
        listing.insert()

        _log_listing_event(
            "created",
            user,
            {"listing": listing.name, "listing_code": listing.listing_code, "seller": seller},
        )

        return {
            "success": True,
            "message": _("Listing created successfully"),
            "listing": listing.name,
            "listing_code": listing.listing_code,
            "status": listing.status,
            "route": listing.route,
        }

    except frappe.DuplicateEntryError:
        frappe.throw(_("A listing with this information already exists"))
    except Exception as e:
        frappe.log_error(f"Listing creation error: {str(e)}", "Listing API Error")
        frappe.throw(_("An error occurred while creating the listing"))


@frappe.whitelist()
def get_listing(
    listing_name: Optional[str] = None,
    listing_code: Optional[str] = None,
    include_seller: bool = True,
    include_variants: bool = False,
) -> Dict[str, Any]:
    """
    Get listing details by name or code.

    Args:
        listing_name: Name of the listing
        listing_code: Unique listing code
        include_seller: Include seller details (default: True)
        include_variants: Include variant information (default: False)

    Returns:
        dict: Listing details

    Example:
        POST /api/method/tr_tradehub.api.v1.listing.get_listing
        {
            "listing_code": "LST-ABC12345"
        }
    """
    if not listing_name and not listing_code:
        frappe.throw(_("Either listing_name or listing_code is required"))

    # Find listing by code if name not provided
    if listing_code and not listing_name:
        listing_name = frappe.db.get_value(
            "Listing", {"listing_code": listing_code}, "name"
        )

    if not listing_name:
        return {"success": False, "message": _("Listing not found")}

    if not frappe.db.exists("Listing", listing_name):
        return {"success": False, "message": _("Listing not found")}

    listing = frappe.get_doc("Listing", listing_name)

    # Check visibility for non-owner users
    user = frappe.session.user
    seller_user = frappe.db.get_value("Seller Profile", listing.seller, "user")
    is_owner = seller_user == user
    is_admin = frappe.has_permission("Listing", "read")

    if not is_owner and not is_admin:
        if not listing.is_visible_to_buyer():
            return {"success": False, "message": _("Listing not available")}

    # Build response
    response = {
        "success": True,
        "name": listing.name,
        "listing_code": listing.listing_code,
        "title": listing.title,
        "seller": listing.seller,
        "status": listing.status,
        "moderation_status": listing.moderation_status,
        "listing_type": listing.listing_type,
        "category": listing.category,
        "subcategory": listing.subcategory,
        "brand": listing.brand,
        "condition": listing.condition,
        "short_description": listing.short_description,
        "description": listing.description,
        "sku": listing.sku,
        "barcode": listing.barcode,
        "mpn": listing.mpn,
        "gtin": listing.gtin,
        "currency": listing.currency,
        "base_price": listing.base_price,
        "selling_price": listing.selling_price,
        "compare_at_price": listing.compare_at_price,
        "cost_price": listing.cost_price if is_owner or is_admin else None,
        "discount_percentage": listing.get_discount_percentage() if hasattr(listing, 'get_discount_percentage') else 0,
        "is_on_sale": cint(listing.is_on_sale),
        "sale_start_date": listing.sale_start_date,
        "sale_end_date": listing.sale_end_date,
        "stock_qty": listing.stock_qty,
        "available_qty": listing.available_qty,
        "reserved_qty": listing.reserved_qty if is_owner or is_admin else None,
        "stock_uom": listing.stock_uom,
        "min_order_qty": listing.min_order_qty,
        "max_order_qty": listing.max_order_qty,
        "track_inventory": cint(listing.track_inventory),
        "allow_backorders": cint(listing.allow_backorders),
        "has_variants": cint(listing.has_variants),
        "primary_image": listing.primary_image,
        "images": json.loads(listing.images or "[]"),
        "video_url": listing.video_url,
        "attributes": json.loads(listing.attributes or "{}"),
        "weight": listing.weight,
        "weight_uom": listing.weight_uom,
        "length": listing.length,
        "width": listing.width,
        "height": listing.height,
        "dimension_uom": listing.dimension_uom,
        "route": listing.route,
        "meta_title": listing.meta_title,
        "meta_description": listing.meta_description,
        "average_rating": listing.average_rating,
        "review_count": listing.review_count,
        "view_count": listing.view_count,
        "order_count": listing.order_count,
        "wishlist_count": listing.wishlist_count,
        "quality_score": listing.quality_score,
        "is_featured": cint(listing.is_featured),
        "is_best_seller": cint(listing.is_best_seller),
        "is_new_arrival": cint(listing.is_new_arrival),
        "published_at": listing.published_at,
        "docstatus": listing.docstatus,
    }

    # B2B pricing (only for authenticated users)
    if user != "Guest":
        response["b2b_enabled"] = cint(listing.b2b_enabled)
        if listing.b2b_enabled:
            response["wholesale_price"] = listing.wholesale_price
            response["wholesale_min_qty"] = listing.wholesale_min_qty
            response["bulk_pricing_enabled"] = cint(listing.bulk_pricing_enabled)
            if listing.bulk_pricing_enabled:
                response["bulk_pricing_tiers"] = json.loads(listing.bulk_pricing_tiers or "[]")

    # Auction settings
    if listing.listing_type == "Auction":
        response.update({
            "is_auction": 1,
            "auction_start_date": listing.auction_start_date,
            "auction_end_date": listing.auction_end_date,
            "starting_bid": listing.starting_bid,
            "reserve_price": listing.reserve_price if is_owner or is_admin else None,
            "buy_now_price": listing.buy_now_price,
            "bid_increment": listing.bid_increment,
            "current_bid": listing.current_bid,
            "bid_count": listing.bid_count,
        })

    # Shipping settings
    response.update({
        "shipping_enabled": cint(listing.shipping_enabled),
        "free_shipping": cint(listing.free_shipping),
        "shipping_class": listing.shipping_class,
        "handling_time_days": listing.handling_time_days,
        "origin_country": listing.origin_country,
    })

    # Warranty & returns
    response.update({
        "warranty_type": listing.warranty_type,
        "warranty_period_months": listing.warranty_period_months,
        "return_allowed": cint(listing.return_allowed),
        "return_period_days": listing.return_period_days,
    })

    # Include seller details if requested
    if include_seller:
        seller_details = frappe.db.get_value(
            "Seller Profile",
            listing.seller,
            ["seller_name", "display_name", "city", "country", "average_rating",
             "total_reviews", "is_verified", "is_top_seller", "seller_tier"],
            as_dict=True,
        )
        response["seller_details"] = seller_details

    # Include variants if requested
    if include_variants and cint(listing.has_variants):
        variants = frappe.get_all(
            "Listing Variant",
            filters={"listing": listing.name, "status": "Active"},
            fields=[
                "name", "variant_name", "variant_code", "sku", "barcode",
                "selling_price", "stock_qty", "available_qty", "primary_image",
                "is_default", "status"
            ],
            order_by="display_order asc",
        )

        # Get variant attributes
        for variant in variants:
            attrs = frappe.get_all(
                "Listing Variant Attribute",
                filters={"parent": variant["name"]},
                fields=["attribute", "attribute_value"],
            )
            variant["attributes"] = {a["attribute"]: a["attribute_value"] for a in attrs}

        response["variants"] = variants

    return response


@frappe.whitelist()
def update_listing(
    listing_name: str,
    **kwargs,
) -> Dict[str, Any]:
    """
    Update an existing listing.

    Args:
        listing_name: Name of the listing to update
        **kwargs: Fields to update

    Returns:
        dict: Update result

    Example:
        POST /api/method/tr_tradehub.api.v1.listing.update_listing
        {
            "listing_name": "LST-00001",
            "title": "Updated Title",
            "selling_price": 50000
        }
    """
    check_rate_limit("listing_update")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not listing_name:
        frappe.throw(_("Listing name is required"))

    if not frappe.db.exists("Listing", listing_name):
        frappe.throw(_("Listing not found"))

    # Validate ownership
    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)

    # Check if listing can be updated
    if listing.docstatus == 2:
        frappe.throw(_("Cancelled listing cannot be updated"))

    # Allowed fields for update
    allowed_fields = [
        "title", "brand", "short_description", "description",
        "sku", "barcode", "mpn", "gtin", "stock_uom",
        "min_order_qty", "max_order_qty", "track_inventory", "allow_backorders",
        "weight", "weight_uom", "length", "width", "height", "dimension_uom",
        "primary_image", "images", "video_url", "attributes",
        "condition", "condition_notes", "currency", "cost_price",
        "compare_at_price", "tax_rate", "tax_included",
        "b2b_enabled", "wholesale_price", "wholesale_min_qty",
        "bulk_pricing_enabled", "bulk_pricing_tiers",
        "is_on_sale", "sale_start_date", "sale_end_date",
        "visibility_start_date", "visibility_end_date", "is_visible",
        "meta_title", "meta_description", "meta_keywords", "og_image",
        "shipping_enabled", "free_shipping", "shipping_class",
        "shipping_weight", "handling_time_days", "origin_country",
        "warranty_type", "warranty_period_months",
        "return_allowed", "return_period_days", "return_policy_notes",
    ]

    # Restricted fields that require admin permission or special status
    restricted_fields = [
        "category", "subcategory", "selling_price", "base_price",
        "stock_qty", "listing_type",
    ]

    # Admin can update additional fields
    is_admin = frappe.has_permission("Listing", "write")
    if is_admin:
        allowed_fields.extend(restricted_fields)
        allowed_fields.extend([
            "status", "moderation_status", "is_featured", "is_best_seller",
            "is_new_arrival", "feature_priority", "requires_approval",
            "moderation_notes", "rejection_reason",
        ])

    # Sellers can update restricted fields only in Draft status
    if listing.docstatus == 0:
        allowed_fields.extend(restricted_fields)

    # Update allowed fields
    updated_fields = []
    for field in allowed_fields:
        if field in kwargs:
            setattr(listing, field, kwargs[field])
            updated_fields.append(field)

    if not updated_fields:
        return {
            "success": True,
            "message": _("No changes to update"),
            "listing": listing_name,
        }

    # Validate prices if being updated
    if "selling_price" in kwargs or "base_price" in kwargs:
        if flt(listing.selling_price) <= 0:
            frappe.throw(_("Selling price must be greater than 0"))
        if flt(listing.selling_price) > flt(listing.base_price):
            frappe.throw(_("Selling price cannot be greater than base price"))

    listing.save()

    _log_listing_event(
        "updated",
        user,
        {"listing": listing_name, "updated_fields": updated_fields},
    )

    return {
        "success": True,
        "message": _("Listing updated successfully"),
        "listing": listing_name,
        "updated_fields": updated_fields,
        "status": listing.status,
    }


@frappe.whitelist()
def delete_listing(listing_name: str) -> Dict[str, Any]:
    """
    Delete a listing (only allowed for draft listings).

    For submitted listings, use archive_listing instead.

    Args:
        listing_name: Name of the listing to delete

    Returns:
        dict: Deletion result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not listing_name:
        frappe.throw(_("Listing name is required"))

    if not frappe.db.exists("Listing", listing_name):
        frappe.throw(_("Listing not found"))

    # Validate ownership
    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)

    # Only draft listings can be deleted
    if listing.docstatus != 0:
        frappe.throw(
            _("Only draft listings can be deleted. Use archive for submitted listings.")
        )

    listing_code = listing.listing_code
    listing.delete()

    _log_listing_event(
        "deleted",
        user,
        {"listing": listing_name, "listing_code": listing_code},
    )

    return {
        "success": True,
        "message": _("Listing deleted successfully"),
    }


# =============================================================================
# LISTING STATUS ENDPOINTS
# =============================================================================


@frappe.whitelist()
def submit_listing(listing_name: str) -> Dict[str, Any]:
    """
    Submit a draft listing for publication.

    Args:
        listing_name: Name of the listing to submit

    Returns:
        dict: Submission result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)

    if listing.docstatus != 0:
        frappe.throw(_("Only draft listings can be submitted"))

    listing.submit()

    _log_listing_event(
        "submitted",
        user,
        {"listing": listing_name, "status": listing.status},
    )

    return {
        "success": True,
        "message": _("Listing submitted successfully"),
        "listing": listing_name,
        "status": listing.status,
        "moderation_status": listing.moderation_status,
    }


@frappe.whitelist()
def publish_listing(listing_name: str) -> Dict[str, Any]:
    """
    Publish a listing (make it active).

    Args:
        listing_name: Name of the listing to publish

    Returns:
        dict: Publication result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)
    listing.publish()

    _log_listing_event("published", user, {"listing": listing_name})

    return {
        "success": True,
        "message": _("Listing published successfully"),
        "listing": listing_name,
        "status": listing.status,
        "published_at": listing.published_at,
    }


@frappe.whitelist()
def pause_listing(listing_name: str) -> Dict[str, Any]:
    """
    Pause a listing (temporarily hide from marketplace).

    Args:
        listing_name: Name of the listing to pause

    Returns:
        dict: Result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)
    listing.pause()

    _log_listing_event("paused", user, {"listing": listing_name})

    return {
        "success": True,
        "message": _("Listing paused"),
        "listing": listing_name,
        "status": listing.status,
    }


@frappe.whitelist()
def unpause_listing(listing_name: str) -> Dict[str, Any]:
    """
    Unpause a listing (make it active again).

    Args:
        listing_name: Name of the listing to unpause

    Returns:
        dict: Result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)
    listing.unpause()

    _log_listing_event("unpaused", user, {"listing": listing_name})

    return {
        "success": True,
        "message": _("Listing activated"),
        "listing": listing_name,
        "status": listing.status,
    }


@frappe.whitelist()
def archive_listing(listing_name: str) -> Dict[str, Any]:
    """
    Archive a listing.

    Args:
        listing_name: Name of the listing to archive

    Returns:
        dict: Result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)
    listing.archive()

    _log_listing_event("archived", user, {"listing": listing_name})

    return {
        "success": True,
        "message": _("Listing archived"),
        "listing": listing_name,
        "status": listing.status,
    }


# =============================================================================
# LISTING SEARCH & DISCOVERY
# =============================================================================


@frappe.whitelist(allow_guest=True)
def search_listings(
    query: Optional[str] = None,
    category: Optional[str] = None,
    seller: Optional[str] = None,
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    condition: Optional[str] = None,
    listing_type: Optional[str] = None,
    in_stock_only: bool = False,
    on_sale_only: bool = False,
    featured_only: bool = False,
    has_free_shipping: bool = False,
    min_rating: Optional[float] = None,
    attributes: Optional[str] = None,
    sort_by: str = "relevance",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    Search and filter marketplace listings.

    Args:
        query: Search query (searches title, description, brand, sku)
        category: Filter by category
        seller: Filter by seller
        brand: Filter by brand
        min_price: Minimum price filter
        max_price: Maximum price filter
        condition: Filter by condition (New, Used, Refurbished)
        listing_type: Filter by type (Fixed Price, Auction, RFQ)
        in_stock_only: Only show in-stock items
        on_sale_only: Only show items on sale
        featured_only: Only show featured items
        has_free_shipping: Only show items with free shipping
        min_rating: Minimum average rating filter
        attributes: JSON string of attribute filters
        sort_by: Sort field (relevance, price, rating, newest, popularity)
        sort_order: Sort order (ASC/DESC)
        page: Page number
        page_size: Results per page

    Returns:
        dict: Search results with pagination

    Example:
        POST /api/method/tr_tradehub.api.v1.listing.search_listings
        {
            "query": "iPhone",
            "category": "Electronics",
            "min_price": 10000,
            "max_price": 50000,
            "sort_by": "price",
            "sort_order": "ASC"
        }
    """
    check_rate_limit("listing_search", throw=False)

    # Limit page size
    page_size = min(cint(page_size), MAX_PAGE_SIZE) or DEFAULT_PAGE_SIZE
    page = max(cint(page), 1)

    # Build filters
    filters = {
        "status": ["in", ["Active", "Out of Stock"]],
        "is_visible": 1,
        "docstatus": 1,
    }

    if category:
        # Include subcategories
        filters["category"] = ["in", get_category_and_children(category)]

    if seller:
        filters["seller"] = seller

    if brand:
        filters["brand"] = brand

    if min_price:
        filters["selling_price"] = [">=", flt(min_price)]

    if max_price:
        if "selling_price" in filters:
            # Combine with min_price
            filters["selling_price"] = ["between", [flt(min_price), flt(max_price)]]
        else:
            filters["selling_price"] = ["<=", flt(max_price)]

    if condition:
        filters["condition"] = condition

    if listing_type:
        filters["listing_type"] = listing_type

    if in_stock_only:
        filters["available_qty"] = [">", 0]

    if on_sale_only:
        filters["is_on_sale"] = 1

    if featured_only:
        filters["is_featured"] = 1

    if has_free_shipping:
        filters["free_shipping"] = 1

    if min_rating:
        filters["average_rating"] = [">=", flt(min_rating)]

    # Parse attribute filters
    attribute_filters = {}
    if attributes:
        try:
            attribute_filters = json.loads(attributes)
        except json.JSONDecodeError:
            pass

    # Determine sort field
    sort_map = {
        "relevance": "modified",
        "price": "selling_price",
        "rating": "average_rating",
        "newest": "published_at",
        "popularity": "order_count",
        "views": "view_count",
    }
    sort_field = sort_map.get(sort_by, "modified")
    sort_direction = "DESC" if sort_order.upper() == "DESC" else "ASC"

    # Calculate pagination
    start = (page - 1) * page_size

    # Build or_filters for text search
    or_filters = None
    if query:
        query = query.strip()
        or_filters = [
            {"title": ["like", f"%{query}%"]},
            {"short_description": ["like", f"%{query}%"]},
            {"brand": ["like", f"%{query}%"]},
            {"sku": ["like", f"%{query}%"]},
            {"listing_code": ["like", f"%{query}%"]},
        ]

    # Get total count
    total = frappe.db.count("Listing", filters=filters, or_filters=or_filters)

    # Get listings
    listings = frappe.get_all(
        "Listing",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "listing_code", "title", "seller", "status",
            "listing_type", "category", "subcategory", "brand", "condition",
            "currency", "selling_price", "compare_at_price", "base_price",
            "available_qty", "stock_uom", "min_order_qty",
            "primary_image", "average_rating", "review_count", "view_count",
            "order_count", "is_on_sale", "is_featured", "is_best_seller",
            "is_new_arrival", "free_shipping", "published_at", "route",
        ],
        order_by=f"{sort_field} {sort_direction}",
        start=start,
        limit_page_length=page_size,
    )

    # Calculate discount percentage for each listing
    for listing in listings:
        if listing.get("compare_at_price") and flt(listing["compare_at_price"]) > 0:
            discount = (
                (flt(listing["compare_at_price"]) - flt(listing["selling_price"]))
                / flt(listing["compare_at_price"]) * 100
            )
            listing["discount_percentage"] = round(discount, 0)
        else:
            listing["discount_percentage"] = 0

    return {
        "success": True,
        "listings": listings,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "filters_applied": {
            "query": query,
            "category": category,
            "seller": seller,
            "brand": brand,
            "min_price": min_price,
            "max_price": max_price,
            "condition": condition,
            "listing_type": listing_type,
        },
    }


def get_category_and_children(category: str) -> List[str]:
    """Get category and all its child categories."""
    categories = [category]

    children = frappe.get_all(
        "Category",
        filters={"parent_category": category},
        pluck="name",
    )

    for child in children:
        categories.extend(get_category_and_children(child))

    return categories


@frappe.whitelist(allow_guest=True)
def get_featured_listings(
    limit: int = 12,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get featured listings for homepage/discovery.

    Args:
        limit: Maximum number of listings to return
        category: Optional category filter

    Returns:
        list: Featured listings
    """
    filters = {
        "status": "Active",
        "is_visible": 1,
        "is_featured": 1,
        "docstatus": 1,
    }

    if category:
        filters["category"] = ["in", get_category_and_children(category)]

    return frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category", "brand",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "review_count",
            "is_on_sale", "free_shipping", "route",
        ],
        order_by="feature_priority DESC, average_rating DESC",
        limit_page_length=min(cint(limit), 50),
    )


@frappe.whitelist(allow_guest=True)
def get_new_arrivals(
    limit: int = 12,
    category: Optional[str] = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Get new arrival listings.

    Args:
        limit: Maximum number of listings to return
        category: Optional category filter
        days: How many days back to consider as "new"

    Returns:
        list: New arrival listings
    """
    cutoff_date = add_days(nowdate(), -cint(days))

    filters = {
        "status": "Active",
        "is_visible": 1,
        "docstatus": 1,
        "published_at": [">=", cutoff_date],
    }

    if category:
        filters["category"] = ["in", get_category_and_children(category)]

    return frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category", "brand",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "review_count",
            "is_on_sale", "free_shipping", "published_at", "route",
        ],
        order_by="published_at DESC",
        limit_page_length=min(cint(limit), 50),
    )


@frappe.whitelist(allow_guest=True)
def get_best_sellers(
    limit: int = 12,
    category: Optional[str] = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Get best selling listings.

    Args:
        limit: Maximum number of listings to return
        category: Optional category filter
        days: Time period to consider for sales

    Returns:
        list: Best selling listings
    """
    filters = {
        "status": "Active",
        "is_visible": 1,
        "docstatus": 1,
        "order_count": [">", 0],
    }

    if category:
        filters["category"] = ["in", get_category_and_children(category)]

    return frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category", "brand",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "review_count", "order_count",
            "is_on_sale", "free_shipping", "route",
        ],
        order_by="order_count DESC, average_rating DESC",
        limit_page_length=min(cint(limit), 50),
    )


@frappe.whitelist(allow_guest=True)
def get_deals(
    limit: int = 12,
    category: Optional[str] = None,
    min_discount: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get listings currently on sale.

    Args:
        limit: Maximum number of listings to return
        category: Optional category filter
        min_discount: Minimum discount percentage

    Returns:
        list: Listings on sale
    """
    filters = {
        "status": "Active",
        "is_visible": 1,
        "is_on_sale": 1,
        "docstatus": 1,
    }

    if category:
        filters["category"] = ["in", get_category_and_children(category)]

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category", "brand",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "review_count",
            "free_shipping", "sale_end_date", "route",
        ],
        order_by="modified DESC",
        limit_page_length=100,  # Get more to filter by discount
    )

    # Filter by minimum discount and calculate discount percentage
    filtered = []
    for listing in listings:
        if listing.get("compare_at_price") and flt(listing["compare_at_price"]) > 0:
            discount = (
                (flt(listing["compare_at_price"]) - flt(listing["selling_price"]))
                / flt(listing["compare_at_price"]) * 100
            )
            if discount >= min_discount:
                listing["discount_percentage"] = round(discount, 0)
                filtered.append(listing)

    # Sort by discount and limit
    filtered.sort(key=lambda x: x["discount_percentage"], reverse=True)
    return filtered[:min(cint(limit), 50)]


@frappe.whitelist(allow_guest=True)
def get_similar_listings(
    listing_name: str,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """
    Get similar listings based on category and attributes.

    Args:
        listing_name: Name of the reference listing
        limit: Maximum number of listings to return

    Returns:
        list: Similar listings
    """
    if not frappe.db.exists("Listing", listing_name):
        return []

    listing = frappe.db.get_value(
        "Listing",
        listing_name,
        ["category", "subcategory", "brand", "selling_price", "seller"],
        as_dict=True,
    )

    if not listing:
        return []

    # Build filters for similar items
    filters = {
        "status": "Active",
        "is_visible": 1,
        "docstatus": 1,
        "name": ["!=", listing_name],
    }

    # Try to match subcategory first, then category
    if listing.get("subcategory"):
        filters["subcategory"] = listing["subcategory"]
    elif listing.get("category"):
        filters["category"] = listing["category"]

    # Exclude same seller
    filters["seller"] = ["!=", listing["seller"]]

    return frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category", "brand",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "review_count",
            "is_on_sale", "free_shipping", "route",
        ],
        order_by="average_rating DESC, order_count DESC",
        limit_page_length=min(cint(limit), 20),
    )


# =============================================================================
# SELLER LISTING MANAGEMENT
# =============================================================================


@frappe.whitelist()
def get_my_listings(
    status: Optional[str] = None,
    moderation_status: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    sort_by: str = "modified",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    Get listings for the current seller.

    Args:
        status: Filter by status
        moderation_status: Filter by moderation status
        category: Filter by category
        query: Search query
        sort_by: Sort field
        sort_order: Sort order
        page: Page number
        page_size: Results per page

    Returns:
        dict: Seller's listings with pagination
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    seller = get_current_seller()
    if not seller:
        return {
            "success": False,
            "message": _("No seller profile found"),
            "listings": [],
            "total": 0,
        }

    # Build filters
    filters = {"seller": seller}

    if status:
        filters["status"] = status

    if moderation_status:
        filters["moderation_status"] = moderation_status

    if category:
        filters["category"] = category

    # Build or_filters for search
    or_filters = None
    if query:
        query = query.strip()
        or_filters = [
            {"title": ["like", f"%{query}%"]},
            {"sku": ["like", f"%{query}%"]},
            {"listing_code": ["like", f"%{query}%"]},
        ]

    # Pagination
    page_size = min(cint(page_size), MAX_PAGE_SIZE) or DEFAULT_PAGE_SIZE
    page = max(cint(page), 1)
    start = (page - 1) * page_size

    # Get total count
    total = frappe.db.count("Listing", filters=filters, or_filters=or_filters)

    # Get listings
    listings = frappe.get_all(
        "Listing",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "listing_code", "title", "status", "moderation_status",
            "listing_type", "category", "brand", "sku",
            "currency", "selling_price", "compare_at_price",
            "stock_qty", "available_qty", "reserved_qty",
            "primary_image", "average_rating", "review_count",
            "view_count", "order_count", "wishlist_count",
            "is_on_sale", "is_featured", "quality_score",
            "docstatus", "creation", "modified",
        ],
        order_by=f"{sort_by} {sort_order}",
        start=start,
        limit_page_length=page_size,
    )

    return {
        "success": True,
        "listings": listings,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "seller": seller,
    }


@frappe.whitelist()
def get_listing_statistics(seller: Optional[str] = None) -> Dict[str, Any]:
    """
    Get listing statistics for a seller.

    Args:
        seller: Seller profile name (optional, defaults to current user's seller)

    Returns:
        dict: Listing statistics
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not seller:
        seller = get_current_seller()

    if not seller:
        return {"success": False, "message": _("No seller profile found")}

    # Verify permission
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if seller_user != user and not frappe.has_permission("Listing", "read"):
        frappe.throw(_("Not permitted to view these statistics"))

    # Get status counts
    status_counts = frappe.db.sql(
        """
        SELECT status, COUNT(*) as count
        FROM `tabListing`
        WHERE seller = %s
        GROUP BY status
        """,
        seller,
        as_dict=True,
    )

    status_breakdown = {s["status"]: s["count"] for s in status_counts}
    total = sum(status_breakdown.values())

    # Get moderation status counts
    moderation_counts = frappe.db.sql(
        """
        SELECT moderation_status, COUNT(*) as count
        FROM `tabListing`
        WHERE seller = %s
        GROUP BY moderation_status
        """,
        seller,
        as_dict=True,
    )

    moderation_breakdown = {m["moderation_status"]: m["count"] for m in moderation_counts}

    # Get aggregate stats
    aggregate = frappe.db.sql(
        """
        SELECT
            COALESCE(SUM(view_count), 0) as total_views,
            COALESCE(SUM(order_count), 0) as total_orders,
            COALESCE(SUM(wishlist_count), 0) as total_wishlists,
            COALESCE(AVG(average_rating), 0) as avg_rating,
            COALESCE(SUM(review_count), 0) as total_reviews,
            COALESCE(AVG(quality_score), 0) as avg_quality_score
        FROM `tabListing`
        WHERE seller = %s AND docstatus = 1
        """,
        seller,
        as_dict=True,
    )

    # Get category distribution
    category_distribution = frappe.db.sql(
        """
        SELECT category, COUNT(*) as count
        FROM `tabListing`
        WHERE seller = %s
        GROUP BY category
        ORDER BY count DESC
        LIMIT 10
        """,
        seller,
        as_dict=True,
    )

    # Get low stock listings count
    low_stock = frappe.db.count(
        "Listing",
        filters={
            "seller": seller,
            "status": "Active",
            "track_inventory": 1,
            "available_qty": ["<", 5],
        },
    )

    return {
        "success": True,
        "seller": seller,
        "total": total,
        "active": status_breakdown.get("Active", 0),
        "draft": status_breakdown.get("Draft", 0),
        "pending_review": status_breakdown.get("Pending Review", 0),
        "out_of_stock": status_breakdown.get("Out of Stock", 0),
        "paused": status_breakdown.get("Paused", 0),
        "suspended": status_breakdown.get("Suspended", 0),
        "rejected": status_breakdown.get("Rejected", 0),
        "archived": status_breakdown.get("Archived", 0),
        "status_breakdown": status_breakdown,
        "moderation_breakdown": moderation_breakdown,
        "total_views": cint(aggregate[0]["total_views"]) if aggregate else 0,
        "total_orders": cint(aggregate[0]["total_orders"]) if aggregate else 0,
        "total_wishlists": cint(aggregate[0]["total_wishlists"]) if aggregate else 0,
        "total_reviews": cint(aggregate[0]["total_reviews"]) if aggregate else 0,
        "average_rating": round(flt(aggregate[0]["avg_rating"]), 2) if aggregate else 0,
        "average_quality_score": round(flt(aggregate[0]["avg_quality_score"]), 1) if aggregate else 0,
        "low_stock_count": low_stock,
        "category_distribution": category_distribution,
    }


# =============================================================================
# INVENTORY MANAGEMENT
# =============================================================================


@frappe.whitelist()
def update_stock(
    listing_name: str,
    qty_change: float,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update listing stock quantity.

    Args:
        listing_name: Name of the listing
        qty_change: Quantity to add (positive) or subtract (negative)
        reason: Reason for stock change

    Returns:
        dict: Updated stock information
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)
    listing.update_stock(flt(qty_change), reason)

    _log_listing_event(
        "stock_updated",
        user,
        {"listing": listing_name, "qty_change": qty_change, "reason": reason},
    )

    return {
        "success": True,
        "message": _("Stock updated successfully"),
        "listing": listing_name,
        "stock_qty": listing.stock_qty,
        "available_qty": listing.available_qty,
        "reserved_qty": listing.reserved_qty,
        "status": listing.status,
    }


@frappe.whitelist()
def bulk_update_stock(
    updates: str,
) -> Dict[str, Any]:
    """
    Bulk update stock for multiple listings.

    Args:
        updates: JSON string of [{listing: name, qty_change: value, reason: text}, ...]

    Returns:
        dict: Results of bulk update
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    try:
        update_list = json.loads(updates)
    except json.JSONDecodeError:
        frappe.throw(_("Invalid updates format"))

    if not update_list or not isinstance(update_list, list):
        frappe.throw(_("Updates must be a list"))

    seller = get_current_seller()
    results = []
    errors = []

    for update in update_list:
        listing_name = update.get("listing")
        qty_change = flt(update.get("qty_change", 0))
        reason = update.get("reason")

        if not listing_name:
            errors.append({"error": _("Listing name is required"), "data": update})
            continue

        try:
            # Verify ownership
            listing_seller = frappe.db.get_value("Listing", listing_name, "seller")
            if listing_seller != seller and not frappe.has_permission("Listing", "write"):
                errors.append({"listing": listing_name, "error": _("Not permitted")})
                continue

            listing = frappe.get_doc("Listing", listing_name)
            listing.update_stock(qty_change, reason)

            results.append({
                "listing": listing_name,
                "success": True,
                "stock_qty": listing.stock_qty,
                "available_qty": listing.available_qty,
            })

        except Exception as e:
            errors.append({"listing": listing_name, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "results": results,
        "errors": errors,
        "total_updated": len(results),
        "total_errors": len(errors),
    }


@frappe.whitelist()
def get_low_stock_listings(
    threshold: int = 5,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    Get listings with low stock.

    Args:
        threshold: Stock threshold to consider as low
        page: Page number
        page_size: Results per page

    Returns:
        dict: Low stock listings
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    seller = get_current_seller()
    if not seller:
        frappe.throw(_("No seller profile found"))

    filters = {
        "seller": seller,
        "status": ["in", ["Active", "Out of Stock"]],
        "track_inventory": 1,
        "available_qty": ["<=", cint(threshold)],
    }

    page_size = min(cint(page_size), MAX_PAGE_SIZE)
    start = (cint(page) - 1) * page_size

    total = frappe.db.count("Listing", filters)

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "sku",
            "stock_qty", "available_qty", "reserved_qty",
            "status", "primary_image",
        ],
        order_by="available_qty ASC",
        start=start,
        limit_page_length=page_size,
    )

    return {
        "success": True,
        "listings": listings,
        "total": total,
        "page": cint(page),
        "page_size": page_size,
        "threshold": cint(threshold),
    }


# =============================================================================
# LISTING MODERATION (Admin)
# =============================================================================


@frappe.whitelist()
def approve_listing(listing_name: str) -> Dict[str, Any]:
    """
    Approve a listing (admin only).

    Args:
        listing_name: Name of the listing to approve

    Returns:
        dict: Approval result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to approve listings"))

    listing = frappe.get_doc("Listing", listing_name)
    listing.approve(frappe.session.user)

    _log_listing_event(
        "approved",
        frappe.session.user,
        {"listing": listing_name},
    )

    return {
        "success": True,
        "message": _("Listing approved"),
        "listing": listing_name,
        "status": listing.status,
        "moderation_status": listing.moderation_status,
    }


@frappe.whitelist()
def reject_listing(
    listing_name: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Reject a listing (admin only).

    Args:
        listing_name: Name of the listing to reject
        reason: Reason for rejection

    Returns:
        dict: Rejection result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to reject listings"))

    if not reason:
        frappe.throw(_("Rejection reason is required"))

    listing = frappe.get_doc("Listing", listing_name)
    listing.reject(reason, frappe.session.user)

    _log_listing_event(
        "rejected",
        frappe.session.user,
        {"listing": listing_name, "reason": reason},
    )

    return {
        "success": True,
        "message": _("Listing rejected"),
        "listing": listing_name,
        "status": listing.status,
        "moderation_status": listing.moderation_status,
    }


@frappe.whitelist()
def flag_listing(
    listing_name: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Flag a listing for review.

    Args:
        listing_name: Name of the listing to flag
        reason: Reason for flagging

    Returns:
        dict: Result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to flag listings"))

    listing = frappe.get_doc("Listing", listing_name)
    listing.flag(reason)

    _log_listing_event(
        "flagged",
        frappe.session.user,
        {"listing": listing_name, "reason": reason},
    )

    return {
        "success": True,
        "message": _("Listing flagged for review"),
        "listing": listing_name,
        "moderation_status": listing.moderation_status,
    }


@frappe.whitelist()
def suspend_listing(
    listing_name: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Suspend a listing (admin only).

    Args:
        listing_name: Name of the listing to suspend
        reason: Reason for suspension

    Returns:
        dict: Suspension result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to suspend listings"))

    if not reason:
        frappe.throw(_("Suspension reason is required"))

    listing = frappe.get_doc("Listing", listing_name)
    listing.suspend(reason)

    _log_listing_event(
        "suspended",
        frappe.session.user,
        {"listing": listing_name, "reason": reason},
    )

    return {
        "success": True,
        "message": _("Listing suspended"),
        "listing": listing_name,
        "status": listing.status,
    }


@frappe.whitelist()
def get_pending_moderation(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    Get listings pending moderation (admin only).

    Args:
        page: Page number
        page_size: Results per page

    Returns:
        dict: Listings pending moderation
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to view moderation queue"))

    filters = {
        "moderation_status": ["in", ["Pending", "Flagged"]],
        "docstatus": 1,
    }

    page_size = min(cint(page_size), MAX_PAGE_SIZE)
    start = (cint(page) - 1) * page_size

    total = frappe.db.count("Listing", filters)

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "status",
            "moderation_status", "category", "selling_price",
            "primary_image", "creation", "modified",
        ],
        order_by="creation ASC",
        start=start,
        limit_page_length=page_size,
    )

    # Add seller details
    for listing in listings:
        listing["seller_details"] = frappe.db.get_value(
            "Seller Profile",
            listing["seller"],
            ["seller_name", "verification_status"],
            as_dict=True,
        )

    return {
        "success": True,
        "listings": listings,
        "total": total,
        "page": cint(page),
        "page_size": page_size,
    }


# =============================================================================
# LISTING VARIANTS
# =============================================================================


@frappe.whitelist()
def create_variant(
    listing_name: str,
    variant_name: str,
    attributes: str,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a variant for a listing.

    Args:
        listing_name: Parent listing name
        variant_name: Name for the variant
        attributes: JSON string of attribute-value pairs
        **kwargs: Additional variant fields

    Returns:
        dict: Created variant information
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    # Parse attributes
    try:
        attr_dict = json.loads(attributes)
    except json.JSONDecodeError:
        frappe.throw(_("Invalid attributes format"))

    if not attr_dict:
        frappe.throw(_("At least one attribute is required"))

    # Build variant data
    variant_data = {
        "doctype": "Listing Variant",
        "listing": listing_name,
        "variant_name": variant_name.strip(),
    }

    # Add optional fields
    optional_fields = [
        "sku", "barcode", "selling_price", "cost_price", "compare_at_price",
        "stock_qty", "primary_image", "images", "weight", "weight_uom",
        "status", "is_default",
    ]

    for field in optional_fields:
        if field in kwargs and kwargs[field] is not None:
            variant_data[field] = kwargs[field]

    # Create variant
    variant = frappe.get_doc(variant_data)

    # Add variant attributes
    for attr_name, attr_value in attr_dict.items():
        variant.append("attributes", {
            "attribute": attr_name,
            "attribute_value": str(attr_value),
        })

    variant.insert()

    # Mark parent listing as having variants
    frappe.db.set_value("Listing", listing_name, "has_variants", 1)

    _log_listing_event(
        "variant_created",
        user,
        {"listing": listing_name, "variant": variant.name},
    )

    return {
        "success": True,
        "message": _("Variant created successfully"),
        "variant": variant.name,
        "variant_code": variant.variant_code,
    }


@frappe.whitelist()
def get_listing_variants(listing_name: str) -> Dict[str, Any]:
    """
    Get all variants for a listing.

    Args:
        listing_name: Parent listing name

    Returns:
        dict: List of variants
    """
    if not frappe.db.exists("Listing", listing_name):
        frappe.throw(_("Listing not found"))

    variants = frappe.get_all(
        "Listing Variant",
        filters={"listing": listing_name},
        fields=[
            "name", "variant_name", "variant_code", "sku", "barcode",
            "selling_price", "stock_qty", "available_qty",
            "primary_image", "is_default", "status", "display_order",
        ],
        order_by="display_order ASC, name ASC",
    )

    # Get attributes for each variant
    for variant in variants:
        attrs = frappe.get_all(
            "Listing Variant Attribute",
            filters={"parent": variant["name"]},
            fields=["attribute", "attribute_value"],
        )
        variant["attributes"] = {a["attribute"]: a["attribute_value"] for a in attrs}

    return {
        "success": True,
        "listing": listing_name,
        "variants": variants,
        "total": len(variants),
    }


@frappe.whitelist()
def update_variant(
    variant_name: str,
    **kwargs,
) -> Dict[str, Any]:
    """
    Update a listing variant.

    Args:
        variant_name: Name of the variant to update
        **kwargs: Fields to update

    Returns:
        dict: Update result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not frappe.db.exists("Listing Variant", variant_name):
        frappe.throw(_("Variant not found"))

    variant = frappe.get_doc("Listing Variant", variant_name)

    # Validate ownership of parent listing
    validate_listing_ownership(variant.listing)

    # Allowed fields
    allowed_fields = [
        "variant_name", "sku", "barcode", "selling_price", "cost_price",
        "compare_at_price", "stock_qty", "primary_image", "images",
        "weight", "weight_uom", "status", "is_default", "display_order",
    ]

    for field in allowed_fields:
        if field in kwargs:
            setattr(variant, field, kwargs[field])

    variant.save()

    return {
        "success": True,
        "message": _("Variant updated successfully"),
        "variant": variant_name,
    }


@frappe.whitelist()
def delete_variant(variant_name: str) -> Dict[str, Any]:
    """
    Delete a listing variant.

    Args:
        variant_name: Name of the variant to delete

    Returns:
        dict: Deletion result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not frappe.db.exists("Listing Variant", variant_name):
        frappe.throw(_("Variant not found"))

    variant = frappe.get_doc("Listing Variant", variant_name)

    # Validate ownership of parent listing
    validate_listing_ownership(variant.listing)

    listing_name = variant.listing
    variant.delete()

    # Check if any variants remain
    remaining = frappe.db.count("Listing Variant", {"listing": listing_name})
    if remaining == 0:
        frappe.db.set_value("Listing", listing_name, "has_variants", 0)

    return {
        "success": True,
        "message": _("Variant deleted successfully"),
    }


# =============================================================================
# MEDIA MANAGEMENT
# =============================================================================


@frappe.whitelist()
def upload_listing_image(
    listing_name: str,
    file_url: str,
    is_primary: bool = False,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Add an image to a listing.

    Args:
        listing_name: Name of the listing
        file_url: URL of the uploaded file
        is_primary: Set as primary image
        position: Position in image array

    Returns:
        dict: Upload result
    """
    check_rate_limit("media_upload")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)

    if is_primary:
        listing.primary_image = file_url
    else:
        # Add to images array
        images = json.loads(listing.images or "[]")
        if position is not None and 0 <= position <= len(images):
            images.insert(position, file_url)
        else:
            images.append(file_url)
        listing.images = json.dumps(images)

    listing.save()

    return {
        "success": True,
        "message": _("Image added successfully"),
        "listing": listing_name,
        "file_url": file_url,
        "is_primary": is_primary,
    }


@frappe.whitelist()
def remove_listing_image(
    listing_name: str,
    file_url: str,
) -> Dict[str, Any]:
    """
    Remove an image from a listing.

    Args:
        listing_name: Name of the listing
        file_url: URL of the image to remove

    Returns:
        dict: Removal result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    listing = frappe.get_doc("Listing", listing_name)

    # Check if it's the primary image
    if listing.primary_image == file_url:
        listing.primary_image = None

    # Remove from images array
    images = json.loads(listing.images or "[]")
    if file_url in images:
        images.remove(file_url)
        listing.images = json.dumps(images)

    listing.save()

    return {
        "success": True,
        "message": _("Image removed successfully"),
        "listing": listing_name,
    }


@frappe.whitelist()
def reorder_listing_images(
    listing_name: str,
    images: str,
) -> Dict[str, Any]:
    """
    Reorder listing images.

    Args:
        listing_name: Name of the listing
        images: JSON array of image URLs in new order

    Returns:
        dict: Result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    validate_listing_ownership(listing_name)

    try:
        image_list = json.loads(images)
    except json.JSONDecodeError:
        frappe.throw(_("Invalid images format"))

    listing = frappe.get_doc("Listing", listing_name)
    listing.images = json.dumps(image_list)
    listing.save()

    return {
        "success": True,
        "message": _("Images reordered successfully"),
        "listing": listing_name,
    }


# =============================================================================
# BULK OPERATIONS
# =============================================================================


@frappe.whitelist()
def bulk_update_listings(
    listing_names: str,
    updates: str,
) -> Dict[str, Any]:
    """
    Bulk update multiple listings.

    Args:
        listing_names: JSON array of listing names
        updates: JSON object of fields to update

    Returns:
        dict: Bulk update results
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    try:
        names = json.loads(listing_names)
        update_dict = json.loads(updates)
    except json.JSONDecodeError:
        frappe.throw(_("Invalid JSON format"))

    if not names or not isinstance(names, list):
        frappe.throw(_("Listing names must be a list"))

    if not update_dict or not isinstance(update_dict, dict):
        frappe.throw(_("Updates must be an object"))

    seller = get_current_seller()
    results = []
    errors = []

    # Allowed bulk update fields
    allowed_fields = [
        "is_visible", "is_on_sale", "category", "brand",
        "shipping_class", "handling_time_days", "free_shipping",
    ]

    # Filter to allowed fields only
    filtered_updates = {k: v for k, v in update_dict.items() if k in allowed_fields}

    if not filtered_updates:
        frappe.throw(_("No valid fields to update"))

    for listing_name in names:
        try:
            # Verify ownership
            listing_seller = frappe.db.get_value("Listing", listing_name, "seller")
            if listing_seller != seller and not frappe.has_permission("Listing", "write"):
                errors.append({"listing": listing_name, "error": _("Not permitted")})
                continue

            # Update listing
            frappe.db.set_value("Listing", listing_name, filtered_updates)
            results.append({"listing": listing_name, "success": True})

        except Exception as e:
            errors.append({"listing": listing_name, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "results": results,
        "errors": errors,
        "total_updated": len(results),
        "total_errors": len(errors),
    }


@frappe.whitelist()
def bulk_change_status(
    listing_names: str,
    action: str,
) -> Dict[str, Any]:
    """
    Bulk change status of multiple listings.

    Args:
        listing_names: JSON array of listing names
        action: Action to perform (pause, unpause, archive)

    Returns:
        dict: Bulk operation results
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    try:
        names = json.loads(listing_names)
    except json.JSONDecodeError:
        frappe.throw(_("Invalid listing names format"))

    if not names or not isinstance(names, list):
        frappe.throw(_("Listing names must be a list"))

    if action not in ["pause", "unpause", "archive"]:
        frappe.throw(_("Invalid action"))

    seller = get_current_seller()
    results = []
    errors = []

    for listing_name in names:
        try:
            # Verify ownership
            listing_seller = frappe.db.get_value("Listing", listing_name, "seller")
            if listing_seller != seller and not frappe.has_permission("Listing", "write"):
                errors.append({"listing": listing_name, "error": _("Not permitted")})
                continue

            listing = frappe.get_doc("Listing", listing_name)

            if action == "pause":
                listing.pause()
            elif action == "unpause":
                listing.unpause()
            elif action == "archive":
                listing.archive()

            results.append({
                "listing": listing_name,
                "success": True,
                "status": listing.status,
            })

        except Exception as e:
            errors.append({"listing": listing_name, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "results": results,
        "errors": errors,
        "total_updated": len(results),
        "total_errors": len(errors),
    }


# =============================================================================
# TRACKING & ANALYTICS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def record_view(listing_name: str) -> Dict[str, Any]:
    """
    Record a listing view.

    Args:
        listing_name: Name of the listing viewed

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Listing", listing_name):
        return {"success": False}

    # Increment view count (don't update modified timestamp)
    frappe.db.set_value(
        "Listing", listing_name, "view_count",
        frappe.db.get_value("Listing", listing_name, "view_count") + 1,
        update_modified=False,
    )

    return {"success": True}


@frappe.whitelist()
def toggle_wishlist(listing_name: str) -> Dict[str, Any]:
    """
    Toggle listing in user's wishlist.

    Args:
        listing_name: Name of the listing

    Returns:
        dict: Result with current wishlist status
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not frappe.db.exists("Listing", listing_name):
        frappe.throw(_("Listing not found"))

    # Check if Wishlist DocType exists
    if not frappe.db.exists("DocType", "Wishlist"):
        # Simple implementation using User fields or cache
        cache_key = f"wishlist:{user}"
        wishlist = frappe.cache().get_value(cache_key) or []

        if listing_name in wishlist:
            wishlist.remove(listing_name)
            is_wishlisted = False
            # Decrement wishlist count
            frappe.db.set_value(
                "Listing", listing_name, "wishlist_count",
                max(0, frappe.db.get_value("Listing", listing_name, "wishlist_count") - 1),
                update_modified=False,
            )
        else:
            wishlist.append(listing_name)
            is_wishlisted = True
            # Increment wishlist count
            frappe.db.set_value(
                "Listing", listing_name, "wishlist_count",
                frappe.db.get_value("Listing", listing_name, "wishlist_count") + 1,
                update_modified=False,
            )

        frappe.cache().set_value(cache_key, wishlist)

        return {
            "success": True,
            "is_wishlisted": is_wishlisted,
            "message": _("Added to wishlist") if is_wishlisted else _("Removed from wishlist"),
        }

    # Use Wishlist DocType if it exists
    existing = frappe.db.exists(
        "Wishlist",
        {"user": user, "listing": listing_name},
    )

    if existing:
        frappe.delete_doc("Wishlist", existing)
        listing = frappe.get_doc("Listing", listing_name)
        listing.decrement_wishlist_count()
        is_wishlisted = False
    else:
        frappe.get_doc({
            "doctype": "Wishlist",
            "user": user,
            "listing": listing_name,
        }).insert()
        listing = frappe.get_doc("Listing", listing_name)
        listing.increment_wishlist_count()
        is_wishlisted = True

    return {
        "success": True,
        "is_wishlisted": is_wishlisted,
        "message": _("Added to wishlist") if is_wishlisted else _("Removed from wishlist"),
    }


@frappe.whitelist()
def get_wishlist() -> Dict[str, Any]:
    """
    Get user's wishlist.

    Returns:
        dict: List of wishlisted listings
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    # Check if Wishlist DocType exists
    if not frappe.db.exists("DocType", "Wishlist"):
        cache_key = f"wishlist:{user}"
        wishlist_names = frappe.cache().get_value(cache_key) or []

        if not wishlist_names:
            return {"success": True, "listings": [], "total": 0}

        listings = frappe.get_all(
            "Listing",
            filters={"name": ["in", wishlist_names]},
            fields=[
                "name", "listing_code", "title", "seller", "category",
                "currency", "selling_price", "compare_at_price",
                "primary_image", "average_rating", "available_qty",
                "status", "route",
            ],
        )

        return {
            "success": True,
            "listings": listings,
            "total": len(listings),
        }

    # Use Wishlist DocType
    wishlist_items = frappe.get_all(
        "Wishlist",
        filters={"user": user},
        pluck="listing",
    )

    if not wishlist_items:
        return {"success": True, "listings": [], "total": 0}

    listings = frappe.get_all(
        "Listing",
        filters={"name": ["in", wishlist_items]},
        fields=[
            "name", "listing_code", "title", "seller", "category",
            "currency", "selling_price", "compare_at_price",
            "primary_image", "average_rating", "available_qty",
            "status", "route",
        ],
    )

    return {
        "success": True,
        "listings": listings,
        "total": len(listings),
    }


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
Public API Endpoints:

Listing CRUD:
- create_listing: Create a new listing
- get_listing: Get listing details
- update_listing: Update listing fields
- delete_listing: Delete draft listing

Listing Status:
- submit_listing: Submit draft for publication
- publish_listing: Make listing active
- pause_listing: Temporarily hide listing
- unpause_listing: Reactivate paused listing
- archive_listing: Archive listing

Search & Discovery:
- search_listings: Search and filter listings (guest allowed)
- get_featured_listings: Get featured listings (guest allowed)
- get_new_arrivals: Get new arrival listings (guest allowed)
- get_best_sellers: Get best selling listings (guest allowed)
- get_deals: Get listings on sale (guest allowed)
- get_similar_listings: Get similar listings (guest allowed)

Seller Management:
- get_my_listings: Get current seller's listings
- get_listing_statistics: Get listing stats for seller

Inventory:
- update_stock: Update single listing stock
- bulk_update_stock: Bulk update stock
- get_low_stock_listings: Get low stock items

Moderation (Admin):
- approve_listing: Approve listing
- reject_listing: Reject listing with reason
- flag_listing: Flag for review
- suspend_listing: Suspend listing
- get_pending_moderation: Get moderation queue

Variants:
- create_variant: Create listing variant
- get_listing_variants: Get all variants
- update_variant: Update variant
- delete_variant: Delete variant

Media:
- upload_listing_image: Add image to listing
- remove_listing_image: Remove image
- reorder_listing_images: Reorder images

Bulk Operations:
- bulk_update_listings: Bulk update fields
- bulk_change_status: Bulk status change

Analytics:
- record_view: Record listing view (guest allowed)
- toggle_wishlist: Add/remove from wishlist
- get_wishlist: Get user's wishlist
"""
