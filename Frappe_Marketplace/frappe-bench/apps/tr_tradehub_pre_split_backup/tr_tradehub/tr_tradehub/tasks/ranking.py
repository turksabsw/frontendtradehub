# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Product Ranking Calculation Tasks

This module provides scheduled tasks for calculating and updating product
ranking scores in the marketplace. The ranking algorithm considers multiple
factors including sales performance, user engagement, quality metrics, and
seller reputation.

Scheduled via hooks.py:
- recalculate_all_rankings: Daily at 3 AM
- recalculate_category_rankings: Every 4 hours
- update_trending_products: Every hour
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_days, get_datetime, flt, cint
from typing import Dict, List, Optional, Tuple
import math
from datetime import datetime, timedelta


def recalculate_all_rankings():
    """
    Recalculate ranking scores for all active listings.
    This is a heavy operation, typically run daily during off-peak hours.
    """
    frappe.logger().info("Starting full ranking recalculation...")

    # Get all active listings
    listings = frappe.get_all(
        "Listing",
        filters={
            "status": "Active",
            "is_visible": 1,
            "docstatus": ["!=", 2]
        },
        fields=["name", "category", "tenant"],
        limit=0  # No limit - process all
    )

    total = len(listings)
    processed = 0
    errors = 0

    frappe.logger().info(f"Processing {total} listings for ranking...")

    for listing in listings:
        try:
            calculate_listing_ranking(listing.name)
            processed += 1

            # Commit every 100 listings to avoid long transactions
            if processed % 100 == 0:
                frappe.db.commit()
                frappe.logger().info(f"Ranking progress: {processed}/{total}")

        except Exception as e:
            errors += 1
            frappe.log_error(
                f"Failed to calculate ranking for {listing.name}: {str(e)}",
                "Ranking Calculation Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Ranking recalculation complete. Processed: {processed}, Errors: {errors}"
    )

    return {
        "total": total,
        "processed": processed,
        "errors": errors
    }


def recalculate_category_rankings(category: str = None):
    """
    Recalculate rankings for a specific category or all categories.
    More frequent than full recalculation, focuses on category-relative rankings.

    Args:
        category: Optional category to process. If None, processes all categories.
    """
    if category:
        categories = [{"name": category}]
    else:
        categories = frappe.get_all("Category", filters={"is_active": 1})

    for cat in categories:
        try:
            _recalculate_category_ranking(cat.name)
        except Exception as e:
            frappe.log_error(
                f"Failed to recalculate rankings for category {cat.name}: {str(e)}",
                "Category Ranking Error"
            )

    frappe.db.commit()


def _recalculate_category_ranking(category: str):
    """Internal: Recalculate rankings for a single category"""
    listings = frappe.get_all(
        "Listing",
        filters={
            "category": category,
            "status": "Active",
            "is_visible": 1
        },
        fields=["name"]
    )

    for listing in listings:
        calculate_listing_ranking(listing.name)


def update_trending_products():
    """
    Update rankings for products showing trending behavior.
    Run frequently (hourly) to capture real-time trends.
    """
    # Find products with recent activity (views, orders, wishlists in last 24h)
    # This would typically query from an analytics/events table
    # For now, we update recently modified listings

    recently_active = frappe.get_all(
        "Listing",
        filters={
            "status": "Active",
            "is_visible": 1,
            "modified": [">=", add_days(now_datetime(), -1)]
        },
        fields=["name"],
        limit=500
    )

    for listing in recently_active:
        try:
            calculate_listing_ranking(listing.name)
        except Exception:
            pass  # Don't fail the whole batch for one error

    frappe.db.commit()


def calculate_listing_ranking(listing_name: str) -> float:
    """
    Calculate and update the ranking score for a single listing.

    The ranking algorithm uses a weighted combination of:
    1. Performance metrics (sales, views, conversion rate, CTR)
    2. Engagement metrics (wishlists, reviews, ratings)
    3. Quality metrics (quality score, seller score)
    4. Boosts (featured, bestseller, new arrival, sale)
    5. Penalties (out of stock, low rating)

    Args:
        listing_name: Name of the listing to rank

    Returns:
        float: The calculated ranking score (0-100)
    """
    listing = frappe.get_doc("Listing", listing_name)

    # Get appropriate ranking config
    config = _get_ranking_config(listing.category, listing.tenant)

    # Calculate component scores
    performance_score = _calculate_performance_score(listing, config)
    engagement_score = _calculate_engagement_score(listing, config)
    quality_score = _calculate_quality_score(listing, config)
    boost_score = _calculate_boost_score(listing, config)
    penalty_score = _calculate_penalty_score(listing, config)

    # Combine scores
    base_score = performance_score + engagement_score + quality_score
    final_score = base_score + boost_score + penalty_score

    # Clamp to 0-100 range
    final_score = max(0, min(100, final_score))

    # Calculate conversion rate and CTR for storage
    conversion_rate = _calculate_conversion_rate(listing)
    click_through_rate = _calculate_ctr(listing)

    # Get seller score
    seller_score = _get_seller_score(listing.seller)

    # Update listing with new ranking data
    frappe.db.set_value(
        "Listing",
        listing_name,
        {
            "ranking_score": flt(final_score, 4),
            "ranking_updated_at": now_datetime(),
            "conversion_rate": flt(conversion_rate, 2),
            "click_through_rate": flt(click_through_rate, 2),
            "seller_score": flt(seller_score, 2)
        },
        update_modified=False
    )

    return final_score


def _get_ranking_config(category: str = None, tenant: str = None) -> Dict:
    """Get ranking configuration with fallbacks"""
    from tr_tradehub.tr_tradehub.doctype.ranking_weight_config.ranking_weight_config import (
        get_ranking_config
    )

    config = get_ranking_config(category, tenant)

    if not config:
        # Return default weights if no config exists
        return {
            "sales_weight": 25,
            "view_weight": 10,
            "conversion_weight": 15,
            "ctr_weight": 5,
            "wishlist_weight": 3,
            "review_weight": 5,
            "rating_weight": 12,
            "quality_score_weight": 10,
            "seller_score_weight": 10,
            "recency_weight": 3,
            "stock_weight": 2,
            "featured_boost": 15,
            "bestseller_boost": 8,
            "new_arrival_boost": 5,
            "sale_boost": 3,
            "new_listing_boost_days": 14,
            "new_listing_boost_amount": 10,
            "out_of_stock_penalty": -25,
            "low_rating_penalty": -15,
            "use_time_decay": 1,
            "decay_half_life_days": 30,
            "normalize_scores": 1,
            "min_orders_for_conversion": 5
        }

    return config


def _calculate_performance_score(listing, config: Dict) -> float:
    """Calculate performance-based score component"""
    score = 0

    # Sales score (normalized to 0-100)
    sales_score = _normalize_metric(
        listing.order_count or 0,
        max_value=100,  # Listings with 100+ orders get full score
        method="log"
    )
    score += sales_score * (config.get("sales_weight", 25) / 100)

    # Views score (normalized)
    views_score = _normalize_metric(
        listing.view_count or 0,
        max_value=10000,
        method="log"
    )
    score += views_score * (config.get("view_weight", 10) / 100)

    # Conversion rate score
    conversion = _calculate_conversion_rate(listing)
    conversion_score = min(100, conversion * 10)  # 10% conversion = full score
    score += conversion_score * (config.get("conversion_weight", 15) / 100)

    # CTR score
    ctr = _calculate_ctr(listing)
    ctr_score = min(100, ctr * 5)  # 20% CTR = full score
    score += ctr_score * (config.get("ctr_weight", 5) / 100)

    return score


def _calculate_engagement_score(listing, config: Dict) -> float:
    """Calculate engagement-based score component"""
    score = 0

    # Wishlist score
    wishlist_score = _normalize_metric(
        listing.wishlist_count or 0,
        max_value=500,
        method="log"
    )
    score += wishlist_score * (config.get("wishlist_weight", 3) / 100)

    # Review count score
    review_score = _normalize_metric(
        listing.review_count or 0,
        max_value=50,
        method="log"
    )
    score += review_score * (config.get("review_weight", 5) / 100)

    # Rating score (already 0-5, convert to 0-100)
    rating = listing.average_rating or 0
    rating_score = (rating / 5) * 100 if rating > 0 else 50  # Default to neutral
    score += rating_score * (config.get("rating_weight", 12) / 100)

    return score


def _calculate_quality_score(listing, config: Dict) -> float:
    """Calculate quality-based score component"""
    score = 0

    # Quality score (already 0-100)
    quality = listing.quality_score or 50  # Default to neutral
    score += quality * (config.get("quality_score_weight", 10) / 100)

    # Seller score
    seller_score = _get_seller_score(listing.seller)
    score += seller_score * (config.get("seller_score_weight", 10) / 100)

    # Recency score (based on last_sold_at)
    recency_score = _calculate_recency_score(listing.last_sold_at)
    score += recency_score * (config.get("recency_weight", 3) / 100)

    # Stock availability score
    stock_score = _calculate_stock_score(listing)
    score += stock_score * (config.get("stock_weight", 2) / 100)

    return score


def _calculate_boost_score(listing, config: Dict) -> float:
    """Calculate boost additions"""
    boost = 0

    if listing.is_featured:
        boost += config.get("featured_boost", 15)

    if listing.is_best_seller:
        boost += config.get("bestseller_boost", 8)

    if listing.is_new_arrival:
        boost += config.get("new_arrival_boost", 5)

    if listing.is_on_sale:
        boost += config.get("sale_boost", 3)

    # New listing boost
    new_listing_days = config.get("new_listing_boost_days", 14)
    new_listing_boost = config.get("new_listing_boost_amount", 10)

    if listing.published_at:
        days_since_publish = (now_datetime() - get_datetime(listing.published_at)).days
        if days_since_publish <= new_listing_days:
            # Linear decay of new listing boost
            decay_factor = 1 - (days_since_publish / new_listing_days)
            boost += new_listing_boost * decay_factor

    return boost


def _calculate_penalty_score(listing, config: Dict) -> float:
    """Calculate penalty deductions"""
    penalty = 0

    # Out of stock penalty
    available_qty = flt(listing.available_qty or 0)
    if available_qty <= 0 and not listing.allow_backorders:
        penalty += config.get("out_of_stock_penalty", -25)

    # Low rating penalty (below 3 stars with significant reviews)
    if (listing.average_rating or 0) < 3 and (listing.review_count or 0) >= 5:
        penalty += config.get("low_rating_penalty", -15)

    return penalty


def _calculate_conversion_rate(listing) -> float:
    """Calculate conversion rate (orders / views * 100)"""
    views = listing.view_count or 0
    orders = listing.order_count or 0

    if views < 10:  # Not enough data
        return 0

    return (orders / views) * 100


def _calculate_ctr(listing) -> float:
    """Calculate click-through rate (clicks / impressions * 100)"""
    # This would typically come from an analytics table
    # For now, estimate from views as a proxy for clicks
    views = listing.view_count or 0

    # Assume impressions are 10x views (rough estimate)
    # In a real system, this would be tracked separately
    impressions = views * 10

    if impressions < 100:
        return 0

    return (views / impressions) * 100


def _get_seller_score(seller_name: str) -> float:
    """Get seller's performance score"""
    if not seller_name:
        return 50  # Neutral score

    # Try to get from Seller Score DocType
    seller_score = frappe.db.get_value(
        "Seller Score",
        {"seller": seller_name},
        "overall_score"
    )

    if seller_score is not None:
        return flt(seller_score)

    # Fallback: try to get from Seller KPI
    kpi_score = frappe.db.get_value(
        "Seller KPI",
        {"seller_profile": seller_name},
        "overall_score"
    )

    if kpi_score is not None:
        return flt(kpi_score)

    return 50  # Neutral if no score available


def _calculate_recency_score(last_sold_at) -> float:
    """Calculate score based on recency of last sale"""
    if not last_sold_at:
        return 30  # Low score for never sold

    days_since_sale = (now_datetime() - get_datetime(last_sold_at)).days

    if days_since_sale <= 1:
        return 100
    elif days_since_sale <= 7:
        return 90
    elif days_since_sale <= 30:
        return 70
    elif days_since_sale <= 90:
        return 50
    elif days_since_sale <= 180:
        return 30
    else:
        return 10


def _calculate_stock_score(listing) -> float:
    """Calculate score based on stock availability"""
    available = flt(listing.available_qty or 0)
    threshold = flt(listing.low_stock_threshold or 5)

    if available <= 0:
        return 0 if not listing.allow_backorders else 50
    elif available <= threshold:
        return 30  # Low stock warning
    elif available <= threshold * 3:
        return 70  # Moderate stock
    else:
        return 100  # Well stocked


def _normalize_metric(value: float, max_value: float, method: str = "linear") -> float:
    """
    Normalize a metric value to 0-100 scale.

    Args:
        value: The raw metric value
        max_value: The value that should map to 100
        method: 'linear' or 'log' normalization

    Returns:
        float: Normalized value (0-100)
    """
    if value <= 0:
        return 0

    if method == "log":
        # Logarithmic normalization - good for metrics with power law distributions
        # like views, sales, etc.
        log_value = math.log10(value + 1)
        log_max = math.log10(max_value + 1)
        return min(100, (log_value / log_max) * 100)
    else:
        # Linear normalization
        return min(100, (value / max_value) * 100)


# API Endpoints

@frappe.whitelist()
def recalculate_ranking_for_listing(listing_name: str) -> Dict:
    """
    API endpoint to recalculate ranking for a specific listing.

    Args:
        listing_name: The listing to recalculate

    Returns:
        dict: Result with new ranking score
    """
    if not frappe.db.exists("Listing", listing_name):
        return {"success": False, "message": _("Listing not found")}

    try:
        score = calculate_listing_ranking(listing_name)
        frappe.db.commit()
        return {
            "success": True,
            "listing": listing_name,
            "ranking_score": score
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_top_ranked_listings(
    category: str = None,
    tenant: str = None,
    limit: int = 20
) -> List[Dict]:
    """
    Get top-ranked listings, optionally filtered by category or tenant.

    Args:
        category: Optional category filter
        tenant: Optional tenant filter
        limit: Maximum number of results

    Returns:
        list: Top-ranked listings with their scores
    """
    filters = {
        "status": "Active",
        "is_visible": 1,
        "docstatus": ["!=", 2]
    }

    if category:
        filters["category"] = category
    if tenant:
        filters["tenant"] = tenant

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "title", "seller", "category", "selling_price",
            "ranking_score", "average_rating", "review_count",
            "order_count", "is_featured", "is_best_seller"
        ],
        order_by="ranking_score desc",
        limit=cint(limit)
    )

    return listings


@frappe.whitelist()
def trigger_full_ranking_recalculation() -> Dict:
    """
    API endpoint to trigger a full ranking recalculation.
    This should be called with caution as it can be resource-intensive.

    Returns:
        dict: Result summary
    """
    # Check permissions
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("You don't have permission to recalculate rankings"))

    result = recalculate_all_rankings()
    return result
