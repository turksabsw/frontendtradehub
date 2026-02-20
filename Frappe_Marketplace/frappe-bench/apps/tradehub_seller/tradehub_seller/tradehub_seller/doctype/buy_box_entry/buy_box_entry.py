# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Buy Box Entry DocType for Trade Hub B2B Marketplace.

This module implements seller offer entries that compete for the Buy Box position
on product pages. The Buy Box represents the primary sales position where buyers
can quickly add items to cart.

Key features:
- Multi-tenant data isolation via Seller Profile's tenant
- Price, delivery time, rating, and stock scoring factors
- Winner determination based on composite score
- Automatic score calculation on save
- fetch_from pattern for product, seller, and tenant information

Buy Box Algorithm Factors:
- Price Score (40%): Lower prices score higher
- Delivery Score (25%): Faster delivery scores higher
- Rating Score (20%): Higher seller ratings score higher
- Stock Score (15%): Higher stock availability scores higher
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, now_datetime, getdate, nowdate


# Default scoring weights
DEFAULT_WEIGHTS = {
    "price": 0.40,
    "delivery": 0.25,
    "rating": 0.20,
    "stock": 0.15
}


class BuyBoxEntry(Document):
    """
    Buy Box Entry DocType for marketplace seller offers.

    Each Buy Box Entry represents a seller's offer for a specific product.
    Multiple sellers can have entries for the same product, and the Buy Box
    algorithm determines which seller's entry wins the primary position.
    """

    def before_insert(self):
        """Set defaults before inserting a new entry."""
        self.validate_unique_entry()
        self.update_stock_timestamp()

    def validate(self):
        """Validate Buy Box entry data before saving."""
        self.validate_sku_product()
        self.validate_seller()
        self.validate_pricing()
        self.validate_delivery()
        self.validate_stock()
        self.validate_tenant_isolation()
        self.sync_is_active_status()

    def on_update(self):
        """Actions after Buy Box entry is updated."""
        self.trigger_buy_box_recalculation()

    def on_trash(self):
        """Actions before Buy Box entry is deleted."""
        self.trigger_buy_box_recalculation_on_delete()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_unique_entry(self):
        """
        Validate that only one active entry exists per product-seller combination.

        A seller cannot have multiple active Buy Box entries for the same product.
        """
        if self.status in ("Active", "Inactive"):
            existing = frappe.db.get_value(
                "Buy Box Entry",
                {
                    "sku_product": self.sku_product,
                    "seller": self.seller,
                    "status": ("in", ["Active", "Inactive"]),
                    "name": ("!=", self.name or "")
                },
                "name"
            )

            if existing:
                frappe.throw(
                    _("An entry for this product-seller combination already exists: {0}").format(
                        existing
                    )
                )

    def validate_sku_product(self):
        """Validate SKU Product link exists and is valid."""
        if not self.sku_product:
            frappe.throw(_("SKU Product is required"))

        product_status = frappe.db.get_value(
            "SKU Product", self.sku_product, "status"
        )

        if product_status == "Archive":
            frappe.throw(
                _("Cannot create Buy Box entry for archived product {0}").format(
                    self.sku_product
                )
            )

        if product_status != "Active":
            frappe.msgprint(
                _("Warning: Product {0} is not in Active status").format(
                    self.sku_product
                ),
                indicator='orange',
                alert=True
            )

    def validate_seller(self):
        """Validate Seller Profile link exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        seller_data = frappe.db.get_value(
            "Seller Profile",
            self.seller,
            ["status", "verification_status"],
            as_dict=True
        )

        if not seller_data:
            frappe.throw(_("Seller Profile not found"))

        if seller_data.status != "Active":
            frappe.throw(
                _("Cannot create Buy Box entry for inactive seller")
            )

        if seller_data.verification_status != "Verified":
            frappe.msgprint(
                _("Warning: Seller {0} is not verified").format(self.seller),
                indicator='orange',
                alert=True
            )

    def validate_pricing(self):
        """Validate pricing fields."""
        if flt(self.offer_price) <= 0:
            frappe.throw(_("Offer Price must be greater than zero"))

        if not self.currency:
            self.currency = "TRY"

        if flt(self.min_order_quantity) <= 0:
            self.min_order_quantity = 1

        if flt(self.max_order_quantity) < 0:
            self.max_order_quantity = 0

        if self.max_order_quantity and flt(self.min_order_quantity) > flt(self.max_order_quantity):
            frappe.throw(
                _("Min Order Quantity cannot be greater than Max Order Quantity")
            )

    def validate_delivery(self):
        """Validate delivery fields."""
        if cint(self.delivery_days) <= 0:
            frappe.throw(_("Delivery Days must be greater than zero"))

        if cint(self.delivery_days) > 365:
            frappe.msgprint(
                _("Delivery time of {0} days seems unusually long").format(
                    self.delivery_days
                ),
                indicator='orange',
                alert=True
            )

    def validate_stock(self):
        """Validate stock fields."""
        if flt(self.stock_available) < 0:
            frappe.throw(_("Stock Available cannot be negative"))

        if flt(self.stock_available) == 0 and self.status == "Active":
            frappe.msgprint(
                _("Warning: Stock is zero for an active Buy Box entry"),
                indicator='orange',
                alert=True
            )

    def validate_tenant_isolation(self):
        """
        Validate that entry belongs to user's tenant.

        Inherits tenant from Seller Profile to ensure multi-tenant data isolation.
        """
        if not self.tenant:
            return

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access Buy Box entries in your tenant")
            )

    def sync_is_active_status(self):
        """Sync is_active checkbox with status field."""
        if self.status == "Active" and not self.is_active:
            self.is_active = 1
        elif self.status != "Active" and self.is_active:
            self.is_active = 0

    # =========================================================================
    # STOCK MANAGEMENT
    # =========================================================================

    def update_stock_timestamp(self):
        """Update the stock timestamp when stock changes."""
        self.last_stock_update = now_datetime()

    def update_stock(self, quantity):
        """
        Update stock availability.

        Args:
            quantity: New stock quantity
        """
        self.stock_available = flt(quantity)
        self.last_stock_update = now_datetime()
        self.save()

    # =========================================================================
    # BUY BOX RECALCULATION TRIGGERS
    # =========================================================================

    def trigger_buy_box_recalculation(self):
        """Trigger Buy Box recalculation for this product."""
        frappe.enqueue(
            "tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry.recalculate_buy_box_for_product",
            sku_product=self.sku_product,
            queue="short",
            deduplicate=True
        )

    def trigger_buy_box_recalculation_on_delete(self):
        """Trigger recalculation when an entry is deleted."""
        frappe.enqueue(
            "tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry.recalculate_buy_box_for_product",
            sku_product=self.sku_product,
            queue="short",
            deduplicate=True
        )


# =============================================================================
# BUY BOX SCORING FUNCTIONS
# =============================================================================


def calculate_price_score(offer_price, all_prices):
    """
    Calculate price score (0-100) based on competitiveness.

    Lower prices get higher scores. The lowest price gets 100,
    and scores decrease proportionally.

    Args:
        offer_price: The entry's offer price
        all_prices: List of all active offer prices for the product

    Returns:
        float: Score between 0 and 100
    """
    if not all_prices or len(all_prices) == 0:
        return 100.0

    min_price = min(all_prices)
    max_price = max(all_prices)

    if max_price == min_price:
        return 100.0

    # Linear scoring: lowest price = 100, highest price = 0
    score = 100 * (1 - (offer_price - min_price) / (max_price - min_price))
    return max(0, min(100, score))


def calculate_delivery_score(delivery_days, all_delivery_days):
    """
    Calculate delivery score (0-100) based on speed.

    Faster delivery gets higher scores.

    Args:
        delivery_days: The entry's delivery days
        all_delivery_days: List of all active delivery days for the product

    Returns:
        float: Score between 0 and 100
    """
    if not all_delivery_days or len(all_delivery_days) == 0:
        return 100.0

    min_days = min(all_delivery_days)
    max_days = max(all_delivery_days)

    if max_days == min_days:
        return 100.0

    # Linear scoring: fastest delivery = 100, slowest = 0
    score = 100 * (1 - (delivery_days - min_days) / (max_days - min_days))
    return max(0, min(100, score))


def calculate_rating_score(average_rating, total_reviews):
    """
    Calculate rating score (0-100) based on seller rating.

    Higher ratings with more reviews get higher scores.

    Args:
        average_rating: Seller's average rating (0-5)
        total_reviews: Total number of reviews

    Returns:
        float: Score between 0 and 100
    """
    if not average_rating or average_rating <= 0:
        return 50.0  # Neutral score for unrated sellers

    # Base score from rating (0-5 scale to 0-100)
    base_score = (average_rating / 5) * 100

    # Confidence boost based on review count (logarithmic)
    import math
    confidence_factor = min(1.0, math.log10(total_reviews + 1) / 3)

    # Weighted score: confidence increases weight toward actual rating
    final_score = 50 + (base_score - 50) * confidence_factor

    return max(0, min(100, final_score))


def calculate_stock_score(stock_available, all_stock):
    """
    Calculate stock score (0-100) based on availability.

    Higher stock availability gets higher scores.

    Args:
        stock_available: The entry's stock quantity
        all_stock: List of all active stock quantities for the product

    Returns:
        float: Score between 0 and 100
    """
    if stock_available <= 0:
        return 0.0

    if not all_stock or len(all_stock) == 0:
        return 100.0

    max_stock = max(all_stock)

    if max_stock <= 0:
        return 100.0

    # Logarithmic scoring to prevent massive stock from dominating
    import math
    stock_ratio = math.log10(stock_available + 1) / math.log10(max_stock + 1)
    score = stock_ratio * 100

    return max(0, min(100, score))


def calculate_composite_score(price_score, delivery_score, rating_score, stock_score, weights=None):
    """
    Calculate composite Buy Box score from individual scores.

    Args:
        price_score: Price competitiveness score (0-100)
        delivery_score: Delivery speed score (0-100)
        rating_score: Seller rating score (0-100)
        stock_score: Stock availability score (0-100)
        weights: Optional custom weights dict

    Returns:
        float: Composite score (0-100)
    """
    w = weights or DEFAULT_WEIGHTS

    score = (
        w.get("price", 0.40) * price_score +
        w.get("delivery", 0.25) * delivery_score +
        w.get("rating", 0.20) * rating_score +
        w.get("stock", 0.15) * stock_score
    )

    return round(score, 2)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def recalculate_buy_box_for_product(sku_product):
    """
    Recalculate Buy Box scores for all entries of a product.

    This function:
    1. Gets all active entries for the product
    2. Calculates individual scores for each factor
    3. Calculates composite scores
    4. Determines the winner
    5. Updates all entries

    Args:
        sku_product: The SKU Product name

    Returns:
        dict: Recalculation result with winner info
    """
    # Get all active entries
    entries = frappe.get_all(
        "Buy Box Entry",
        filters={
            "sku_product": sku_product,
            "status": "Active"
        },
        fields=["name", "offer_price", "delivery_days", "stock_available",
                "seller_average_rating", "seller_total_reviews", "is_winner"]
    )

    if not entries:
        return {"message": _("No active Buy Box entries for this product")}

    # Collect all values for relative scoring
    all_prices = [flt(e.offer_price) for e in entries if flt(e.offer_price) > 0]
    all_delivery_days = [cint(e.delivery_days) for e in entries if cint(e.delivery_days) > 0]
    all_stock = [flt(e.stock_available) for e in entries]

    # Calculate scores for each entry
    scored_entries = []
    for entry in entries:
        price_score = calculate_price_score(flt(entry.offer_price), all_prices)
        delivery_score = calculate_delivery_score(cint(entry.delivery_days), all_delivery_days)
        rating_score = calculate_rating_score(
            flt(entry.seller_average_rating),
            cint(entry.seller_total_reviews)
        )
        stock_score = calculate_stock_score(flt(entry.stock_available), all_stock)

        composite_score = calculate_composite_score(
            price_score, delivery_score, rating_score, stock_score
        )

        scored_entries.append({
            "name": entry.name,
            "price_score": round(price_score, 2),
            "delivery_score": round(delivery_score, 2),
            "rating_score": round(rating_score, 2),
            "stock_score": round(stock_score, 2),
            "buy_box_score": composite_score,
            "was_winner": entry.is_winner
        })

    # Sort by score (highest first)
    scored_entries.sort(key=lambda x: x["buy_box_score"], reverse=True)

    # Determine winner (highest score)
    winner_name = scored_entries[0]["name"] if scored_entries else None

    # Update all entries
    now = now_datetime()
    for entry_data in scored_entries:
        is_winner = 1 if entry_data["name"] == winner_name else 0

        update_values = {
            "price_score": entry_data["price_score"],
            "delivery_score": entry_data["delivery_score"],
            "rating_score": entry_data["rating_score"],
            "stock_score": entry_data["stock_score"],
            "buy_box_score": entry_data["buy_box_score"],
            "is_winner": is_winner,
            "last_score_update": now
        }

        # Set winner_since if this is a new winner
        if is_winner and not entry_data["was_winner"]:
            update_values["winner_since"] = now

        # Clear winner_since if no longer winner
        if not is_winner and entry_data["was_winner"]:
            update_values["winner_since"] = None

        frappe.db.set_value("Buy Box Entry", entry_data["name"], update_values)

    frappe.db.commit()

    return {
        "success": True,
        "winner": winner_name,
        "entries_processed": len(scored_entries),
        "message": _("Buy Box recalculated successfully")
    }


@frappe.whitelist()
def get_buy_box_winner(sku_product):
    """
    Get the current Buy Box winner for a product.

    Args:
        sku_product: The SKU Product name

    Returns:
        dict: Winner entry details or None
    """
    winner = frappe.get_all(
        "Buy Box Entry",
        filters={
            "sku_product": sku_product,
            "status": "Active",
            "is_winner": 1
        },
        fields=[
            "name", "seller", "seller_name", "offer_price", "currency",
            "delivery_days", "stock_available", "buy_box_score",
            "seller_average_rating", "winner_since"
        ],
        limit=1
    )

    return winner[0] if winner else None


@frappe.whitelist()
def get_product_buy_box_entries(sku_product, include_inactive=False):
    """
    Get all Buy Box entries for a product.

    Args:
        sku_product: The SKU Product name
        include_inactive: Whether to include inactive entries

    Returns:
        list: List of Buy Box entries sorted by score
    """
    filters = {"sku_product": sku_product}

    if not include_inactive:
        filters["status"] = "Active"

    entries = frappe.get_all(
        "Buy Box Entry",
        filters=filters,
        fields=[
            "name", "seller", "seller_name", "offer_price", "currency",
            "delivery_days", "stock_available", "buy_box_score",
            "is_winner", "status", "seller_average_rating",
            "price_score", "delivery_score", "rating_score", "stock_score"
        ],
        order_by="buy_box_score desc"
    )

    return entries


@frappe.whitelist()
def get_seller_buy_box_entries(seller, sku_product=None):
    """
    Get all Buy Box entries for a seller.

    Args:
        seller: The Seller Profile name
        sku_product: Optional product filter

    Returns:
        list: List of Buy Box entries for the seller
    """
    filters = {"seller": seller}

    if sku_product:
        filters["sku_product"] = sku_product

    entries = frappe.get_all(
        "Buy Box Entry",
        filters=filters,
        fields=[
            "name", "sku_product", "product_name", "product_sku_code",
            "offer_price", "currency", "delivery_days", "stock_available",
            "buy_box_score", "is_winner", "status"
        ],
        order_by="is_winner desc, buy_box_score desc"
    )

    return entries


@frappe.whitelist()
def create_buy_box_entry(sku_product, seller, offer_price, delivery_days,
                          stock_available, currency="TRY", **kwargs):
    """
    Create a new Buy Box entry.

    Args:
        sku_product: The SKU Product name
        seller: The Seller Profile name
        offer_price: The offer price
        delivery_days: Estimated delivery days
        stock_available: Available stock quantity
        currency: Currency code (default TRY)
        **kwargs: Additional optional fields

    Returns:
        dict: Created entry info
    """
    doc = frappe.new_doc("Buy Box Entry")
    doc.sku_product = sku_product
    doc.seller = seller
    doc.offer_price = flt(offer_price)
    doc.delivery_days = cint(delivery_days)
    doc.stock_available = flt(stock_available)
    doc.currency = currency

    # Set optional fields
    for field in ["min_order_quantity", "max_order_quantity", "delivery_location",
                  "origin_country", "shipping_method", "price_includes_shipping",
                  "is_stock_guaranteed"]:
        if field in kwargs:
            setattr(doc, field, kwargs[field])

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Buy Box entry created successfully")
    }


@frappe.whitelist()
def update_buy_box_entry(name, **kwargs):
    """
    Update a Buy Box entry.

    Args:
        name: The Buy Box Entry name
        **kwargs: Fields to update

    Returns:
        dict: Update result
    """
    doc = frappe.get_doc("Buy Box Entry", name)

    # Update allowed fields
    allowed_fields = [
        "offer_price", "delivery_days", "stock_available", "currency",
        "min_order_quantity", "max_order_quantity", "delivery_location",
        "origin_country", "shipping_method", "price_includes_shipping",
        "is_stock_guaranteed", "status", "internal_notes"
    ]

    for field in allowed_fields:
        if field in kwargs:
            setattr(doc, field, kwargs[field])

    doc.save()

    return {
        "success": True,
        "message": _("Buy Box entry updated successfully")
    }


@frappe.whitelist()
def activate_entry(name):
    """
    Activate a Buy Box entry.

    Args:
        name: The Buy Box Entry name

    Returns:
        dict: Activation result
    """
    doc = frappe.get_doc("Buy Box Entry", name)

    if doc.status == "Active":
        return {"success": True, "message": _("Entry is already active")}

    doc.status = "Active"
    doc.is_active = 1
    doc.save()

    return {
        "success": True,
        "message": _("Buy Box entry activated successfully")
    }


@frappe.whitelist()
def deactivate_entry(name):
    """
    Deactivate a Buy Box entry.

    Args:
        name: The Buy Box Entry name

    Returns:
        dict: Deactivation result
    """
    doc = frappe.get_doc("Buy Box Entry", name)

    if doc.status == "Inactive":
        return {"success": True, "message": _("Entry is already inactive")}

    doc.status = "Inactive"
    doc.is_active = 0

    # Clear winner status
    if doc.is_winner:
        doc.is_winner = 0
        doc.winner_since = None

    doc.save()

    return {
        "success": True,
        "message": _("Buy Box entry deactivated successfully")
    }


@frappe.whitelist()
def get_buy_box_statistics(sku_product=None, seller=None):
    """
    Get Buy Box statistics.

    Args:
        sku_product: Optional product filter
        seller: Optional seller filter

    Returns:
        dict: Statistics including total entries, winners, average scores
    """
    filters = {"status": "Active"}

    if sku_product:
        filters["sku_product"] = sku_product
    if seller:
        filters["seller"] = seller

    entries = frappe.get_all(
        "Buy Box Entry",
        filters=filters,
        fields=["name", "is_winner", "buy_box_score", "offer_price"]
    )

    if not entries:
        return {
            "total_entries": 0,
            "total_winners": 0,
            "average_score": 0,
            "average_price": 0
        }

    total_entries = len(entries)
    total_winners = sum(1 for e in entries if e.is_winner)
    average_score = sum(flt(e.buy_box_score) for e in entries) / total_entries
    average_price = sum(flt(e.offer_price) for e in entries) / total_entries

    return {
        "total_entries": total_entries,
        "total_winners": total_winners,
        "average_score": round(average_score, 2),
        "average_price": round(average_price, 2)
    }


@frappe.whitelist()
def recalculate_all_buy_boxes():
    """
    Recalculate Buy Box for all products with active entries.

    This should be called by a scheduled job.

    Returns:
        dict: Summary of recalculations
    """
    products = frappe.get_all(
        "Buy Box Entry",
        filters={"status": "Active"},
        fields=["sku_product"],
        group_by="sku_product"
    )

    recalculated = 0
    for product in products:
        try:
            recalculate_buy_box_for_product(product.sku_product)
            recalculated += 1
        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=f"Buy Box Recalculation Error: {product.sku_product}"
            )

    return {
        "success": True,
        "products_recalculated": recalculated,
        "message": _("Buy Box recalculation completed")
    }
