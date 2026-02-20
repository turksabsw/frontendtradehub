# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Seller Store DocType for Trade Hub B2B Marketplace.

This module implements the Seller Store DocType for storefront configuration.
Each seller can have one store that defines their public storefront appearance,
branding, theme, and display settings.

Key Features:
- Multi-tenant isolation via fetch_from seller.tenant pattern
- Theme and color customization
- Typography and layout settings
- SEO configuration with URL slug generation
- Social media integration
- Analytics tracking support
- Store policies management
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, today, now_datetime


class SellerStore(Document):
    """
    Seller Store DocType for storefront configuration.

    Each seller can have one store that defines the appearance and settings
    for their public storefront on the Trade Hub marketplace.
    """

    def before_insert(self):
        """Set default values before inserting a new store."""
        self.set_system_info()
        self.generate_store_code()
        self.generate_url_slug()

    def validate(self):
        """Validate store data before saving."""
        self.validate_store_name()
        self.validate_seller()
        self.validate_colors()
        self.validate_seo_fields()
        self.validate_analytics_ids()
        self.generate_url_slug()

    def on_update(self):
        """Actions after store is updated."""
        self.update_modified_by()
        self.update_published_status()
        self.clear_store_cache()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_system_info(self):
        """Set system information for new stores."""
        if not self.created_date:
            self.created_date = today()
        self.modified_by_user = frappe.session.user

    def generate_store_code(self):
        """Generate unique store code if not provided."""
        if not self.store_code and self.store_name:
            # Create code from store name (first 3 letters + random suffix)
            base_code = re.sub(r'[^A-Z0-9]', '', self.store_name.upper()[:3])
            if len(base_code) < 3:
                base_code = base_code.ljust(3, 'S')

            # Add timestamp-based suffix for uniqueness
            import time
            suffix = str(int(time.time()))[-5:]
            self.store_code = f"STR{base_code}{suffix}"

            # Ensure uniqueness
            counter = 1
            original_code = self.store_code
            while frappe.db.exists("Seller Store", {"store_code": self.store_code, "name": ("!=", self.name or "")}):
                self.store_code = f"{original_code}{counter}"
                counter += 1

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_store_name(self):
        """Validate store name is not empty and follows naming conventions."""
        if not self.store_name:
            frappe.throw(_("Store Name is required"))

        # Check for invalid characters
        if any(char in self.store_name for char in ['<', '>', '"', '\\']):
            frappe.throw(_("Store Name contains invalid characters"))

        # Check length
        if len(self.store_name) > 140:
            frappe.throw(_("Store Name cannot exceed 140 characters"))

        # Trim whitespace
        self.store_name = self.store_name.strip()

        # Validate tagline length
        if self.store_tagline and len(self.store_tagline) > 100:
            frappe.throw(_("Store Tagline cannot exceed 100 characters"))

    def validate_seller(self):
        """Validate seller is set and active."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        # Check if seller exists and is verified
        seller = frappe.db.get_value(
            "Seller Profile",
            self.seller,
            ["verification_status", "status", "tenant"],
            as_dict=True
        )

        if not seller:
            frappe.throw(_("Seller Profile not found: {0}").format(self.seller))

        # Warn if seller is not verified (but allow creation)
        if seller.verification_status != "Verified":
            frappe.msgprint(
                _("Note: Seller is not yet verified. Store will not be visible until seller is verified."),
                indicator="orange"
            )

        # Validate user has access to this seller (unless System Manager)
        if not frappe.has_permission("Seller Profile", "write"):
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant and seller.tenant and user_tenant != seller.tenant:
                frappe.throw(_("You can only create stores for sellers in your own tenant"))

    def validate_colors(self):
        """Validate color values are in proper hex format."""
        color_fields = ['primary_color', 'secondary_color', 'accent_color']
        hex_pattern = re.compile(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')

        for field in color_fields:
            color = getattr(self, field, None)
            if color and not hex_pattern.match(color):
                frappe.throw(
                    _("{0} must be a valid hex color (e.g., #2563eb or #fff)").format(
                        field.replace('_', ' ').title()
                    )
                )

    def validate_seo_fields(self):
        """Validate SEO field lengths and content."""
        if self.seo_title and len(self.seo_title) > 60:
            frappe.msgprint(
                _("SEO Title exceeds recommended length of 60 characters"),
                indicator="orange"
            )

        if self.seo_description and len(self.seo_description) > 160:
            frappe.msgprint(
                _("SEO Description exceeds recommended length of 160 characters"),
                indicator="orange"
            )

    def validate_analytics_ids(self):
        """Validate analytics tracking IDs format."""
        # Validate Google Analytics ID format (G-XXXXXXX)
        if self.google_analytics_id:
            ga_pattern = re.compile(r'^G-[A-Z0-9]+$')
            if not ga_pattern.match(self.google_analytics_id):
                frappe.msgprint(
                    _("Google Analytics ID should be in format G-XXXXXXX"),
                    indicator="orange"
                )

        # Validate Facebook Pixel ID format (numeric)
        if self.facebook_pixel_id:
            if not self.facebook_pixel_id.isdigit():
                frappe.msgprint(
                    _("Facebook Pixel ID should be numeric"),
                    indicator="orange"
                )

    # =========================================================================
    # URL SLUG GENERATION
    # =========================================================================

    def generate_url_slug(self):
        """Generate SEO-friendly URL slug from store name."""
        if not self.url_slug and self.store_name:
            # Convert to lowercase and replace special characters
            slug = self.store_name.lower()

            # Turkish character replacements
            turkish_map = {
                'i': 'i', 'g': 'g', 'u': 'u', 's': 's', 'o': 'o', 'c': 'c',
                'I': 'i', 'G': 'g', 'U': 'u', 'S': 's', 'O': 'o', 'C': 'c'
            }
            for tr_char, en_char in turkish_map.items():
                slug = slug.replace(tr_char, en_char)

            # Replace spaces and special chars with hyphens
            slug = re.sub(r'[^a-z0-9\-]', '-', slug)
            # Remove consecutive hyphens
            slug = re.sub(r'-+', '-', slug)
            # Remove leading/trailing hyphens
            slug = slug.strip('-')

            # Add 'store' prefix to avoid collision with seller slugs
            if not slug.startswith('store-'):
                slug = f"store-{slug}"

            # Ensure uniqueness
            base_slug = slug
            counter = 1
            while frappe.db.exists("Seller Store", {"url_slug": slug, "name": ("!=", self.name or "")}):
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.url_slug = slug

    # =========================================================================
    # UPDATE METHODS
    # =========================================================================

    def update_modified_by(self):
        """Update the modified by user field."""
        self.db_set("modified_by_user", frappe.session.user, update_modified=False)

    def update_published_status(self):
        """Update published status and timestamp."""
        if self.is_published and self.status == "Active":
            if not self.last_published:
                self.db_set("last_published", now_datetime(), update_modified=False)
        elif self.has_value_changed("is_published") and not self.is_published:
            # Store was unpublished
            pass  # Keep last_published for record

    # =========================================================================
    # PUBLISHING METHODS
    # =========================================================================

    def publish(self):
        """Publish the store to make it visible."""
        if self.status != "Active":
            frappe.throw(_("Only active stores can be published"))

        # Check if seller is verified
        seller_verified = frappe.db.get_value(
            "Seller Profile",
            self.seller,
            "verification_status"
        )

        if seller_verified != "Verified":
            frappe.throw(_("Cannot publish store: Seller must be verified first"))

        self.is_published = 1
        self.last_published = now_datetime()
        self.save()

        return {"published": True, "published_at": self.last_published}

    def unpublish(self):
        """Unpublish the store to hide it from buyers."""
        self.is_published = 0
        self.save()

        return {"published": False}

    # =========================================================================
    # THEME METHODS
    # =========================================================================

    def get_theme_config(self):
        """
        Get complete theme configuration for frontend rendering.

        Returns:
            dict: Theme configuration including colors, fonts, and layout
        """
        return {
            "theme_preset": self.theme_preset,
            "layout_style": self.layout_style,
            "colors": {
                "primary": self.primary_color,
                "secondary": self.secondary_color,
                "accent": self.accent_color
            },
            "typography": {
                "heading_font": self.heading_font,
                "body_font": self.body_font,
                "font_size_base": self.font_size_base
            },
            "custom_css": self.custom_css
        }

    def apply_theme_preset(self, preset):
        """
        Apply a predefined theme preset.

        Args:
            preset: Name of the theme preset
        """
        presets = {
            "Default": {
                "primary_color": "#2563eb",
                "secondary_color": "#64748b",
                "accent_color": "#f59e0b",
                "heading_font": "Inter",
                "body_font": "Inter"
            },
            "Modern": {
                "primary_color": "#0f172a",
                "secondary_color": "#475569",
                "accent_color": "#22c55e",
                "heading_font": "Poppins",
                "body_font": "Inter"
            },
            "Classic": {
                "primary_color": "#1e3a5f",
                "secondary_color": "#6b7280",
                "accent_color": "#b8860b",
                "heading_font": "Montserrat",
                "body_font": "Open Sans"
            },
            "Minimal": {
                "primary_color": "#18181b",
                "secondary_color": "#a1a1aa",
                "accent_color": "#ef4444",
                "heading_font": "Inter",
                "body_font": "Inter"
            },
            "Bold": {
                "primary_color": "#7c3aed",
                "secondary_color": "#64748b",
                "accent_color": "#f97316",
                "heading_font": "Montserrat",
                "body_font": "Nunito"
            },
            "Elegant": {
                "primary_color": "#292524",
                "secondary_color": "#78716c",
                "accent_color": "#d4af37",
                "heading_font": "Raleway",
                "body_font": "Lato"
            }
        }

        if preset in presets:
            for field, value in presets[preset].items():
                setattr(self, field, value)
            self.theme_preset = preset

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_store_cache(self):
        """Clear cached store data."""
        cache_keys = [
            "store_list",
            f"store:{self.name}",
            f"store_slug:{self.url_slug}",
        ]
        if self.tenant:
            cache_keys.append(f"store_list:{self.tenant}")
        if self.seller:
            cache_keys.append(f"seller_store:{self.seller}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # ANALYTICS METHODS
    # =========================================================================

    def increment_page_views(self):
        """Increment the page views counter."""
        frappe.db.sql(
            """UPDATE `tabSeller Store` SET page_views = page_views + 1 WHERE name = %s""",
            (self.name,)
        )


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_store_by_slug(slug):
    """
    Get store by URL slug for public display.

    Args:
        slug: The URL slug of the store

    Returns:
        dict: Store data for frontend rendering
    """
    store = frappe.db.get_value(
        "Seller Store",
        {"url_slug": slug, "is_published": 1, "status": "Active"},
        [
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
            "seo_title", "seo_description", "seo_keywords", "og_image",
            "google_analytics_id", "return_policy", "shipping_policy",
            "privacy_policy", "terms_conditions",
            "default_currency", "default_language", "timezone", "date_format"
        ],
        as_dict=True
    )

    if not store:
        frappe.throw(_("Store not found"))

    # Increment page views asynchronously
    frappe.enqueue(
        'tr_tradehub.trade_hub.doctype.seller_store.seller_store.increment_store_views',
        store_name=store.name,
        queue='short'
    )

    return store


@frappe.whitelist()
def get_store_by_seller(seller):
    """
    Get store for a specific seller.

    Args:
        seller: Seller Profile name

    Returns:
        dict: Store data or None if no store exists
    """
    store_name = frappe.db.get_value("Seller Store", {"seller": seller}, "name")

    if not store_name:
        return None

    return frappe.get_doc("Seller Store", store_name).as_dict()


@frappe.whitelist()
def publish_store(store_name):
    """
    Publish a store.

    Args:
        store_name: Name of the store to publish

    Returns:
        dict: Publication result
    """
    store = frappe.get_doc("Seller Store", store_name)
    return store.publish()


@frappe.whitelist()
def unpublish_store(store_name):
    """
    Unpublish a store.

    Args:
        store_name: Name of the store to unpublish

    Returns:
        dict: Unpublication result
    """
    store = frappe.get_doc("Seller Store", store_name)
    return store.unpublish()


@frappe.whitelist()
def get_theme_config(store_name):
    """
    Get theme configuration for a store.

    Args:
        store_name: Name of the store

    Returns:
        dict: Theme configuration
    """
    store = frappe.get_doc("Seller Store", store_name)
    return store.get_theme_config()


@frappe.whitelist()
def apply_theme_preset(store_name, preset):
    """
    Apply a theme preset to a store.

    Args:
        store_name: Name of the store
        preset: Name of the theme preset

    Returns:
        dict: Updated store data
    """
    store = frappe.get_doc("Seller Store", store_name)
    store.apply_theme_preset(preset)
    store.save()

    return {
        "name": store.name,
        "theme_preset": store.theme_preset,
        "primary_color": store.primary_color,
        "secondary_color": store.secondary_color,
        "accent_color": store.accent_color,
        "heading_font": store.heading_font,
        "body_font": store.body_font
    }


@frappe.whitelist()
def get_store_list(tenant=None, published_only=True, limit=20, offset=0):
    """
    Get list of stores.

    Args:
        tenant: Optional tenant filter
        published_only: Only include published stores
        limit: Number of stores to return
        offset: Pagination offset

    Returns:
        dict: List of stores and total count
    """
    filters = {}

    if published_only:
        filters["is_published"] = 1
        filters["status"] = "Active"

    if tenant:
        filters["tenant"] = tenant

    total = frappe.db.count("Seller Store", filters=filters)
    stores = frappe.get_all(
        "Seller Store",
        filters=filters,
        fields=[
            "name", "store_name", "seller", "seller_name",
            "store_logo", "store_tagline", "url_slug",
            "primary_color", "theme_preset", "page_views"
        ],
        limit_page_length=cint(limit),
        limit_start=cint(offset),
        order_by="page_views desc"
    )

    return {
        "stores": stores,
        "total": total,
        "limit": cint(limit),
        "offset": cint(offset)
    }


@frappe.whitelist()
def create_store_for_seller(seller, store_name=None):
    """
    Create a new store for a seller.

    Args:
        seller: Seller Profile name
        store_name: Optional store name (defaults to seller name)

    Returns:
        dict: Created store data
    """
    # Check if seller already has a store
    existing = frappe.db.exists("Seller Store", {"seller": seller})
    if existing:
        frappe.throw(_("Seller already has a store: {0}").format(existing))

    # Get seller info
    seller_doc = frappe.get_doc("Seller Profile", seller)

    if not store_name:
        store_name = f"{seller_doc.seller_name} Store"

    store = frappe.get_doc({
        "doctype": "Seller Store",
        "seller": seller,
        "store_name": store_name,
        "status": "Draft"
    })
    store.insert()

    return {
        "name": store.name,
        "store_name": store.store_name,
        "seller": store.seller,
        "url_slug": store.url_slug
    }


@frappe.whitelist()
def get_store_statistics(store_name):
    """
    Get statistics for a store.

    Args:
        store_name: Name of the store

    Returns:
        dict: Store statistics
    """
    store = frappe.get_doc("Seller Store", store_name)

    # Get product count for this seller
    product_count = frappe.db.count(
        "SKU Product",
        {"seller": store.seller, "status": "Active"}
    )

    # Get order count if Order DocType exists
    order_count = 0
    if frappe.db.exists("DocType", "Order"):
        order_count = frappe.db.count(
            "Order",
            {"seller": store.seller}
        )

    return {
        "name": store.name,
        "store_name": store.store_name,
        "page_views": store.page_views,
        "is_published": store.is_published,
        "last_published": store.last_published,
        "active_products": product_count,
        "total_orders": order_count
    }


@frappe.whitelist()
def update_store_settings(store_name, settings):
    """
    Update store settings.

    Args:
        store_name: Name of the store
        settings: Dictionary of settings to update

    Returns:
        dict: Updated store data
    """
    import json
    if isinstance(settings, str):
        settings = json.loads(settings)

    store = frappe.get_doc("Seller Store", store_name)

    # List of allowed fields to update
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

    for field, value in settings.items():
        if field in allowed_fields:
            setattr(store, field, value)

    store.save()

    return {
        "name": store.name,
        "store_name": store.store_name,
        "updated_fields": list(settings.keys())
    }


def increment_store_views(store_name):
    """
    Increment store page views (called from queue).

    Args:
        store_name: Name of the store
    """
    frappe.db.sql(
        """UPDATE `tabSeller Store` SET page_views = page_views + 1 WHERE name = %s""",
        (store_name,)
    )
