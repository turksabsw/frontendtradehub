# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Seller Store API v1.

This module provides a comprehensive REST API for seller storefronts in the
Trade Hub B2B marketplace. It enables sellers to manage their storefront
configuration and allows buyers to browse seller stores.

Key Features:
- Complete store lifecycle management (create, update, publish, unpublish)
- Public store browsing for buyers
- Store product listing with pagination
- Theme customization and configuration
- Store statistics and analytics
- Multi-tenant data isolation

Usage Flow (Seller):
1. get_my_store() - Get current seller's store
2. create_store() - Create new store if none exists
3. update_store() - Update store settings and appearance
4. update_store_theme() - Apply theme preset or custom colors
5. upload_store_media() - Upload logo, banner, etc.
6. publish_store() - Make store visible to buyers
7. get_store_statistics() - View store performance metrics

Usage Flow (Public/Buyer):
1. get_store() - Get store by name or slug (public view)
2. get_stores() - Browse all published stores
3. get_store_products() - List products from a store
4. search_stores() - Search for stores by name or category
"""

import json
from typing import Optional, Dict, Any, List

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate, now_datetime


# =============================================================================
# CONSTANTS
# =============================================================================

# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Store statuses
STORE_STATUSES = ["Draft", "Active", "Inactive", "Suspended"]

# Theme presets
THEME_PRESETS = ["Default", "Modern", "Classic", "Minimal", "Bold", "Elegant", "Custom"]

# Layout styles
LAYOUT_STYLES = ["Grid", "List", "Masonry", "Carousel"]

# Fonts
AVAILABLE_FONTS = [
    "Inter", "Roboto", "Open Sans", "Montserrat", "Poppins",
    "Lato", "Nunito", "PT Sans", "Source Sans Pro", "Raleway"
]

# Public fields for store display (non-sensitive data)
PUBLIC_STORE_FIELDS = [
    "name", "store_name", "store_code", "seller", "seller_name",
    "store_logo", "store_banner", "favicon", "store_tagline",
    "about_store", "about_company",
    "theme_preset", "layout_style", "primary_color", "secondary_color",
    "accent_color", "heading_font", "body_font", "font_size_base",
    "products_per_page", "products_per_row", "show_filters",
    "show_sorting", "show_quick_view", "enable_reviews",
    "enable_wishlist", "enable_compare", "show_seller_badges",
    "show_stock_status", "show_delivery_estimate",
    "contact_email", "contact_phone", "whatsapp_number", "support_hours",
    "facebook_url", "instagram_url", "twitter_url", "linkedin_url",
    "youtube_url", "tiktok_url",
    "seo_title", "seo_description", "seo_keywords", "url_slug", "og_image",
    "return_policy", "shipping_policy", "privacy_policy", "terms_conditions",
    "default_currency", "default_language", "timezone", "date_format",
    "page_views"
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_current_tenant() -> Optional[str]:
    """Get current user's tenant."""
    try:
        from tr_tradehub.utils.tenant import get_current_tenant as _get_tenant
        return _get_tenant()
    except ImportError:
        return frappe.db.get_value("User", frappe.session.user, "tenant")


def validate_page_params(limit: int, offset: int) -> tuple:
    """Validate and sanitize pagination parameters."""
    limit = min(max(cint(limit), 1), MAX_PAGE_SIZE) if limit else DEFAULT_PAGE_SIZE
    offset = max(cint(offset), 0)
    return limit, offset


def get_user_seller_profile() -> Optional[str]:
    """Get the Seller Profile for the current user."""
    return frappe.db.get_value(
        "Seller Profile",
        {"user": frappe.session.user, "status": ["in", ["Active", "Verified"]]},
        "name"
    )


def validate_seller_access(seller: str = None):
    """
    Validate that current user has access to seller operations.

    Args:
        seller: Optional seller profile to check access against

    Returns:
        str: The seller profile name for the current user
    """
    if "System Manager" in frappe.get_roles():
        if seller:
            return seller
        return get_user_seller_profile()

    user_seller = get_user_seller_profile()
    if not user_seller:
        frappe.throw(_("You do not have a valid Seller Profile"))

    if seller and user_seller != seller:
        frappe.throw(_("Access denied: You can only access your own seller profile"))

    return user_seller


def validate_store_access(store_name: str = None):
    """
    Validate that current user has access to a specific store.

    Args:
        store_name: The store name to check access for

    Returns:
        tuple: (store_name, seller_profile) if access is valid
    """
    if "System Manager" in frappe.get_roles():
        if store_name:
            seller = frappe.db.get_value("Seller Store", store_name, "seller")
            return store_name, seller
        return None, get_user_seller_profile()

    user_seller = get_user_seller_profile()
    if not user_seller:
        frappe.throw(_("You do not have a valid Seller Profile"))

    if store_name:
        store_seller = frappe.db.get_value("Seller Store", store_name, "seller")
        if store_seller != user_seller:
            frappe.throw(_("Access denied: You can only manage your own store"))

    return store_name, user_seller


def parse_json_param(param: Any, param_name: str) -> Any:
    """Parse a JSON parameter if it's a string."""
    if param is None:
        return None
    if isinstance(param, str):
        try:
            return json.loads(param)
        except json.JSONDecodeError:
            frappe.throw(_("{0} must be valid JSON").format(param_name))
    return param


# =============================================================================
# PUBLIC STORE BROWSING APIs
# =============================================================================

@frappe.whitelist(allow_guest=True)
def get_store(
    store_name: str = None,
    slug: str = None
) -> Dict[str, Any]:
    """
    Get store details for public display.

    Retrieves a single store by name or URL slug. This is the primary endpoint
    for displaying storefront pages to buyers and visitors.

    Args:
        store_name: The store document name
        slug: The URL slug of the store

    Returns:
        dict: {
            "success": True,
            "store": {...},
            "seller_info": {...}
        }
    """
    if not store_name and not slug:
        frappe.throw(_("Either store_name or slug is required"))

    filters = {"is_published": 1, "status": "Active"}

    if store_name:
        filters["name"] = store_name
    elif slug:
        filters["url_slug"] = slug

    store = frappe.db.get_value(
        "Seller Store",
        filters,
        PUBLIC_STORE_FIELDS,
        as_dict=True
    )

    if not store:
        frappe.throw(_("Store not found or not available"), frappe.DoesNotExistError)

    # Get additional seller information
    seller_info = frappe.db.get_value(
        "Seller Profile",
        store.seller,
        ["name", "seller_name", "company_name", "verification_status",
         "tier", "tier_name", "average_rating", "total_reviews",
         "response_rate", "on_time_delivery_rate", "member_since"],
        as_dict=True
    )

    # Increment page views asynchronously
    frappe.enqueue(
        'tr_tradehub.trade_hub.doctype.seller_store.seller_store.increment_store_views',
        store_name=store.name,
        queue='short'
    )

    return {
        "success": True,
        "store": store,
        "seller_info": seller_info
    }


@frappe.whitelist(allow_guest=True)
def get_stores(
    tenant: str = None,
    search: str = None,
    category: str = None,
    sort_by: str = "page_views",
    sort_order: str = "desc",
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get a paginated list of published stores.

    This endpoint is used for browsing all available stores in the marketplace.
    Supports filtering, searching, and sorting.

    Args:
        tenant: Filter by tenant (for multi-tenant deployments)
        search: Search in store name and tagline
        category: Filter by product category (stores selling products in this category)
        sort_by: Sort field (page_views, store_name, created_date)
        sort_order: Sort direction (asc, desc)
        limit: Number of records per page (default 20, max 100)
        offset: Starting position for pagination

    Returns:
        dict: {
            "success": True,
            "stores": [...],
            "count": int,
            "total": int,
            "limit": int,
            "offset": int,
            "has_more": bool
        }
    """
    limit, offset = validate_page_params(limit, offset)

    filters = {"is_published": 1, "status": "Active"}
    or_filters = None

    if tenant:
        filters["tenant"] = tenant

    # Search filter
    if search:
        or_filters = [
            ["store_name", "like", f"%{search}%"],
            ["store_tagline", "like", f"%{search}%"],
            ["seller_name", "like", f"%{search}%"]
        ]

    # Validate sort field
    valid_sort_fields = ["page_views", "store_name", "created_date", "last_published"]
    if sort_by not in valid_sort_fields:
        sort_by = "page_views"

    sort_order = "desc" if sort_order.lower() == "desc" else "asc"

    # Get total count
    total = frappe.db.count("Seller Store", filters=filters)

    # Get stores
    stores = frappe.get_all(
        "Seller Store",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "store_name", "store_code", "seller", "seller_name",
            "store_logo", "store_banner", "store_tagline", "url_slug",
            "primary_color", "theme_preset", "page_views",
            "default_currency", "tenant"
        ],
        order_by=f"{sort_by} {sort_order}",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(stores) > limit
    if has_more:
        stores = stores[:limit]

    # Add seller badges/rating for each store
    for store in stores:
        seller_data = frappe.db.get_value(
            "Seller Profile",
            store.seller,
            ["verification_status", "tier_name", "average_rating"],
            as_dict=True
        )
        if seller_data:
            store["verification_status"] = seller_data.verification_status
            store["tier_name"] = seller_data.tier_name
            store["average_rating"] = seller_data.average_rating

    return {
        "success": True,
        "stores": stores,
        "count": len(stores),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more
    }


@frappe.whitelist(allow_guest=True)
def search_stores(
    query: str,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Quick search for stores by name.

    Lightweight search endpoint optimized for autocomplete and quick lookup.

    Args:
        query: Search query (minimum 2 characters)
        limit: Maximum results (default 10, max 50)

    Returns:
        dict: {
            "success": True,
            "stores": [{"name", "store_name", "store_logo", "url_slug"}]
        }
    """
    if not query or len(query) < 2:
        return {"success": True, "stores": []}

    limit = min(max(cint(limit), 1), 50)

    stores = frappe.get_all(
        "Seller Store",
        filters={
            "is_published": 1,
            "status": "Active",
            "store_name": ["like", f"%{query}%"]
        },
        fields=["name", "store_name", "store_logo", "url_slug", "seller_name"],
        limit_page_length=limit,
        order_by="page_views desc"
    )

    return {
        "success": True,
        "stores": stores
    }


@frappe.whitelist(allow_guest=True)
def get_store_products(
    store_name: str = None,
    slug: str = None,
    category: str = None,
    search: str = None,
    sort_by: str = "creation",
    sort_order: str = "desc",
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get products from a specific store.

    Lists all active products belonging to a store with pagination,
    filtering, and sorting options.

    Args:
        store_name: The store document name
        slug: The store URL slug
        category: Filter by product category
        search: Search in product name and description
        sort_by: Sort field (creation, name, price, popularity)
        sort_order: Sort direction (asc, desc)
        limit: Number of records per page
        offset: Starting position

    Returns:
        dict: {
            "success": True,
            "products": [...],
            "count": int,
            "total": int,
            "has_more": bool,
            "store": {...}
        }
    """
    if not store_name and not slug:
        frappe.throw(_("Either store_name or slug is required"))

    limit, offset = validate_page_params(limit, offset)

    # Get store and seller
    store_filters = {"is_published": 1, "status": "Active"}
    if store_name:
        store_filters["name"] = store_name
    elif slug:
        store_filters["url_slug"] = slug

    store = frappe.db.get_value(
        "Seller Store",
        store_filters,
        ["name", "store_name", "seller", "seller_name", "products_per_page"],
        as_dict=True
    )

    if not store:
        frappe.throw(_("Store not found or not available"))

    # Use store's products_per_page if limit not specified
    if limit == DEFAULT_PAGE_SIZE and store.products_per_page:
        limit = cint(store.products_per_page)

    # Build product filters
    product_filters = {
        "seller": store.seller,
        "status": "Active"
    }

    if category:
        product_filters["category"] = category

    or_filters = None
    if search:
        or_filters = [
            ["product_name", "like", f"%{search}%"],
            ["description", "like", f"%{search}%"],
            ["sku_code", "like", f"%{search}%"]
        ]

    # Validate sort field
    valid_sort_fields = ["creation", "product_name", "base_price", "modified"]
    if sort_by not in valid_sort_fields:
        sort_by = "creation"

    sort_order = "desc" if sort_order.lower() == "desc" else "asc"

    # Get total count
    total = frappe.db.count("SKU Product", filters=product_filters)

    # Get products
    products = frappe.get_all(
        "SKU Product",
        filters=product_filters,
        or_filters=or_filters,
        fields=[
            "name", "product_name", "sku_code", "url_slug",
            "category", "category_name", "brand", "brand_name",
            "base_price", "currency", "stock_uom",
            "stock_quantity", "is_stock_item",
            "primary_image", "short_description",
            "has_variants", "total_variants"
        ],
        order_by=f"{sort_by} {sort_order}",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(products) > limit
    if has_more:
        products = products[:limit]

    return {
        "success": True,
        "products": products,
        "count": len(products),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "store": {
            "name": store.name,
            "store_name": store.store_name,
            "seller_name": store.seller_name
        }
    }


# =============================================================================
# SELLER STORE MANAGEMENT APIs
# =============================================================================

@frappe.whitelist()
def get_my_store() -> Dict[str, Any]:
    """
    Get the current seller's store.

    Returns the store belonging to the currently logged-in seller,
    or indicates that no store exists yet.

    Returns:
        dict: {
            "success": True,
            "has_store": bool,
            "store": {...} | None
        }
    """
    seller = validate_seller_access()

    store_name = frappe.db.get_value("Seller Store", {"seller": seller}, "name")

    if not store_name:
        return {
            "success": True,
            "has_store": False,
            "store": None,
            "message": _("You don't have a store yet. Create one to start selling.")
        }

    store = frappe.get_doc("Seller Store", store_name)

    return {
        "success": True,
        "has_store": True,
        "store": store.as_dict()
    }


@frappe.whitelist()
def create_store(
    store_name: str,
    store_tagline: str = None,
    theme_preset: str = "Default",
    seller: str = None
) -> Dict[str, Any]:
    """
    Create a new store for the current seller.

    Each seller can have only one store. Creating a second store will fail.

    Args:
        store_name: Display name for the store (required)
        store_tagline: Short tagline (max 100 characters)
        theme_preset: Initial theme preset (Default, Modern, Classic, etc.)
        seller: Seller Profile (optional, defaults to current user's seller)

    Returns:
        dict: {
            "success": True,
            "name": "STORE-00001",
            "store_name": str,
            "url_slug": str
        }
    """
    if not seller:
        seller = validate_seller_access()
    else:
        validate_seller_access(seller)

    # Validate required fields
    if not store_name:
        frappe.throw(_("Store Name is required"))

    if len(store_name) > 140:
        frappe.throw(_("Store Name cannot exceed 140 characters"))

    if store_tagline and len(store_tagline) > 100:
        frappe.throw(_("Store Tagline cannot exceed 100 characters"))

    # Check if seller already has a store
    existing = frappe.db.exists("Seller Store", {"seller": seller})
    if existing:
        frappe.throw(_("You already have a store: {0}").format(existing))

    # Validate theme preset
    if theme_preset not in THEME_PRESETS:
        theme_preset = "Default"

    # Create store
    doc = frappe.new_doc("Seller Store")
    doc.seller = seller
    doc.store_name = store_name
    doc.store_tagline = store_tagline
    doc.theme_preset = theme_preset
    doc.status = "Draft"

    doc.insert()

    return {
        "success": True,
        "name": doc.name,
        "store_name": doc.store_name,
        "store_code": doc.store_code,
        "url_slug": doc.url_slug,
        "status": doc.status,
        "message": _("Store created successfully")
    }


@frappe.whitelist()
def update_store(
    store_name: str,
    settings: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update store settings.

    Updates various store settings including branding, display options,
    contact information, social links, SEO, and policies.

    Args:
        store_name: The store document name (required)
        settings: JSON object of settings to update
        **kwargs: Individual field updates (alternative to settings JSON)

    Returns:
        dict: {
            "success": True,
            "name": str,
            "updated_fields": [...]
        }
    """
    validate_store_access(store_name)

    # Parse settings if provided as JSON
    if settings:
        settings_dict = parse_json_param(settings, "settings")
    else:
        settings_dict = kwargs

    if not settings_dict:
        frappe.throw(_("No settings provided to update"))

    store = frappe.get_doc("Seller Store", store_name)

    # List of allowed fields to update via API
    allowed_fields = [
        "store_name", "store_tagline", "about_store", "about_company",
        "theme_preset", "layout_style", "primary_color", "secondary_color",
        "accent_color", "heading_font", "body_font", "font_size_base",
        "custom_css", "products_per_page", "products_per_row",
        "show_filters", "show_sorting", "show_quick_view",
        "enable_reviews", "enable_wishlist", "enable_compare",
        "show_seller_badges", "show_stock_status", "show_delivery_estimate",
        "show_contact_form", "contact_email", "contact_phone",
        "whatsapp_number", "support_hours",
        "facebook_url", "instagram_url", "twitter_url",
        "linkedin_url", "youtube_url", "tiktok_url",
        "seo_title", "seo_description", "seo_keywords",
        "google_analytics_id", "facebook_pixel_id", "custom_tracking_code",
        "return_policy", "shipping_policy", "privacy_policy", "terms_conditions",
        "default_currency", "default_language", "timezone", "date_format"
    ]

    updated_fields = []
    for field, value in settings_dict.items():
        if field in allowed_fields:
            setattr(store, field, value)
            updated_fields.append(field)

    if not updated_fields:
        frappe.throw(_("No valid fields provided to update"))

    store.save()

    return {
        "success": True,
        "name": store.name,
        "store_name": store.store_name,
        "updated_fields": updated_fields,
        "message": _("Store updated successfully")
    }


@frappe.whitelist()
def update_store_status(
    store_name: str,
    status: str
) -> Dict[str, Any]:
    """
    Update store status.

    Args:
        store_name: The store document name
        status: New status (Draft, Active, Inactive)

    Returns:
        dict: {
            "success": True,
            "status": str
        }
    """
    validate_store_access(store_name)

    if status not in ["Draft", "Active", "Inactive"]:
        frappe.throw(_("Invalid status. Must be one of: Draft, Active, Inactive"))

    # Suspended status can only be set by System Manager
    if status == "Suspended" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only administrators can suspend stores"))

    store = frappe.get_doc("Seller Store", store_name)

    # Check current status
    if store.status == "Suspended":
        frappe.throw(_("Cannot change status of a suspended store. Contact support."))

    store.status = status

    # Unpublish if deactivating
    if status in ["Draft", "Inactive"]:
        store.is_published = 0

    store.save()

    return {
        "success": True,
        "status": store.status,
        "is_published": store.is_published,
        "message": _("Store status updated to {0}").format(status)
    }


@frappe.whitelist()
def publish_store(store_name: str) -> Dict[str, Any]:
    """
    Publish a store to make it visible to buyers.

    Requires that:
    - Store status is Active
    - Seller is verified

    Args:
        store_name: The store document name

    Returns:
        dict: {
            "success": True,
            "is_published": True,
            "published_at": datetime
        }
    """
    validate_store_access(store_name)

    store = frappe.get_doc("Seller Store", store_name)
    result = store.publish()

    return {
        "success": True,
        "is_published": True,
        "published_at": result.get("published_at"),
        "url_slug": store.url_slug,
        "message": _("Store published successfully")
    }


@frappe.whitelist()
def unpublish_store(store_name: str) -> Dict[str, Any]:
    """
    Unpublish a store to hide it from buyers.

    Args:
        store_name: The store document name

    Returns:
        dict: {
            "success": True,
            "is_published": False
        }
    """
    validate_store_access(store_name)

    store = frappe.get_doc("Seller Store", store_name)
    store.unpublish()

    return {
        "success": True,
        "is_published": False,
        "message": _("Store unpublished")
    }


# =============================================================================
# THEME CUSTOMIZATION APIs
# =============================================================================

@frappe.whitelist()
def get_theme_config(store_name: str) -> Dict[str, Any]:
    """
    Get theme configuration for a store.

    Args:
        store_name: The store document name

    Returns:
        dict: {
            "success": True,
            "theme": {...}
        }
    """
    store = frappe.get_doc("Seller Store", store_name)

    return {
        "success": True,
        "theme": store.get_theme_config()
    }


@frappe.whitelist()
def apply_theme_preset(
    store_name: str,
    preset: str
) -> Dict[str, Any]:
    """
    Apply a predefined theme preset to a store.

    Args:
        store_name: The store document name
        preset: Theme preset name (Default, Modern, Classic, Minimal, Bold, Elegant)

    Returns:
        dict: {
            "success": True,
            "theme_preset": str,
            "colors": {...}
        }
    """
    validate_store_access(store_name)

    if preset not in THEME_PRESETS:
        frappe.throw(_("Invalid theme preset. Must be one of: {0}").format(
            ", ".join(THEME_PRESETS)
        ))

    store = frappe.get_doc("Seller Store", store_name)
    store.apply_theme_preset(preset)
    store.save()

    return {
        "success": True,
        "theme_preset": store.theme_preset,
        "colors": {
            "primary": store.primary_color,
            "secondary": store.secondary_color,
            "accent": store.accent_color
        },
        "fonts": {
            "heading": store.heading_font,
            "body": store.body_font
        },
        "message": _("Theme preset applied successfully")
    }


@frappe.whitelist()
def update_store_branding(
    store_name: str,
    store_logo: str = None,
    store_banner: str = None,
    favicon: str = None,
    og_image: str = None
) -> Dict[str, Any]:
    """
    Update store branding images.

    Args:
        store_name: The store document name
        store_logo: URL of the store logo image
        store_banner: URL of the banner image
        favicon: URL of the favicon
        og_image: URL of the Open Graph image

    Returns:
        dict: {
            "success": True,
            "updated_fields": [...]
        }
    """
    validate_store_access(store_name)

    store = frappe.get_doc("Seller Store", store_name)

    updated_fields = []

    if store_logo is not None:
        store.store_logo = store_logo
        updated_fields.append("store_logo")

    if store_banner is not None:
        store.store_banner = store_banner
        updated_fields.append("store_banner")

    if favicon is not None:
        store.favicon = favicon
        updated_fields.append("favicon")

    if og_image is not None:
        store.og_image = og_image
        updated_fields.append("og_image")

    if updated_fields:
        store.save()

    return {
        "success": True,
        "updated_fields": updated_fields,
        "message": _("Branding updated successfully") if updated_fields else _("No changes made")
    }


# =============================================================================
# STORE STATISTICS APIs
# =============================================================================

@frappe.whitelist()
def get_store_statistics(store_name: str) -> Dict[str, Any]:
    """
    Get comprehensive statistics for a store.

    Includes page views, product counts, order metrics, and more.

    Args:
        store_name: The store document name

    Returns:
        dict: {
            "success": True,
            "statistics": {...}
        }
    """
    validate_store_access(store_name)

    store = frappe.get_doc("Seller Store", store_name)

    # Get product counts
    active_products = frappe.db.count(
        "SKU Product",
        {"seller": store.seller, "status": "Active"}
    )

    total_products = frappe.db.count(
        "SKU Product",
        {"seller": store.seller}
    )

    # Get order counts if Order DocType exists
    order_stats = {
        "total_orders": 0,
        "completed_orders": 0,
        "pending_orders": 0
    }

    if frappe.db.exists("DocType", "Order"):
        order_stats["total_orders"] = frappe.db.count(
            "Order",
            {"seller": store.seller}
        )
        order_stats["completed_orders"] = frappe.db.count(
            "Order",
            {"seller": store.seller, "status": ["in", ["Delivered", "Completed"]]}
        )
        order_stats["pending_orders"] = frappe.db.count(
            "Order",
            {"seller": store.seller, "status": ["in", ["Pending", "Processing", "Shipped"]]}
        )

    # Get seller performance metrics
    seller_metrics = frappe.db.get_value(
        "Seller Profile",
        store.seller,
        ["average_rating", "total_reviews", "response_rate",
         "on_time_delivery_rate", "buy_box_wins", "buy_box_win_rate"],
        as_dict=True
    ) or {}

    return {
        "success": True,
        "statistics": {
            "store": {
                "name": store.name,
                "store_name": store.store_name,
                "status": store.status,
                "is_published": store.is_published,
                "page_views": store.page_views,
                "last_published": store.last_published,
                "created_date": store.created_date
            },
            "products": {
                "active_products": active_products,
                "total_products": total_products
            },
            "orders": order_stats,
            "performance": {
                "average_rating": flt(seller_metrics.get("average_rating"), 2),
                "total_reviews": cint(seller_metrics.get("total_reviews")),
                "response_rate": flt(seller_metrics.get("response_rate"), 1),
                "on_time_delivery_rate": flt(seller_metrics.get("on_time_delivery_rate"), 1),
                "buy_box_wins": cint(seller_metrics.get("buy_box_wins")),
                "buy_box_win_rate": flt(seller_metrics.get("buy_box_win_rate"), 1)
            }
        }
    }


# =============================================================================
# CONFIGURATION APIs
# =============================================================================

@frappe.whitelist(allow_guest=True)
def get_store_config() -> Dict[str, Any]:
    """
    Get store configuration options.

    Returns available options for themes, fonts, layouts, etc.
    Useful for populating dropdown menus in the frontend.

    Returns:
        dict: Configuration options
    """
    return {
        "success": True,
        "config": {
            "store_statuses": STORE_STATUSES,
            "theme_presets": THEME_PRESETS,
            "layout_styles": LAYOUT_STYLES,
            "available_fonts": AVAILABLE_FONTS,
            "products_per_row_options": ["2", "3", "4", "5", "6"],
            "default_products_per_page": 12,
            "max_store_name_length": 140,
            "max_tagline_length": 100,
            "recommended_logo_size": "400x400",
            "recommended_banner_size": "1920x400",
            "recommended_og_image_size": "1200x630"
        }
    }
