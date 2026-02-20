# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, add_days
from frappe.utils.file_manager import save_file
import json
import re

# Import ERPNext sync utilities
from tradehub_core.tradehub_core.utils.erpnext_sync import (
    create_item_from_listing,
    sync_item_from_listing,
    is_erpnext_installed,
    ERPNextSyncError,
)


class Listing(Document):
    """
    Marketplace Listing DocType extending ERPNext Item.

    Listings represent products/services offered for sale on the TR-TradeHub
    marketplace. Each listing:
    - Links to a Seller Profile (required)
    - Can sync to ERPNext Item for inventory management
    - Supports variants (via Listing Variant DocType)
    - Has moderation workflow for content approval
    - Tracks views, orders, and ratings
    - Supports different listing types (Fixed Price, Auction, RFQ)
    """
    website = frappe._dict()

    def before_insert(self):
        """Set default values before inserting a new listing."""
        # Generate unique listing code
        if not self.listing_code:
            self.listing_code = self.generate_listing_code()

        # Set created by
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant from seller's tenant if not specified
        if not self.tenant and self.seller:
            self.set_tenant_from_seller()

        # Set attribute set from category if not specified
        if not self.attribute_set and self.category:
            self.set_attribute_set_from_category()

        # Initialize images as empty array
        if not self.images:
            self.images = "[]"

        # Initialize attributes as empty object
        if not self.attributes:
            self.attributes = "{}"

        # Initialize bulk pricing tiers
        if not self.bulk_pricing_tiers:
            self.bulk_pricing_tiers = "[]"

    def validate(self):
        """Validate listing data before saving."""
        self.validate_seller()
        self.validate_tenant_seller_consistency()
        self.validate_seller_can_create_listing()
        self.validate_prices()
        self.validate_inventory()
        self.validate_category()
        self.validate_auction_settings()
        self.validate_b2b_settings()
        self.validate_visibility_dates()
        self.validate_sale_dates()
        self.validate_images()
        self.calculate_available_qty()
        self.set_listing_type_flags()
        self.generate_route()
        self.update_status_based_on_inventory()

    def before_save(self):
        """Actions before saving the listing."""
        # Update quality score (basic calculation)
        self.calculate_quality_score()

    def on_update(self):
        """Actions to perform after listing is updated."""
        self.clear_listing_cache()

        # Sync to ERPNext Item if exists
        if self.erpnext_item:
            self.sync_to_erpnext_item()

    def on_submit(self):
        """Actions when listing is submitted (published)."""
        # Create ERPNext Item if not exists
        if not self.erpnext_item:
            self.create_erpnext_item()

        # Set published timestamp
        if not self.published_at:
            self.db_set("published_at", now_datetime())

        # Update status to Active if moderation is approved
        if self.moderation_status == "Approved" or not self.requires_approval:
            self.db_set("status", "Active")
            self.db_set("moderation_status", "Approved")
        else:
            self.db_set("status", "Pending Review")
            self.db_set("moderation_status", "Pending")

    def on_cancel(self):
        """Actions when listing is cancelled."""
        self.db_set("status", "Archived")

    def on_trash(self):
        """Prevent deletion of listing with pending orders."""
        self.check_linked_documents()

    # Helper Methods
    def generate_listing_code(self):
        """Generate a unique listing code."""
        return f"LST-{frappe.generate_hash(length=8).upper()}"

    def set_tenant_from_seller(self):
        """Set tenant from seller's profile."""
        if self.seller:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant

    def set_attribute_set_from_category(self):
        """Set attribute set from the selected category."""
        if self.category:
            attribute_set = frappe.db.get_value("Category", self.category, "attribute_set")
            if attribute_set:
                self.attribute_set = attribute_set

    # Validation Methods
    def validate_seller(self):
        """Validate seller link."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

    def validate_tenant_seller_consistency(self):
        """
        Ensure tenant matches seller's tenant.

        This validation prevents data inconsistency where a listing could be
        linked to a seller from a different tenant. Such inconsistency would
        break tenant isolation and data security.

        Raises:
            frappe.ValidationError: If the selected seller belongs to a
            different tenant than the listing's tenant.
        """
        if not self.seller:
            return

        seller_tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")

        # If listing has no tenant set but seller has one, use seller's tenant
        if not self.tenant and seller_tenant:
            self.tenant = seller_tenant
            return

        # If both have tenant set, they must match
        if self.tenant and seller_tenant and self.tenant != seller_tenant:
            seller_name = frappe.db.get_value("Seller Profile", self.seller, "seller_name")
            frappe.throw(
                _("Tenant mismatch: Seller '{0}' belongs to a different tenant. "
                  "Please select a seller from tenant '{1}' or change the listing's tenant.").format(
                    seller_name or self.seller, self.tenant
                )
            )

    def validate_seller_can_create_listing(self):
        """Check if seller can create/update listings."""
        if self.is_new():
            seller = frappe.get_doc("Seller Profile", self.seller)

            # Check if seller is active
            if seller.status not in ["Active", "Vacation"]:
                frappe.throw(
                    _("Seller {0} is not active and cannot create listings").format(
                        seller.seller_name
                    )
                )

            # Check if seller can create listings
            if not cint(seller.can_create_listings):
                frappe.throw(
                    _("Seller {0} is restricted from creating listings").format(
                        seller.seller_name
                    )
                )

            # Check listing limit
            if not seller.can_create_listing():
                frappe.throw(
                    _("Seller {0} has reached their maximum listing limit of {1}").format(
                        seller.seller_name, seller.max_listings
                    )
                )

    def validate_prices(self):
        """Validate pricing fields."""
        if flt(self.base_price) <= 0:
            frappe.throw(_("Base Price must be greater than 0"))

        if flt(self.selling_price) <= 0:
            frappe.throw(_("Selling Price must be greater than 0"))

        if flt(self.selling_price) > flt(self.base_price):
            frappe.throw(_("Selling Price cannot be greater than Base Price"))

        if self.compare_at_price and flt(self.compare_at_price) < flt(self.selling_price):
            frappe.throw(_("Compare at Price should be greater than Selling Price"))

        if self.cost_price and flt(self.cost_price) < 0:
            frappe.throw(_("Cost Price cannot be negative"))

    def validate_inventory(self):
        """Validate inventory fields."""
        if flt(self.stock_qty) < 0:
            frappe.throw(_("Stock Quantity cannot be negative"))

        if flt(self.min_order_qty) <= 0:
            self.min_order_qty = 1

        if self.max_order_qty and flt(self.max_order_qty) > 0:
            if flt(self.max_order_qty) < flt(self.min_order_qty):
                frappe.throw(_("Max Order Quantity cannot be less than Min Order Quantity"))

    def validate_category(self):
        """Validate category selection."""
        if not self.category:
            frappe.throw(_("Category is required"))

        if not frappe.db.exists("Category", self.category):
            frappe.throw(_("Category {0} does not exist").format(self.category))

        # Validate subcategory if specified
        if self.subcategory:
            if not frappe.db.exists("Category", self.subcategory):
                frappe.throw(_("Subcategory {0} does not exist").format(self.subcategory))

            # Check if subcategory is child of category
            parent = frappe.db.get_value("Category", self.subcategory, "parent_category")
            if parent != self.category:
                frappe.throw(
                    _("Subcategory {0} is not a child of Category {1}").format(
                        self.subcategory, self.category
                    )
                )

    def validate_auction_settings(self):
        """Validate auction settings if listing type is Auction."""
        if self.listing_type == "Auction":
            self.is_auction = 1

            if not self.auction_start_date:
                frappe.throw(_("Auction Start Date is required for auction listings"))

            if not self.auction_end_date:
                frappe.throw(_("Auction End Date is required for auction listings"))

            if self.auction_end_date <= self.auction_start_date:
                frappe.throw(_("Auction End Date must be after Start Date"))

            if not self.starting_bid or flt(self.starting_bid) <= 0:
                frappe.throw(_("Starting Bid is required and must be greater than 0"))

            if self.reserve_price and flt(self.reserve_price) < flt(self.starting_bid):
                frappe.throw(_("Reserve Price cannot be less than Starting Bid"))

            if self.buy_now_price:
                if flt(self.buy_now_price) <= flt(self.starting_bid):
                    frappe.throw(_("Buy Now Price must be greater than Starting Bid"))

                if self.reserve_price and flt(self.buy_now_price) <= flt(self.reserve_price):
                    frappe.throw(_("Buy Now Price must be greater than Reserve Price"))
        else:
            self.is_auction = 0

    def validate_b2b_settings(self):
        """Validate B2B pricing settings."""
        if self.b2b_enabled:
            if not self.wholesale_min_qty or flt(self.wholesale_min_qty) <= 0:
                frappe.throw(
                    _("Wholesale Minimum Quantity is required when B2B is enabled")
                )

            if not self.wholesale_price or flt(self.wholesale_price) <= 0:
                frappe.throw(_("Wholesale Price is required when B2B is enabled"))

            if flt(self.wholesale_price) >= flt(self.selling_price):
                frappe.throw(
                    _("Wholesale Price should be less than regular Selling Price")
                )

            # Validate bulk pricing tiers
            if self.bulk_pricing_enabled and self.bulk_pricing_tiers:
                self.validate_bulk_pricing_tiers()

    def validate_bulk_pricing_tiers(self):
        """Validate bulk pricing tier structure."""
        try:
            tiers = json.loads(self.bulk_pricing_tiers or "[]")
        except json.JSONDecodeError:
            frappe.throw(_("Invalid Bulk Pricing Tiers format"))
            return

        if not tiers:
            return

        prev_max = 0
        for i, tier in enumerate(tiers):
            if "min_qty" not in tier or "price" not in tier:
                frappe.throw(
                    _("Bulk pricing tier {0} must have min_qty and price").format(i + 1)
                )

            min_qty = flt(tier.get("min_qty"))
            max_qty = flt(tier.get("max_qty", 0))
            price = flt(tier.get("price"))

            if min_qty <= 0:
                frappe.throw(
                    _("Min quantity in tier {0} must be greater than 0").format(i + 1)
                )

            if price <= 0:
                frappe.throw(
                    _("Price in tier {0} must be greater than 0").format(i + 1)
                )

            if min_qty <= prev_max:
                frappe.throw(
                    _("Min quantity in tier {0} must be greater than previous tier's max")
                    .format(i + 1)
                )

            if max_qty > 0:
                prev_max = max_qty

    def validate_visibility_dates(self):
        """Validate visibility date range."""
        if self.visibility_start_date and self.visibility_end_date:
            if self.visibility_end_date <= self.visibility_start_date:
                frappe.throw(_("Visibility End Date must be after Start Date"))

    def validate_sale_dates(self):
        """Validate sale date range."""
        if self.is_on_sale:
            if self.sale_start_date and self.sale_end_date:
                if self.sale_end_date <= self.sale_start_date:
                    frappe.throw(_("Sale End Date must be after Start Date"))

    def validate_images(self):
        """Validate images JSON structure."""
        if self.images:
            try:
                images = json.loads(self.images)
                if not isinstance(images, list):
                    frappe.throw(_("Images must be a JSON array"))
            except json.JSONDecodeError:
                frappe.throw(_("Invalid Images JSON format"))

    def calculate_available_qty(self):
        """Calculate available quantity (stock - reserved)."""
        self.available_qty = max(0, flt(self.stock_qty) - flt(self.reserved_qty))

    def set_listing_type_flags(self):
        """Set flags based on listing type."""
        self.is_auction = 1 if self.listing_type == "Auction" else 0

    def generate_route(self):
        """Generate SEO-friendly route if not set."""
        if not self.route and self.title:
            # Create slug from title
            slug = self.title.lower()
            slug = re.sub(r"[^a-z0-9\s-]", "", slug)
            slug = re.sub(r"[\s]+", "-", slug)
            slug = re.sub(r"-+", "-", slug)
            slug = slug.strip("-")

            self.route = f"products/{self.listing_code}/{slug}"

    def update_status_based_on_inventory(self):
        """Update status based on inventory levels."""
        if self.status in ["Draft", "Pending Review", "Suspended", "Rejected", "Archived"]:
            return

        if self.track_inventory:
            if flt(self.available_qty) <= 0 and not self.allow_backorders:
                if self.status != "Out of Stock":
                    self.status = "Out of Stock"
            elif self.status == "Out of Stock" and flt(self.available_qty) > 0:
                self.status = "Active"

    def calculate_quality_score(self):
        """Calculate a quality score based on listing completeness."""
        score = 0
        max_score = 100

        # Title quality (20 points)
        if self.title and len(self.title) > 20:
            score += 20
        elif self.title:
            score += 10

        # Description (20 points)
        if self.description and len(self.description) > 200:
            score += 20
        elif self.description and len(self.description) > 50:
            score += 10

        # Images (20 points)
        if self.primary_image:
            score += 10
        if self.images:
            try:
                images = json.loads(self.images)
                if len(images) >= 3:
                    score += 10
                elif len(images) >= 1:
                    score += 5
            except (json.JSONDecodeError, TypeError):
                pass

        # Pricing (10 points)
        if self.selling_price and self.base_price:
            score += 5
        if self.compare_at_price:
            score += 5

        # Specifications (10 points)
        if self.sku:
            score += 3
        if self.brand:
            score += 3
        if self.weight:
            score += 2
        if self.barcode:
            score += 2

        # SEO (10 points)
        if self.meta_title:
            score += 3
        if self.meta_description:
            score += 4
        if self.meta_keywords:
            score += 3

        # Attributes (10 points)
        if self.attributes:
            try:
                attrs = json.loads(self.attributes)
                if attrs and len(attrs) > 0:
                    score += 10
            except (json.JSONDecodeError, TypeError):
                pass

        self.quality_score = min(score, max_score)

    # ERPNext Integration Methods
    def create_erpnext_item(self):
        """
        Create a linked ERPNext Item record.

        This method is called on submit (docstatus = 1) to create a corresponding
        ERPNext Item for inventory management. Uses centralized sync utility.
        """
        if not is_erpnext_installed():
            frappe.log_error(
                "ERPNext not installed - skipping Item creation",
                "Listing ERPNext Sync"
            )
            return

        try:
            item_name = create_item_from_listing(self)
            if item_name:
                frappe.msgprint(
                    _("ERPNext Item {0} created successfully").format(item_name),
                    indicator="green",
                    alert=True
                )
        except ERPNextSyncError as e:
            frappe.log_error(
                f"Failed to create ERPNext Item for Listing {self.name}: {str(e)}",
                "Listing ERPNext Sync Error"
            )
            # Don't throw - allow listing to be submitted even if ERPNext sync fails
            frappe.msgprint(
                _("Warning: ERPNext Item creation failed. You can retry sync later."),
                indicator="orange",
                alert=True
            )

    def sync_to_erpnext_item(self):
        """
        Sync listing data to linked ERPNext Item.

        This method is called on update (on_update hook) to keep the ERPNext
        Item in sync with listing changes. Uses centralized sync utility.
        """
        if not self.erpnext_item:
            return

        if not is_erpnext_installed():
            return

        try:
            success = sync_item_from_listing(self)
            if not success and self.erpnext_item:
                # Item might have been deleted, check and clear reference
                if not frappe.db.exists("Item", self.erpnext_item):
                    self.db_set("erpnext_item", None, update_modified=False)
        except Exception as e:
            frappe.log_error(
                f"Failed to sync ERPNext Item for Listing {self.name}: {str(e)}",
                "Listing ERPNext Sync Error"
            )

    def get_erpnext_category(self):
        """Get ERPNext Item Group from Category."""
        if self.category:
            return frappe.db.get_value(
                "Category", self.category, "erpnext_item_group"
            ) or "All Item Groups"
        return "All Item Groups"

    # Status Methods
    def publish(self):
        """Publish the listing (make it active)."""
        if self.docstatus == 0:
            frappe.throw(_("Please submit the listing first"))

        if self.status in ["Suspended", "Rejected"]:
            frappe.throw(
                _("Cannot publish a {0} listing").format(self.status.lower())
            )

        self.db_set("status", "Active")
        if not self.published_at:
            self.db_set("published_at", now_datetime())
        self.clear_listing_cache()

    def pause(self):
        """Pause the listing (temporarily hide from marketplace)."""
        if self.status not in ["Active", "Out of Stock"]:
            frappe.throw(_("Can only pause active listings"))

        self.db_set("status", "Paused")
        self.clear_listing_cache()

    def unpause(self):
        """Unpause the listing (make it active again)."""
        if self.status != "Paused":
            frappe.throw(_("Listing is not paused"))

        if flt(self.available_qty) <= 0 and not self.allow_backorders:
            self.db_set("status", "Out of Stock")
        else:
            self.db_set("status", "Active")
        self.clear_listing_cache()

    def archive(self):
        """Archive the listing."""
        self.db_set("status", "Archived")
        self.db_set("is_visible", 0)
        self.clear_listing_cache()

    def suspend(self, reason=None):
        """Suspend the listing (admin action)."""
        self.db_set("status", "Suspended")
        self.db_set("is_visible", 0)
        if reason:
            self.db_set("moderation_notes", f"Suspended: {reason}")
        self.clear_listing_cache()

    # Moderation Methods
    def approve(self, moderator=None):
        """Approve the listing after moderation."""
        self.db_set("moderation_status", "Approved")
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())

        if self.docstatus == 1:
            self.db_set("status", "Active")

        self.clear_listing_cache()

    def reject(self, reason, moderator=None):
        """Reject the listing with reason."""
        self.db_set("moderation_status", "Rejected")
        self.db_set("rejection_reason", reason)
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())
        self.db_set("status", "Rejected")
        self.db_set("is_visible", 0)
        self.clear_listing_cache()

    def flag(self, reason=None):
        """Flag the listing for review."""
        self.db_set("moderation_status", "Flagged")
        if reason:
            self.db_set(
                "moderation_notes",
                f"Flagged: {reason}\n\n{self.moderation_notes or ''}"
            )
        self.clear_listing_cache()

    # Inventory Methods
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

        self.clear_listing_cache()

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
        self.clear_listing_cache()

    def release_reservation(self, qty):
        """Release reserved stock."""
        new_reserved = max(0, flt(self.reserved_qty) - flt(qty))
        self.db_set("reserved_qty", new_reserved)
        self.db_set("available_qty", max(0, flt(self.stock_qty) - new_reserved))
        self.clear_listing_cache()

    # Statistics Methods
    def increment_view_count(self):
        """Increment view count (should be called from page view tracking)."""
        frappe.db.set_value(
            "Listing", self.name, "view_count", cint(self.view_count) + 1,
            update_modified=False
        )

    def increment_wishlist_count(self):
        """Increment wishlist count."""
        frappe.db.set_value(
            "Listing", self.name, "wishlist_count", cint(self.wishlist_count) + 1,
            update_modified=False
        )

    def decrement_wishlist_count(self):
        """Decrement wishlist count."""
        frappe.db.set_value(
            "Listing", self.name, "wishlist_count",
            max(0, cint(self.wishlist_count) - 1),
            update_modified=False
        )

    def increment_order_count(self):
        """Increment order count."""
        frappe.db.set_value(
            "Listing", self.name, "order_count", cint(self.order_count) + 1,
            update_modified=False
        )
        frappe.db.set_value(
            "Listing", self.name, "last_sold_at", now_datetime(),
            update_modified=False
        )

    def update_rating(self):
        """Update average rating from reviews."""
        result = frappe.db.sql("""
            SELECT AVG(rating) as avg_rating, COUNT(*) as review_count
            FROM `tabReview`
            WHERE listing = %s AND status = 'Approved'
        """, self.name, as_dict=True)

        if result:
            self.db_set("average_rating", round(flt(result[0].avg_rating), 2))
            self.db_set("review_count", cint(result[0].review_count))
        self.clear_listing_cache()

    # Pricing Methods
    def get_price(self, qty=1, buyer_type="B2C"):
        """Get the applicable price based on quantity and buyer type."""
        if buyer_type == "B2B" and self.b2b_enabled:
            if flt(qty) >= flt(self.wholesale_min_qty):
                # Check bulk pricing tiers first
                if self.bulk_pricing_enabled and self.bulk_pricing_tiers:
                    tier_price = self.get_bulk_tier_price(qty)
                    if tier_price:
                        return tier_price
                return flt(self.wholesale_price)

        # Check sale price
        if self.is_on_sale and self.is_sale_active():
            return flt(self.selling_price)

        return flt(self.selling_price)

    def get_bulk_tier_price(self, qty):
        """Get price from bulk pricing tiers."""
        try:
            tiers = json.loads(self.bulk_pricing_tiers or "[]")
            for tier in sorted(tiers, key=lambda x: x.get("min_qty", 0), reverse=True):
                min_qty = flt(tier.get("min_qty", 0))
                max_qty = flt(tier.get("max_qty", 0))

                if flt(qty) >= min_qty:
                    if max_qty == 0 or flt(qty) <= max_qty:
                        return flt(tier.get("price"))
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def is_sale_active(self):
        """Check if sale is currently active."""
        if not self.is_on_sale:
            return False

        now = now_datetime()
        if self.sale_start_date and now < self.sale_start_date:
            return False
        if self.sale_end_date and now > self.sale_end_date:
            return False

        return True

    def get_discount_percentage(self):
        """Calculate discount percentage."""
        if self.compare_at_price and flt(self.compare_at_price) > 0:
            discount = (
                (flt(self.compare_at_price) - flt(self.selling_price))
                / flt(self.compare_at_price) * 100
            )
            return round(discount, 0)
        return 0

    # Helper Methods
    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for pending order lines
        if frappe.db.exists("Cart Line", {"listing": self.name}):
            frappe.throw(
                _("Cannot delete Listing with items in shopping carts")
            )

        # Check for reviews
        if frappe.db.exists("Review", {"listing": self.name}):
            frappe.throw(
                _("Cannot delete Listing with reviews. Consider archiving instead.")
            )

    def clear_listing_cache(self):
        """Clear cached listing data."""
        cache_key = f"listing:{self.name}"
        frappe.cache().delete_value(cache_key)

        if self.listing_code:
            code_cache_key = f"listing_by_code:{self.listing_code}"
            frappe.cache().delete_value(code_cache_key)

    def is_visible_to_buyer(self):
        """Check if listing is visible to buyers."""
        if not self.is_visible:
            return False

        if self.status not in ["Active", "Out of Stock"]:
            return False

        now = now_datetime()
        if self.visibility_start_date and now < self.visibility_start_date:
            return False
        if self.visibility_end_date and now > self.visibility_end_date:
            return False

        return True

    def get_seller_details(self):
        """Get seller profile details for the listing."""
        if not self.seller:
            return None

        return frappe.db.get_value(
            "Seller Profile",
            self.seller,
            ["seller_name", "display_name", "city", "average_rating", "is_verified"],
            as_dict=True
        )


# API Endpoints
@frappe.whitelist()
def get_listing(listing_name=None, listing_code=None):
    """
    Get listing details.

    Args:
        listing_name: Name of the listing
        listing_code: Unique listing code

    Returns:
        dict: Listing details
    """
    if not listing_name and not listing_code:
        frappe.throw(_("Either listing_name or listing_code is required"))

    if listing_code and not listing_name:
        listing_name = frappe.db.get_value(
            "Listing", {"listing_code": listing_code}, "name"
        )

    if not listing_name:
        return {"error": _("Listing not found")}

    listing = frappe.get_doc("Listing", listing_name)

    # Check visibility for non-admin users
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value("Seller Profile", listing.seller, "user")
        if seller_user != frappe.session.user and not listing.is_visible_to_buyer():
            return {"error": _("Listing not found or not available")}

    return {
        "name": listing.name,
        "listing_code": listing.listing_code,
        "title": listing.title,
        "seller": listing.seller,
        "seller_details": listing.get_seller_details(),
        "status": listing.status,
        "listing_type": listing.listing_type,
        "category": listing.category,
        "brand": listing.brand,
        "short_description": listing.short_description,
        "description": listing.description,
        "currency": listing.currency,
        "selling_price": listing.selling_price,
        "compare_at_price": listing.compare_at_price,
        "discount_percentage": listing.get_discount_percentage(),
        "is_on_sale": listing.is_on_sale,
        "available_qty": listing.available_qty,
        "stock_uom": listing.stock_uom,
        "min_order_qty": listing.min_order_qty,
        "max_order_qty": listing.max_order_qty,
        "primary_image": listing.primary_image,
        "images": json.loads(listing.images or "[]"),
        "attributes": json.loads(listing.attributes or "{}"),
        "route": listing.route,
        "is_visible": listing.is_visible,
        "average_rating": listing.average_rating,
        "review_count": listing.review_count,
        "view_count": listing.view_count,
        "order_count": listing.order_count,
    }


@frappe.whitelist()
def search_listings(
    query=None,
    category=None,
    seller=None,
    min_price=None,
    max_price=None,
    sort_by="modified",
    sort_order="DESC",
    page=1,
    page_size=20
):
    """
    Search and filter listings.

    Args:
        query: Search query
        category: Filter by category
        seller: Filter by seller
        min_price: Minimum price filter
        max_price: Maximum price filter
        sort_by: Sort field
        sort_order: Sort order (ASC/DESC)
        page: Page number
        page_size: Results per page

    Returns:
        dict: Search results with pagination
    """
    filters = {
        "status": ["in", ["Active", "Out of Stock"]],
        "is_visible": 1,
        "docstatus": 1,
    }

    if category:
        filters["category"] = category

    if seller:
        filters["seller"] = seller

    if min_price:
        filters["selling_price"] = [">=", flt(min_price)]

    if max_price:
        filters["selling_price"] = ["<=", flt(max_price)]

    # Build SQL for search
    search_condition = ""
    if query:
        search_condition = f"""
            AND (
                title LIKE %s
                OR short_description LIKE %s
                OR brand LIKE %s
                OR sku LIKE %s
            )
        """

    # Calculate pagination
    start = (cint(page) - 1) * cint(page_size)

    # Get total count
    count_query = f"""
        SELECT COUNT(*) as total
        FROM `tabListing`
        WHERE status IN ('Active', 'Out of Stock')
        AND is_visible = 1
        AND docstatus = 1
        {f"AND category = %(category)s" if category else ""}
        {f"AND seller = %(seller)s" if seller else ""}
        {f"AND selling_price >= %(min_price)s" if min_price else ""}
        {f"AND selling_price <= %(max_price)s" if max_price else ""}
        {search_condition}
    """

    params = {}
    if category:
        params["category"] = category
    if seller:
        params["seller"] = seller
    if min_price:
        params["min_price"] = flt(min_price)
    if max_price:
        params["max_price"] = flt(max_price)

    if query:
        search_term = f"%{query}%"
        result = frappe.db.sql(
            count_query,
            (search_term, search_term, search_term, search_term),
            as_dict=True
        )
    else:
        result = frappe.db.sql(count_query, params, as_dict=True)

    total = result[0].total if result else 0

    # Get listings
    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "status",
            "category", "brand", "selling_price", "compare_at_price",
            "currency", "available_qty", "primary_image", "average_rating",
            "review_count", "is_on_sale", "is_featured", "is_best_seller"
        ],
        or_filters=[
            {"title": ["like", f"%{query}%"]},
            {"short_description": ["like", f"%{query}%"]},
            {"brand": ["like", f"%{query}%"]},
            {"sku": ["like", f"%{query}%"]},
        ] if query else None,
        order_by=f"{sort_by} {sort_order}",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "listings": listings,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def create_listing(**kwargs):
    """
    Create a new listing.

    Returns:
        dict: Created listing details
    """
    # Validate required fields
    required = ["title", "category", "selling_price", "seller"]
    for field in required:
        if not kwargs.get(field):
            frappe.throw(_(f"{field} is required"))

    # Check if user is allowed to create listings
    seller = kwargs.get("seller")
    if seller:
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if seller_user != frappe.session.user:
            if not frappe.has_permission("Listing", "write"):
                frappe.throw(_("Not permitted to create listings for other sellers"))

    listing = frappe.get_doc({
        "doctype": "Listing",
        **kwargs
    })
    listing.insert()

    return {
        "status": "success",
        "listing_name": listing.name,
        "listing_code": listing.listing_code,
        "message": _("Listing created successfully")
    }


@frappe.whitelist()
def update_listing_status(listing_name, action):
    """
    Update listing status (publish, pause, unpause, archive, suspend).

    Args:
        listing_name: Name of the listing
        action: Action to perform (publish, pause, unpause, archive, suspend)

    Returns:
        dict: Updated status
    """
    listing = frappe.get_doc("Listing", listing_name)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", listing.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing", "write"):
            frappe.throw(_("Not permitted to update this listing"))

    if action == "publish":
        listing.publish()
    elif action == "pause":
        listing.pause()
    elif action == "unpause":
        listing.unpause()
    elif action == "archive":
        listing.archive()
    elif action == "suspend":
        if not frappe.has_permission("Listing", "write"):
            frappe.throw(_("Not permitted to suspend listings"))
        listing.suspend()
    else:
        frappe.throw(_("Invalid action: {0}").format(action))

    return {
        "status": "success",
        "listing_status": listing.status,
        "message": _("Listing status updated to {0}").format(listing.status)
    }


@frappe.whitelist()
def moderate_listing(listing_name, action, reason=None):
    """
    Moderate a listing (approve, reject, flag).

    Args:
        listing_name: Name of the listing
        action: Action to perform (approve, reject, flag)
        reason: Reason for rejection or flagging

    Returns:
        dict: Moderation result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to moderate listings"))

    listing = frappe.get_doc("Listing", listing_name)

    if action == "approve":
        listing.approve()
    elif action == "reject":
        if not reason:
            frappe.throw(_("Reason is required for rejection"))
        listing.reject(reason)
    elif action == "flag":
        listing.flag(reason)
    else:
        frappe.throw(_("Invalid action: {0}").format(action))

    return {
        "status": "success",
        "moderation_status": listing.moderation_status,
        "listing_status": listing.status,
        "message": _("Listing {0}").format(action + "ed")
    }


@frappe.whitelist()
def update_stock(listing_name, qty_change, reason=None):
    """
    Update listing stock quantity.

    Args:
        listing_name: Name of the listing
        qty_change: Quantity to add (positive) or subtract (negative)
        reason: Reason for stock change

    Returns:
        dict: Updated stock info
    """
    listing = frappe.get_doc("Listing", listing_name)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", listing.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing", "write"):
            frappe.throw(_("Not permitted to update stock for this listing"))

    listing.update_stock(flt(qty_change), reason)

    return {
        "status": "success",
        "stock_qty": listing.stock_qty,
        "available_qty": listing.available_qty,
        "reserved_qty": listing.reserved_qty,
        "listing_status": listing.status
    }


@frappe.whitelist()
def get_seller_listings(seller=None, status=None, page=1, page_size=20):
    """
    Get listings for a seller.

    Args:
        seller: Seller profile name (defaults to current user's seller)
        status: Filter by status
        page: Page number
        page_size: Results per page

    Returns:
        dict: Seller's listings with pagination
    """
    if not seller:
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )

    if not seller:
        return {"error": _("Seller profile not found")}

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("Listing", "read"):
            frappe.throw(_("Not permitted to view these listings"))

    filters = {"seller": seller}
    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)

    total = frappe.db.count("Listing", filters)

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "status", "moderation_status",
            "category", "selling_price", "currency", "stock_qty", "available_qty",
            "primary_image", "average_rating", "review_count", "view_count",
            "order_count", "is_featured", "is_on_sale", "docstatus", "creation"
        ],
        order_by="modified DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "listings": listings,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def increment_view(listing_name):
    """
    Increment listing view count.

    Args:
        listing_name: Name of the listing

    Returns:
        dict: Success status
    """
    if not frappe.db.exists("Listing", listing_name):
        return {"error": _("Listing not found")}

    listing = frappe.get_doc("Listing", listing_name)
    listing.increment_view_count()

    return {"status": "success", "view_count": cint(listing.view_count) + 1}


@frappe.whitelist()
def get_featured_listings(limit=10):
    """
    Get featured listings.

    Args:
        limit: Maximum number of listings to return

    Returns:
        list: Featured listings
    """
    return frappe.get_all(
        "Listing",
        filters={
            "status": "Active",
            "is_visible": 1,
            "is_featured": 1,
            "docstatus": 1
        },
        fields=[
            "name", "listing_code", "title", "seller", "category",
            "selling_price", "compare_at_price", "currency",
            "primary_image", "average_rating", "review_count"
        ],
        order_by="modified DESC",
        limit_page_length=cint(limit)
    )


@frappe.whitelist()
def get_listing_statistics(seller=None):
    """
    Get listing statistics for a seller or platform.

    Args:
        seller: Seller profile name (optional)

    Returns:
        dict: Listing statistics
    """
    filters = {}
    if seller:
        filters["seller"] = seller

    # Use parameterized queries to prevent SQL injection
    params = {}
    if seller:
        where_clause = "seller = %(seller)s"
        params["seller"] = seller
    else:
        where_clause = "1=1"

    stats = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as count
        FROM `tabListing`
        WHERE {where_clause}
        GROUP BY status
    """.format(where_clause=where_clause), params, as_dict=True)

    status_counts = {s.status: s.count for s in stats}

    total = frappe.db.count("Listing", filters)
    active = status_counts.get("Active", 0)
    draft = status_counts.get("Draft", 0)
    out_of_stock = status_counts.get("Out of Stock", 0)

    return {
        "total": total,
        "active": active,
        "draft": draft,
        "out_of_stock": out_of_stock,
        "pending_review": status_counts.get("Pending Review", 0),
        "paused": status_counts.get("Paused", 0),
        "suspended": status_counts.get("Suspended", 0),
        "rejected": status_counts.get("Rejected", 0),
        "archived": status_counts.get("Archived", 0),
        "status_breakdown": status_counts
    }
