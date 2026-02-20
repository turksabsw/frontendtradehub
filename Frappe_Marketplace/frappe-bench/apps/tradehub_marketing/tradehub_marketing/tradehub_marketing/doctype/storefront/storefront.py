# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, getdate
from frappe.website.utils import cleanup_page_name
import re
import json


class Storefront(Document):
    """
    Storefront DocType for seller store pages.

    Each seller can have one storefront that serves as their public-facing
    shop page on the TR-TradeHub marketplace. Features include:
    - Custom branding (logo, banner, colors)
    - Theme customization
    - SEO optimization
    - Social media links
    - Store policies
    - Statistics tracking
    """
    website = frappe._dict()

    def before_insert(self):
        """Set default values before inserting a new storefront."""
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant from seller's tenant if not specified
        if not self.tenant and self.seller:
            self.tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")

        # Generate slug if not provided
        if not self.slug:
            self.slug = self.generate_slug()

        # Generate route from slug
        if not self.route:
            self.route = f"store/{self.slug}"

        # Set default store name from seller name
        if not self.store_name and self.seller:
            seller_name = frappe.db.get_value("Seller Profile", self.seller, "seller_name")
            self.store_name = seller_name or "My Store"

        # Set default SEO meta title
        if not self.meta_title:
            self.meta_title = self.store_name

    def validate(self):
        """Validate storefront data before saving."""
        self.validate_seller()
        self.validate_slug()
        self.validate_colors()
        self.validate_seo_fields()
        self.validate_social_urls()
        self.validate_featured_dates()
        self.validate_products_per_page()
        self.modified_by = frappe.session.user
        self.last_updated_at = now_datetime()

    def on_update(self):
        """Actions to perform after storefront is updated."""
        self.update_route()
        self.clear_storefront_cache()

    def after_insert(self):
        """Actions to perform after storefront is inserted."""
        # Link storefront back to seller profile if not already linked
        pass

    def on_trash(self):
        """Prevent deletion of storefront with active listings."""
        self.check_linked_documents()

    def validate_seller(self):
        """Validate seller link and ensure uniqueness."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

        # Check if seller already has a storefront (for new records)
        if self.is_new():
            existing = frappe.db.exists("Storefront", {"seller": self.seller})
            if existing:
                frappe.throw(_("Seller {0} already has a Storefront").format(self.seller))

    def validate_slug(self):
        """Validate and sanitize URL slug."""
        if not self.slug:
            self.slug = self.generate_slug()
            return

        # Sanitize slug
        slug = self.slug.strip().lower()
        slug = re.sub(r'[^a-z0-9\-]', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        slug = slug.strip('-')

        if not slug:
            frappe.throw(_("Slug cannot be empty"))

        if len(slug) < 3:
            frappe.throw(_("Slug must be at least 3 characters long"))

        if len(slug) > 100:
            frappe.throw(_("Slug cannot exceed 100 characters"))

        # Reserved slugs
        reserved = ['admin', 'api', 'app', 'store', 'stores', 'marketplace',
                   'seller', 'sellers', 'product', 'products', 'category',
                   'categories', 'cart', 'checkout', 'order', 'orders',
                   'account', 'login', 'logout', 'register', 'search']
        if slug in reserved:
            frappe.throw(_("Slug '{0}' is reserved and cannot be used").format(slug))

        # Check uniqueness (excluding current document)
        filters = {"slug": slug}
        if not self.is_new():
            filters["name"] = ["!=", self.name]

        if frappe.db.exists("Storefront", filters):
            frappe.throw(_("Slug '{0}' is already in use by another storefront").format(slug))

        self.slug = slug

    def generate_slug(self):
        """Generate URL slug from store name."""
        base_name = self.store_name or "store"
        slug = cleanup_page_name(base_name.lower())

        # Ensure uniqueness
        counter = 1
        original_slug = slug
        while frappe.db.exists("Storefront", {"slug": slug, "name": ["!=", self.name or ""]}):
            slug = f"{original_slug}-{counter}"
            counter += 1

        return slug

    def validate_colors(self):
        """Validate color hex codes."""
        color_fields = ['primary_color', 'secondary_color', 'accent_color',
                       'background_color', 'text_color']

        for field in color_fields:
            value = getattr(self, field, None)
            if value and not self.is_valid_hex_color(value):
                frappe.throw(_("Invalid color format for {0}. Use hex color code (e.g., #FF5733)").format(field))

    def is_valid_hex_color(self, color):
        """Check if string is a valid hex color code."""
        if not color:
            return True
        return bool(re.match(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$', color))

    def validate_seo_fields(self):
        """Validate SEO fields for optimal length."""
        if self.meta_title and len(self.meta_title) > 60:
            frappe.msgprint(
                _("Meta title is longer than 60 characters. Consider shortening for better SEO."),
                indicator="orange"
            )

        if self.meta_description and len(self.meta_description) > 160:
            frappe.msgprint(
                _("Meta description is longer than 160 characters. Consider shortening for better SEO."),
                indicator="orange"
            )

        # Update route from slug
        if self.slug and not self.route:
            self.route = f"store/{self.slug}"

    def validate_social_urls(self):
        """Validate social media URL formats."""
        social_fields = {
            'facebook_url': 'facebook.com',
            'instagram_url': 'instagram.com',
            'twitter_url': ['twitter.com', 'x.com'],
            'linkedin_url': 'linkedin.com',
            'youtube_url': 'youtube.com',
            'tiktok_url': 'tiktok.com'
        }

        for field, domains in social_fields.items():
            url = getattr(self, field, None)
            if url:
                url = url.strip()
                if not url.startswith(('http://', 'https://')):
                    url = f"https://{url}"
                    setattr(self, field, url)

                # Basic URL validation
                if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', url):
                    frappe.throw(_("Invalid URL format for {0}").format(field))

    def validate_featured_dates(self):
        """Validate featured date range."""
        if self.is_featured:
            if self.featured_from and self.featured_until:
                if getdate(self.featured_from) > getdate(self.featured_until):
                    frappe.throw(_("Featured 'From' date cannot be after 'Until' date"))

    def validate_products_per_page(self):
        """Validate products per page setting."""
        if self.products_per_page:
            if self.products_per_page < 4:
                self.products_per_page = 4
            elif self.products_per_page > 100:
                self.products_per_page = 100

        if self.featured_products_count:
            if self.featured_products_count < 1:
                self.featured_products_count = 1
            elif self.featured_products_count > 24:
                self.featured_products_count = 24

    def update_route(self):
        """Update route when slug changes."""
        if self.slug:
            new_route = f"store/{self.slug}"
            if self.route != new_route:
                self.db_set("route", new_route)

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for active listings linked to this storefront
        listing_count = frappe.db.count("Listing", {
            "storefront": self.name,
            "status": ["!=", "Archived"]
        })

        if listing_count > 0:
            frappe.throw(
                _("Cannot delete Storefront with {0} active listings. "
                  "Please archive all listings first.").format(listing_count)
            )

    def clear_storefront_cache(self):
        """Clear cached storefront data."""
        cache_keys = [
            f"storefront:{self.name}",
            f"storefront_by_seller:{self.seller}",
            f"storefront_by_slug:{self.slug}"
        ]

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # Publishing Methods
    def publish(self):
        """Publish the storefront to make it publicly visible."""
        # Validate seller is active and verified
        seller_status = frappe.db.get_value("Seller Profile", self.seller,
                                            ["status", "verification_status"], as_dict=True)

        if seller_status.status != "Active":
            frappe.throw(_("Cannot publish storefront. Seller must be active."))

        if seller_status.verification_status != "Verified":
            frappe.throw(_("Cannot publish storefront. Seller must be verified."))

        self.status = "Active"
        self.is_published = 1
        self.published_at = now_datetime()
        self.save()

        frappe.msgprint(_("Storefront published successfully"))

    def unpublish(self):
        """Unpublish the storefront to hide it from public."""
        self.is_published = 0
        self.status = "Draft"
        self.save()

        frappe.msgprint(_("Storefront unpublished"))

    def submit_for_review(self):
        """Submit storefront for admin review."""
        if self.status != "Draft":
            frappe.throw(_("Only draft storefronts can be submitted for review"))

        self.status = "Pending Review"
        self.save()

        frappe.msgprint(_("Storefront submitted for review"))

    def approve(self):
        """Approve a pending storefront."""
        if self.status != "Pending Review":
            frappe.throw(_("Only pending storefronts can be approved"))

        self.status = "Active"
        self.is_published = 1
        self.published_at = now_datetime()
        self.save()

        frappe.msgprint(_("Storefront approved and published"))

    def reject(self, reason=None):
        """Reject a pending storefront."""
        if self.status != "Pending Review":
            frappe.throw(_("Only pending storefronts can be rejected"))

        self.status = "Draft"
        if reason:
            frappe.msgprint(_("Storefront rejected: {0}").format(reason))
        else:
            frappe.msgprint(_("Storefront rejected"))
        self.save()

    def suspend(self, reason=None):
        """Suspend an active storefront."""
        self.status = "Suspended"
        self.is_published = 0
        self.save()

        if reason:
            frappe.msgprint(_("Storefront suspended: {0}").format(reason))

    def archive(self):
        """Archive the storefront."""
        self.status = "Archived"
        self.is_published = 0
        self.save()

        frappe.msgprint(_("Storefront archived"))

    # Statistics Methods
    def update_stats(self):
        """Update storefront statistics from related data."""
        # Count products
        total_products = frappe.db.count("Listing", {
            "seller": self.seller,
            "status": ["in", ["Active", "Published"]]
        })

        # Get seller review stats
        seller_stats = frappe.db.sql("""
            SELECT
                COALESCE(AVG(rating), 0) as avg_rating,
                COUNT(*) as review_count
            FROM `tabReview`
            WHERE seller = %s AND status = 'Approved'
        """, self.seller, as_dict=True)

        # Get sales count
        total_sales = frappe.db.count("Sub Order", {
            "seller": self.seller,
            "status": "Completed"
        })

        self.total_products = total_products
        self.average_rating = round(seller_stats[0].avg_rating or 0, 2) if seller_stats else 0
        self.total_reviews = seller_stats[0].review_count or 0 if seller_stats else 0
        self.total_sales = total_sales
        self.save()

        return {
            "total_products": self.total_products,
            "average_rating": self.average_rating,
            "total_reviews": self.total_reviews,
            "total_sales": self.total_sales,
            "total_views": self.total_views,
            "total_followers": self.total_followers
        }

    def increment_views(self):
        """Increment view counter for the storefront."""
        frappe.db.set_value("Storefront", self.name, "total_views",
                          cint(self.total_views) + 1, update_modified=False)

    def add_follower(self):
        """Increment follower count."""
        frappe.db.set_value("Storefront", self.name, "total_followers",
                          cint(self.total_followers) + 1, update_modified=False)

    def remove_follower(self):
        """Decrement follower count."""
        if cint(self.total_followers) > 0:
            frappe.db.set_value("Storefront", self.name, "total_followers",
                              cint(self.total_followers) - 1, update_modified=False)

    # Status Check Methods
    def is_active(self):
        """Check if storefront is active and published."""
        return self.status == "Active" and cint(self.is_published)

    def can_be_published(self):
        """Check if storefront can be published."""
        seller_status = frappe.db.get_value("Seller Profile", self.seller,
                                            ["status", "verification_status"], as_dict=True)
        return (seller_status.status == "Active" and
                seller_status.verification_status == "Verified")

    def get_theme_config(self):
        """Get theme configuration as dictionary."""
        return {
            "theme": self.theme,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "layout_type": self.layout_type,
            "custom_css": self.custom_css
        }

    def get_public_info(self):
        """Get public-facing storefront information."""
        return {
            "name": self.name,
            "store_name": self.store_name,
            "slug": self.slug,
            "tagline": self.tagline,
            "short_description": self.short_description,
            "about": self.about_html,
            "logo": self.logo,
            "banner": self.banner,
            "theme": self.get_theme_config(),
            "contact": {
                "email": self.public_email,
                "phone": self.public_phone,
                "whatsapp": self.whatsapp_number,
                "address": self.public_address if self.show_address else None
            },
            "social": {
                "facebook": self.facebook_url,
                "instagram": self.instagram_url,
                "twitter": self.twitter_url,
                "linkedin": self.linkedin_url,
                "youtube": self.youtube_url,
                "tiktok": self.tiktok_url
            },
            "stats": {
                "total_products": self.total_products,
                "average_rating": self.average_rating,
                "total_reviews": self.total_reviews,
                "total_sales": self.total_sales
            },
            "layout": {
                "show_banner": cint(self.show_banner),
                "show_featured_products": cint(self.show_featured_products),
                "featured_products_count": self.featured_products_count,
                "show_categories": cint(self.show_categories),
                "show_reviews": cint(self.show_reviews),
                "show_contact_info": cint(self.show_contact_info),
                "products_per_page": self.products_per_page
            },
            "route": self.route
        }


# API Endpoints
@frappe.whitelist()
def get_storefront(storefront_name=None, slug=None, seller=None):
    """
    Get storefront details.

    Args:
        storefront_name: Name of the storefront
        slug: URL slug of the storefront
        seller: Seller profile linked to the storefront

    Returns:
        dict: Storefront public information
    """
    if not storefront_name and not slug and not seller:
        frappe.throw(_("Please provide storefront name, slug, or seller"))

    filters = {}
    if storefront_name:
        filters["name"] = storefront_name
    elif slug:
        filters["slug"] = slug
    elif seller:
        filters["seller"] = seller

    storefront_name = frappe.db.get_value("Storefront", filters, "name")

    if not storefront_name:
        return {"error": _("Storefront not found")}

    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check if published or user has permission
    if not storefront.is_active():
        if not frappe.has_permission("Storefront", "read", storefront_name):
            frappe.throw(_("This storefront is not available"))

    return storefront.get_public_info()


@frappe.whitelist()
def get_storefront_by_slug(slug):
    """
    Get storefront by URL slug.

    Args:
        slug: URL slug of the storefront

    Returns:
        dict: Storefront public information
    """
    return get_storefront(slug=slug)


@frappe.whitelist()
def get_my_storefront():
    """
    Get the current user's storefront.

    Returns:
        dict: Storefront details or None
    """
    seller_name = frappe.db.get_value("Seller Profile", {"user": frappe.session.user}, "name")

    if not seller_name:
        return None

    storefront_name = frappe.db.get_value("Storefront", {"seller": seller_name}, "name")

    if not storefront_name:
        return None

    storefront = frappe.get_doc("Storefront", storefront_name)
    return storefront.get_public_info()


@frappe.whitelist()
def create_storefront(seller, store_name=None, **kwargs):
    """
    Create a new storefront for a seller.

    Args:
        seller: Seller profile name
        store_name: Name for the store
        **kwargs: Additional storefront fields

    Returns:
        dict: Created storefront information
    """
    # Check if user owns the seller profile or has admin permission
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "create"):
        frappe.throw(_("Not permitted to create storefront for this seller"))

    # Check if seller already has a storefront
    if frappe.db.exists("Storefront", {"seller": seller}):
        frappe.throw(_("Seller already has a storefront"))

    storefront_data = {
        "doctype": "Storefront",
        "seller": seller,
        "store_name": store_name,
        **kwargs
    }

    storefront = frappe.get_doc(storefront_data)
    storefront.insert()

    return {
        "status": "success",
        "message": _("Storefront created successfully"),
        "storefront": storefront.get_public_info()
    }


@frappe.whitelist()
def update_storefront(storefront_name, **kwargs):
    """
    Update an existing storefront.

    Args:
        storefront_name: Name of the storefront
        **kwargs: Fields to update

    Returns:
        dict: Updated storefront information
    """
    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to update this storefront"))

    # Update allowed fields
    allowed_fields = [
        "store_name", "tagline", "short_description", "about_html",
        "logo", "banner", "favicon", "theme", "primary_color", "secondary_color",
        "accent_color", "background_color", "text_color", "layout_type",
        "show_banner", "show_featured_products", "featured_products_count",
        "show_categories", "show_reviews", "show_contact_info", "products_per_page",
        "meta_title", "meta_description", "meta_keywords", "og_image",
        "public_email", "public_phone", "whatsapp_number", "show_address", "public_address",
        "facebook_url", "instagram_url", "twitter_url", "linkedin_url", "youtube_url", "tiktok_url",
        "shipping_policy", "return_policy", "privacy_policy", "terms_of_service",
        "custom_css", "custom_header_html", "custom_footer_html"
    ]

    for field in allowed_fields:
        if field in kwargs:
            setattr(storefront, field, kwargs[field])

    storefront.save()

    return {
        "status": "success",
        "message": _("Storefront updated successfully"),
        "storefront": storefront.get_public_info()
    }


@frappe.whitelist()
def publish_storefront(storefront_name):
    """
    Publish a storefront.

    Args:
        storefront_name: Name of the storefront

    Returns:
        dict: Status of operation
    """
    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to publish this storefront"))

    storefront.publish()

    return {
        "status": "success",
        "message": _("Storefront published successfully"),
        "is_published": storefront.is_published
    }


@frappe.whitelist()
def unpublish_storefront(storefront_name):
    """
    Unpublish a storefront.

    Args:
        storefront_name: Name of the storefront

    Returns:
        dict: Status of operation
    """
    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to unpublish this storefront"))

    storefront.unpublish()

    return {
        "status": "success",
        "message": _("Storefront unpublished"),
        "is_published": storefront.is_published
    }


@frappe.whitelist(allow_guest=True)
def get_featured_storefronts(limit=10):
    """
    Get featured storefronts.

    Args:
        limit: Maximum number of storefronts to return

    Returns:
        list: Featured storefronts
    """
    storefronts = frappe.db.sql("""
        SELECT
            name, store_name, slug, tagline, logo, banner,
            average_rating, total_reviews, total_products, total_sales
        FROM `tabStorefront`
        WHERE status = 'Active'
        AND is_published = 1
        AND is_featured = 1
        AND (featured_until IS NULL OR featured_until >= NOW())
        ORDER BY featured_priority DESC, average_rating DESC
        LIMIT %s
    """, cint(limit), as_dict=True)

    return storefronts


@frappe.whitelist(allow_guest=True)
def get_top_storefronts(limit=10, sort_by="rating"):
    """
    Get top storefronts by various criteria.

    Args:
        limit: Maximum number of storefronts to return
        sort_by: Sorting criteria (rating, sales, products, views)

    Returns:
        list: Top storefronts
    """
    sort_map = {
        "rating": "average_rating DESC",
        "sales": "total_sales DESC",
        "products": "total_products DESC",
        "views": "total_views DESC",
        "followers": "total_followers DESC"
    }

    order_by = sort_map.get(sort_by, "average_rating DESC")

    storefronts = frappe.db.sql(f"""
        SELECT
            name, store_name, slug, tagline, logo, banner,
            average_rating, total_reviews, total_products,
            total_sales, total_views, total_followers
        FROM `tabStorefront`
        WHERE status = 'Active'
        AND is_published = 1
        ORDER BY {order_by}
        LIMIT %s
    """, cint(limit), as_dict=True)

    return storefronts


@frappe.whitelist(allow_guest=True)
def search_storefronts(query, limit=20):
    """
    Search storefronts by name or tags.

    Args:
        query: Search query
        limit: Maximum number of results

    Returns:
        list: Matching storefronts
    """
    if not query or len(query) < 2:
        return []

    storefronts = frappe.db.sql("""
        SELECT
            name, store_name, slug, tagline, logo,
            average_rating, total_reviews, total_products
        FROM `tabStorefront`
        WHERE status = 'Active'
        AND is_published = 1
        AND (
            store_name LIKE %s
            OR tagline LIKE %s
            OR short_description LIKE %s
            OR meta_keywords LIKE %s
        )
        ORDER BY average_rating DESC
        LIMIT %s
    """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", cint(limit)), as_dict=True)

    return storefronts


@frappe.whitelist(allow_guest=True)
def record_storefront_view(storefront_name):
    """
    Record a view for a storefront.

    Args:
        storefront_name: Name of the storefront

    Returns:
        dict: Status
    """
    if not frappe.db.exists("Storefront", storefront_name):
        return {"status": "error", "message": "Storefront not found"}

    storefront = frappe.get_doc("Storefront", storefront_name)
    storefront.increment_views()

    return {"status": "success", "total_views": cint(storefront.total_views) + 1}


@frappe.whitelist()
def update_storefront_stats(storefront_name):
    """
    Update storefront statistics.

    Args:
        storefront_name: Name of the storefront

    Returns:
        dict: Updated statistics
    """
    storefront = frappe.get_doc("Storefront", storefront_name)
    return storefront.update_stats()


@frappe.whitelist()
def get_storefront_analytics(storefront_name, period="30d"):
    """
    Get analytics for a storefront.

    Args:
        storefront_name: Name of the storefront
        period: Time period (7d, 30d, 90d, 365d)

    Returns:
        dict: Analytics data
    """
    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "read"):
        frappe.throw(_("Not permitted to view analytics"))

    period_days = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "365d": 365
    }.get(period, 30)

    # Get daily view counts (placeholder - would need view tracking)
    # Get product performance
    product_stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_products,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_products,
            SUM(view_count) as total_product_views
        FROM `tabListing`
        WHERE seller = %s
    """, storefront.seller, as_dict=True)

    # Get order stats
    order_stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_orders,
            COALESCE(SUM(total), 0) as total_revenue
        FROM `tabSub Order`
        WHERE seller = %s
        AND status = 'Completed'
        AND creation >= DATE_SUB(NOW(), INTERVAL %s DAY)
    """, (storefront.seller, period_days), as_dict=True)

    return {
        "storefront_name": storefront_name,
        "period": period,
        "stats": {
            "total_views": storefront.total_views,
            "total_followers": storefront.total_followers,
            "average_rating": storefront.average_rating,
            "total_reviews": storefront.total_reviews
        },
        "products": product_stats[0] if product_stats else {},
        "orders": order_stats[0] if order_stats else {}
    }
