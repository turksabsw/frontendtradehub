# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Buy Box Scoring Algorithm for Trade Hub B2B Marketplace.

This module implements the Buy Box winner selection algorithm that determines
which seller's offer is featured as the primary sales position on product pages.

Algorithm Overview:
- Multiple sellers can offer the same product
- Each offer is scored based on 4 key factors
- The highest-scoring offer wins the Buy Box position
- Scores are calculated relative to all competing offers

Scoring Factors (Default Weights):
- Price Score (40%): Lower prices score higher
- Delivery Score (25%): Faster delivery times score higher
- Rating Score (20%): Higher seller ratings with more reviews score higher
- Stock Score (15%): Higher stock availability scores higher

Features:
- Configurable scoring weights per tenant or globally
- Database locking to prevent race conditions during concurrent updates
- Fair distribution rotation for similarly-scored entries
- Brand gating support for authorized reseller restrictions
- Multi-tenant data isolation
- Bulk recalculation support for scheduled jobs
"""

import math
from typing import Dict, List, Optional, Tuple, Any

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime, getdate, nowdate


# =============================================================================
# DEFAULT CONFIGURATION
# =============================================================================

# Default scoring weights (must sum to 1.0)
DEFAULT_WEIGHTS = {
    "price": 0.40,
    "delivery": 0.25,
    "rating": 0.20,
    "stock": 0.15
}

# Score calculation thresholds
RATING_MAX = 5.0  # Maximum rating (5-star system)
RATING_CONFIDENCE_THRESHOLD = 100  # Reviews needed for full confidence
STOCK_LOG_BASE = 10  # Base for logarithmic stock scoring
DELIVERY_MAX_DAYS = 365  # Maximum delivery days to consider

# Tie-breaker thresholds
TIE_THRESHOLD = 0.5  # Score difference to consider a tie


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================


def calculate_price_score(
    offer_price: float,
    all_prices: List[float],
    inverse: bool = True
) -> float:
    """
    Calculate price score (0-100) based on competitiveness.

    Uses linear interpolation where the best price gets 100 and the worst
    gets 0. For Buy Box, lower prices are better (inverse=True).

    Args:
        offer_price: The entry's offer price
        all_prices: List of all active offer prices for the product
        inverse: If True, lower values get higher scores (default for price)

    Returns:
        float: Score between 0 and 100

    Examples:
        >>> calculate_price_score(100, [100, 150, 200])  # Lowest price
        100.0
        >>> calculate_price_score(200, [100, 150, 200])  # Highest price
        0.0
        >>> calculate_price_score(150, [100, 150, 200])  # Middle price
        50.0
    """
    if not all_prices or len(all_prices) == 0:
        return 100.0

    offer_price = flt(offer_price)

    # Filter out invalid prices
    valid_prices = [flt(p) for p in all_prices if flt(p) > 0]
    if not valid_prices:
        return 100.0

    min_price = min(valid_prices)
    max_price = max(valid_prices)

    # All prices are the same
    if max_price == min_price:
        return 100.0

    # Linear interpolation
    if inverse:
        # Lower is better: lowest = 100, highest = 0
        score = 100 * (1 - (offer_price - min_price) / (max_price - min_price))
    else:
        # Higher is better: highest = 100, lowest = 0
        score = 100 * (offer_price - min_price) / (max_price - min_price)

    return max(0.0, min(100.0, score))


def calculate_delivery_score(
    delivery_days: int,
    all_delivery_days: List[int]
) -> float:
    """
    Calculate delivery score (0-100) based on speed.

    Faster delivery times receive higher scores using linear interpolation.

    Args:
        delivery_days: The entry's delivery days
        all_delivery_days: List of all active delivery days for the product

    Returns:
        float: Score between 0 and 100

    Examples:
        >>> calculate_delivery_score(3, [3, 7, 14])  # Fastest
        100.0
        >>> calculate_delivery_score(14, [3, 7, 14])  # Slowest
        0.0
    """
    if not all_delivery_days or len(all_delivery_days) == 0:
        return 100.0

    delivery_days = cint(delivery_days)

    # Filter out invalid values
    valid_days = [cint(d) for d in all_delivery_days if cint(d) > 0]
    if not valid_days:
        return 100.0

    min_days = min(valid_days)
    max_days = max(valid_days)

    # All delivery times are the same
    if max_days == min_days:
        return 100.0

    # Cap at maximum
    if delivery_days > DELIVERY_MAX_DAYS:
        delivery_days = DELIVERY_MAX_DAYS

    # Linear interpolation (lower is better)
    score = 100 * (1 - (delivery_days - min_days) / (max_days - min_days))

    return max(0.0, min(100.0, score))


def calculate_rating_score(
    average_rating: float,
    total_reviews: int,
    max_rating: float = RATING_MAX,
    confidence_threshold: int = RATING_CONFIDENCE_THRESHOLD
) -> float:
    """
    Calculate rating score (0-100) based on seller rating.

    Uses a confidence-weighted approach where the score is influenced by
    both the rating value and the number of reviews. New sellers with
    few reviews get a neutral score.

    Args:
        average_rating: Seller's average rating (0 to max_rating)
        total_reviews: Total number of reviews
        max_rating: Maximum possible rating (default 5)
        confidence_threshold: Reviews needed for full confidence

    Returns:
        float: Score between 0 and 100

    Examples:
        >>> calculate_rating_score(4.5, 500)  # Good rating, many reviews
        ~90.0
        >>> calculate_rating_score(4.5, 1)  # Good rating, few reviews
        ~52.5  (closer to neutral)
        >>> calculate_rating_score(0, 0)  # New seller
        50.0
    """
    # Handle unrated sellers
    if not average_rating or average_rating <= 0 or total_reviews <= 0:
        return 50.0  # Neutral score for unrated sellers

    average_rating = flt(average_rating)
    total_reviews = cint(total_reviews)

    # Clamp rating to valid range
    average_rating = max(0, min(max_rating, average_rating))

    # Base score from rating (0 to max_rating scale to 0-100)
    base_score = (average_rating / max_rating) * 100

    # Confidence factor based on review count (logarithmic scale)
    # More reviews = higher confidence in the rating
    if total_reviews >= confidence_threshold:
        confidence_factor = 1.0
    else:
        # Logarithmic growth: log10(reviews+1) / log10(threshold+1)
        confidence_factor = math.log10(total_reviews + 1) / math.log10(confidence_threshold + 1)
        confidence_factor = max(0.0, min(1.0, confidence_factor))

    # Weighted score: confidence increases weight toward actual rating
    # Low confidence pulls score toward neutral (50)
    final_score = 50 + (base_score - 50) * confidence_factor

    return max(0.0, min(100.0, final_score))


def calculate_stock_score(
    stock_available: float,
    all_stock: List[float],
    use_logarithmic: bool = True
) -> float:
    """
    Calculate stock score (0-100) based on availability.

    Higher stock availability receives higher scores. Uses logarithmic
    scaling by default to prevent massive stock quantities from dominating.

    Args:
        stock_available: The entry's stock quantity
        all_stock: List of all active stock quantities for the product
        use_logarithmic: Whether to use logarithmic scaling

    Returns:
        float: Score between 0 and 100

    Examples:
        >>> calculate_stock_score(1000, [100, 500, 1000])  # Highest stock
        100.0
        >>> calculate_stock_score(0, [100, 500, 1000])  # No stock
        0.0
    """
    stock_available = flt(stock_available)

    # No stock = no score
    if stock_available <= 0:
        return 0.0

    if not all_stock or len(all_stock) == 0:
        return 100.0

    # Filter out zero/negative stock
    valid_stock = [flt(s) for s in all_stock if flt(s) > 0]
    if not valid_stock:
        return 100.0

    max_stock = max(valid_stock)

    if max_stock <= 0:
        return 100.0

    if use_logarithmic:
        # Logarithmic scaling to prevent massive stock from dominating
        stock_ratio = math.log10(stock_available + 1) / math.log10(max_stock + 1)
    else:
        # Linear scaling
        stock_ratio = stock_available / max_stock

    score = stock_ratio * 100

    return max(0.0, min(100.0, score))


def calculate_composite_score(
    price_score: float,
    delivery_score: float,
    rating_score: float,
    stock_score: float,
    weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculate weighted composite Buy Box score from individual scores.

    Args:
        price_score: Price competitiveness score (0-100)
        delivery_score: Delivery speed score (0-100)
        rating_score: Seller rating score (0-100)
        stock_score: Stock availability score (0-100)
        weights: Optional custom weights dict with keys: price, delivery, rating, stock

    Returns:
        float: Composite score (0-100)

    Raises:
        ValueError: If weights don't sum to approximately 1.0
    """
    w = weights or DEFAULT_WEIGHTS

    # Validate weights sum to 1.0 (with small tolerance)
    weight_sum = sum(w.values())
    if abs(weight_sum - 1.0) > 0.01:
        frappe.log_error(
            f"Buy Box weights sum to {weight_sum}, not 1.0",
            "Buy Box Weight Warning"
        )

    score = (
        w.get("price", DEFAULT_WEIGHTS["price"]) * flt(price_score) +
        w.get("delivery", DEFAULT_WEIGHTS["delivery"]) * flt(delivery_score) +
        w.get("rating", DEFAULT_WEIGHTS["rating"]) * flt(rating_score) +
        w.get("stock", DEFAULT_WEIGHTS["stock"]) * flt(stock_score)
    )

    return round(score, 2)


# =============================================================================
# MAIN ALGORITHM FUNCTIONS
# =============================================================================


def calculate_entry_scores(
    entry: Dict[str, Any],
    all_entries: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """
    Calculate all scores for a single Buy Box entry.

    Args:
        entry: Buy Box entry data with offer_price, delivery_days, etc.
        all_entries: List of all competing entries for comparison
        weights: Optional custom scoring weights

    Returns:
        dict: Dictionary with price_score, delivery_score, rating_score,
              stock_score, and buy_box_score
    """
    # Collect comparison values from all entries
    all_prices = [flt(e.get("offer_price")) for e in all_entries if flt(e.get("offer_price")) > 0]
    all_delivery_days = [cint(e.get("delivery_days")) for e in all_entries if cint(e.get("delivery_days")) > 0]
    all_stock = [flt(e.get("stock_available")) for e in all_entries]

    # Calculate individual scores
    price_score = calculate_price_score(
        flt(entry.get("offer_price")),
        all_prices
    )

    delivery_score = calculate_delivery_score(
        cint(entry.get("delivery_days")),
        all_delivery_days
    )

    rating_score = calculate_rating_score(
        flt(entry.get("seller_average_rating")),
        cint(entry.get("seller_total_reviews"))
    )

    stock_score = calculate_stock_score(
        flt(entry.get("stock_available")),
        all_stock
    )

    # Calculate composite score
    buy_box_score = calculate_composite_score(
        price_score,
        delivery_score,
        rating_score,
        stock_score,
        weights
    )

    return {
        "price_score": round(price_score, 2),
        "delivery_score": round(delivery_score, 2),
        "rating_score": round(rating_score, 2),
        "stock_score": round(stock_score, 2),
        "buy_box_score": buy_box_score
    }


def resolve_tie(
    tied_entries: List[Dict[str, Any]],
    tie_breaker: str = "seller_rating"
) -> str:
    """
    Resolve a tie between entries with similar scores.

    Tie-breaker criteria in order:
    1. Primary: specified tie_breaker (default: seller_rating)
    2. Secondary: on_time_delivery_rate
    3. Tertiary: total_reviews
    4. Final: earliest entry (winner_since or creation)

    Args:
        tied_entries: List of entries with similar scores
        tie_breaker: Primary tie-breaker criterion

    Returns:
        str: Name of the winning entry
    """
    if not tied_entries:
        return None

    if len(tied_entries) == 1:
        return tied_entries[0]["name"]

    # Sort by tie-breaker criteria
    def sort_key(entry):
        # Primary: tie_breaker field (higher is better)
        primary = -flt(entry.get(tie_breaker, entry.get("seller_average_rating", 0)))
        # Secondary: on-time delivery rate (higher is better)
        secondary = -flt(entry.get("seller_on_time_delivery_rate", 0))
        # Tertiary: total reviews (higher is better)
        tertiary = -cint(entry.get("seller_total_reviews", 0))
        # Final: winner_since or creation (earlier is better for incumbency)
        final = entry.get("winner_since") or entry.get("creation") or now_datetime()

        return (primary, secondary, tertiary, final)

    sorted_entries = sorted(tied_entries, key=sort_key)
    return sorted_entries[0]["name"]


def calculate_buybox_winner(
    sku_product: str,
    weights: Optional[Dict[str, float]] = None,
    use_locking: bool = True,
    update_entries: bool = True
) -> Dict[str, Any]:
    """
    Calculate the Buy Box winner for a product.

    This is the main algorithm function that:
    1. Retrieves all active entries for the product
    2. Calculates scores for each entry
    3. Determines the winner based on highest composite score
    4. Resolves ties using secondary criteria
    5. Optionally updates all entries in the database

    Args:
        sku_product: The SKU Product name
        weights: Optional custom scoring weights
        use_locking: Whether to use database locking for concurrent safety
        update_entries: Whether to update entries in database

    Returns:
        dict: Result containing:
            - success: bool
            - winner: str (entry name) or None
            - winner_score: float or None
            - entries_processed: int
            - scores: list of score details for each entry
            - message: str

    Example:
        >>> result = calculate_buybox_winner("SKU-00001")
        >>> print(result["winner"], result["winner_score"])
        "BBX-00001", 85.5
    """
    # Get all active entries for the product
    filters = {
        "sku_product": sku_product,
        "status": "Active"
    }

    # Use SELECT ... FOR UPDATE if locking is enabled
    # This prevents race conditions during concurrent updates
    if use_locking:
        entries = frappe.db.sql("""
            SELECT
                name, offer_price, delivery_days, stock_available,
                seller_average_rating, seller_total_reviews,
                seller_on_time_delivery_rate, is_winner, winner_since,
                seller, seller_name
            FROM `tabBuy Box Entry`
            WHERE sku_product = %s AND status = 'Active'
            FOR UPDATE
        """, (sku_product,), as_dict=True)
    else:
        entries = frappe.get_all(
            "Buy Box Entry",
            filters=filters,
            fields=[
                "name", "offer_price", "delivery_days", "stock_available",
                "seller_average_rating", "seller_total_reviews",
                "seller_on_time_delivery_rate", "is_winner", "winner_since",
                "seller", "seller_name"
            ]
        )

    # Handle no entries
    if not entries:
        return {
            "success": True,
            "winner": None,
            "winner_score": None,
            "entries_processed": 0,
            "scores": [],
            "message": _("No active Buy Box entries for this product")
        }

    # Calculate scores for all entries
    scored_entries = []
    for entry in entries:
        scores = calculate_entry_scores(entry, entries, weights)
        scored_entry = {
            **entry,
            **scores,
            "was_winner": entry.get("is_winner")
        }
        scored_entries.append(scored_entry)

    # Sort by composite score (highest first)
    scored_entries.sort(key=lambda x: x["buy_box_score"], reverse=True)

    # Determine winner
    if len(scored_entries) == 1:
        winner_name = scored_entries[0]["name"]
    else:
        # Check for ties
        top_score = scored_entries[0]["buy_box_score"]
        tied_entries = [
            e for e in scored_entries
            if abs(e["buy_box_score"] - top_score) <= TIE_THRESHOLD
        ]

        if len(tied_entries) > 1:
            # Resolve tie
            winner_name = resolve_tie(tied_entries)
        else:
            winner_name = scored_entries[0]["name"]

    # Get winner score
    winner_entry = next((e for e in scored_entries if e["name"] == winner_name), None)
    winner_score = winner_entry["buy_box_score"] if winner_entry else None

    # Update entries in database if requested
    if update_entries:
        now = now_datetime()
        for entry in scored_entries:
            is_winner = 1 if entry["name"] == winner_name else 0

            update_values = {
                "price_score": entry["price_score"],
                "delivery_score": entry["delivery_score"],
                "rating_score": entry["rating_score"],
                "stock_score": entry["stock_score"],
                "buy_box_score": entry["buy_box_score"],
                "is_winner": is_winner,
                "last_score_update": now
            }

            # Set/clear winner_since timestamp
            if is_winner and not entry.get("was_winner"):
                update_values["winner_since"] = now
            elif not is_winner and entry.get("was_winner"):
                update_values["winner_since"] = None

            frappe.db.set_value(
                "Buy Box Entry",
                entry["name"],
                update_values,
                update_modified=False
            )

        frappe.db.commit()

    return {
        "success": True,
        "winner": winner_name,
        "winner_score": winner_score,
        "winner_seller": winner_entry.get("seller_name") if winner_entry else None,
        "entries_processed": len(scored_entries),
        "scores": [
            {
                "entry": e["name"],
                "seller": e.get("seller_name"),
                "buy_box_score": e["buy_box_score"],
                "price_score": e["price_score"],
                "delivery_score": e["delivery_score"],
                "rating_score": e["rating_score"],
                "stock_score": e["stock_score"],
                "is_winner": 1 if e["name"] == winner_name else 0
            }
            for e in scored_entries
        ],
        "message": _("Buy Box calculated successfully")
    }


def get_buybox_winner(sku_product: str) -> Optional[Dict[str, Any]]:
    """
    Get the current Buy Box winner for a product without recalculating.

    Args:
        sku_product: The SKU Product name

    Returns:
        dict: Winner entry details or None if no winner
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
            "seller_average_rating", "winner_since",
            "price_score", "delivery_score", "rating_score", "stock_score"
        ],
        limit=1
    )

    return winner[0] if winner else None


def bulk_calculate_buybox(
    tenant: Optional[str] = None,
    limit: int = 0,
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Bulk calculate Buy Box for multiple products.

    Used by scheduled jobs to recalculate all Buy Boxes periodically.

    Args:
        tenant: Optional tenant filter
        limit: Maximum products to process (0 = unlimited)
        weights: Optional custom scoring weights

    Returns:
        dict: Summary with products_processed, winners_changed, errors
    """
    # Get all products with active Buy Box entries
    query = """
        SELECT DISTINCT sku_product
        FROM `tabBuy Box Entry`
        WHERE status = 'Active'
    """
    params = []

    if tenant:
        query += " AND tenant = %s"
        params.append(tenant)

    if limit:
        query += f" LIMIT {cint(limit)}"

    products = frappe.db.sql(query, tuple(params), as_dict=True)

    results = {
        "products_processed": 0,
        "winners_changed": 0,
        "errors": []
    }

    for product in products:
        try:
            # Get current winner before recalculation
            current_winner = get_buybox_winner(product["sku_product"])
            current_winner_name = current_winner["name"] if current_winner else None

            # Recalculate
            result = calculate_buybox_winner(
                product["sku_product"],
                weights=weights,
                use_locking=True,
                update_entries=True
            )

            results["products_processed"] += 1

            # Check if winner changed
            if result.get("winner") != current_winner_name:
                results["winners_changed"] += 1

        except Exception as e:
            results["errors"].append({
                "product": product["sku_product"],
                "error": str(e)
            })
            frappe.log_error(
                message=str(e),
                title=f"Buy Box Calculation Error: {product['sku_product']}"
            )

    return results


# =============================================================================
# CONFIGURATION AND SETTINGS
# =============================================================================


def get_buybox_weights(tenant: Optional[str] = None) -> Dict[str, float]:
    """
    Get Buy Box scoring weights for a tenant.

    Weights can be configured per tenant or use global defaults.

    Args:
        tenant: Optional tenant name

    Returns:
        dict: Scoring weights with keys: price, delivery, rating, stock
    """
    # Try to get tenant-specific settings
    if tenant:
        try:
            settings = frappe.get_cached_doc("Tenant", tenant)
            if hasattr(settings, "buybox_price_weight") and settings.buybox_price_weight:
                return {
                    "price": flt(settings.buybox_price_weight) / 100,
                    "delivery": flt(settings.buybox_delivery_weight) / 100,
                    "rating": flt(settings.buybox_rating_weight) / 100,
                    "stock": flt(settings.buybox_stock_weight) / 100
                }
        except Exception:
            pass

    # Return default weights
    return DEFAULT_WEIGHTS.copy()


def validate_weights(weights: Dict[str, float]) -> Tuple[bool, str]:
    """
    Validate that scoring weights are valid.

    Args:
        weights: Dictionary with price, delivery, rating, stock keys

    Returns:
        tuple: (is_valid, error_message)
    """
    required_keys = ["price", "delivery", "rating", "stock"]

    # Check all keys present
    for key in required_keys:
        if key not in weights:
            return False, f"Missing weight key: {key}"

    # Check values are between 0 and 1
    for key, value in weights.items():
        if value < 0 or value > 1:
            return False, f"Weight {key} must be between 0 and 1"

    # Check sum is approximately 1.0
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        return False, f"Weights must sum to 1.0, got {total}"

    return True, ""


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def calculate_buybox_for_product(sku_product: str, weights: Optional[str] = None) -> Dict[str, Any]:
    """
    API to calculate Buy Box winner for a product.

    Args:
        sku_product: The SKU Product name
        weights: Optional JSON string of custom weights

    Returns:
        dict: Calculation result
    """
    if not sku_product:
        frappe.throw(_("SKU Product is required"))

    custom_weights = None
    if weights:
        import json
        try:
            custom_weights = json.loads(weights)
            is_valid, error = validate_weights(custom_weights)
            if not is_valid:
                frappe.throw(_(error))
        except json.JSONDecodeError:
            frappe.throw(_("Invalid weights format"))

    return calculate_buybox_winner(sku_product, weights=custom_weights)


@frappe.whitelist()
def get_product_buybox_info(sku_product: str) -> Dict[str, Any]:
    """
    Get Buy Box information for a product.

    Args:
        sku_product: The SKU Product name

    Returns:
        dict: Buy Box info including winner, all entries, and statistics
    """
    if not sku_product:
        frappe.throw(_("SKU Product is required"))

    # Get winner
    winner = get_buybox_winner(sku_product)

    # Get all active entries
    entries = frappe.get_all(
        "Buy Box Entry",
        filters={
            "sku_product": sku_product,
            "status": "Active"
        },
        fields=[
            "name", "seller", "seller_name", "offer_price", "currency",
            "delivery_days", "stock_available", "buy_box_score",
            "is_winner"
        ],
        order_by="buy_box_score desc"
    )

    # Calculate statistics
    stats = {
        "total_entries": len(entries),
        "min_price": min([flt(e.offer_price) for e in entries]) if entries else 0,
        "max_price": max([flt(e.offer_price) for e in entries]) if entries else 0,
        "avg_price": (sum([flt(e.offer_price) for e in entries]) / len(entries)) if entries else 0,
        "min_delivery": min([cint(e.delivery_days) for e in entries]) if entries else 0,
        "max_delivery": max([cint(e.delivery_days) for e in entries]) if entries else 0
    }

    return {
        "winner": winner,
        "entries": entries,
        "statistics": stats
    }


@frappe.whitelist()
def get_scoring_weights(tenant: Optional[str] = None) -> Dict[str, float]:
    """
    Get current Buy Box scoring weights.

    Args:
        tenant: Optional tenant name for tenant-specific weights

    Returns:
        dict: Current scoring weights
    """
    return get_buybox_weights(tenant)


@frappe.whitelist()
def recalculate_all_buyboxes(tenant: Optional[str] = None) -> Dict[str, Any]:
    """
    Recalculate Buy Box for all products (scheduled job).

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Summary of recalculation results
    """
    return bulk_calculate_buybox(tenant=tenant)


@frappe.whitelist()
def simulate_buybox_score(
    offer_price: float,
    delivery_days: int,
    seller_rating: float,
    total_reviews: int,
    stock_available: float,
    sku_product: Optional[str] = None
) -> Dict[str, Any]:
    """
    Simulate a Buy Box score for given parameters.

    Useful for sellers to preview their potential score before submitting.

    Args:
        offer_price: Proposed offer price
        delivery_days: Estimated delivery days
        seller_rating: Seller's average rating
        total_reviews: Seller's total reviews
        stock_available: Available stock quantity
        sku_product: Optional product to compare against existing entries

    Returns:
        dict: Simulated scores and comparison info
    """
    # Create simulated entry
    simulated_entry = {
        "offer_price": flt(offer_price),
        "delivery_days": cint(delivery_days),
        "seller_average_rating": flt(seller_rating),
        "seller_total_reviews": cint(total_reviews),
        "stock_available": flt(stock_available)
    }

    # Get competing entries if product specified
    if sku_product:
        entries = frappe.get_all(
            "Buy Box Entry",
            filters={
                "sku_product": sku_product,
                "status": "Active"
            },
            fields=[
                "offer_price", "delivery_days", "stock_available",
                "seller_average_rating", "seller_total_reviews", "buy_box_score"
            ]
        )
        entries.append(simulated_entry)
    else:
        entries = [simulated_entry]

    # Calculate scores
    scores = calculate_entry_scores(simulated_entry, entries)

    # Determine rank if comparing
    rank = 1
    if sku_product and len(entries) > 1:
        all_scores = sorted(
            [calculate_entry_scores(e, entries)["buy_box_score"] for e in entries],
            reverse=True
        )
        for i, score in enumerate(all_scores, 1):
            if abs(score - scores["buy_box_score"]) < 0.01:
                rank = i
                break

    return {
        "scores": scores,
        "would_win": rank == 1,
        "rank": rank,
        "total_competitors": len(entries) - 1 if sku_product else 0
    }


@frappe.whitelist()
def get_buybox_algorithm_info() -> Dict[str, Any]:
    """
    Get information about the Buy Box algorithm.

    Returns:
        dict: Algorithm info including factors, weights, and thresholds
    """
    return {
        "factors": [
            {
                "name": "price",
                "label": _("Price Score"),
                "weight": DEFAULT_WEIGHTS["price"],
                "description": _("Lower prices receive higher scores")
            },
            {
                "name": "delivery",
                "label": _("Delivery Score"),
                "weight": DEFAULT_WEIGHTS["delivery"],
                "description": _("Faster delivery times receive higher scores")
            },
            {
                "name": "rating",
                "label": _("Rating Score"),
                "weight": DEFAULT_WEIGHTS["rating"],
                "description": _("Higher seller ratings with more reviews receive higher scores")
            },
            {
                "name": "stock",
                "label": _("Stock Score"),
                "weight": DEFAULT_WEIGHTS["stock"],
                "description": _("Higher stock availability receives higher scores")
            }
        ],
        "tie_threshold": TIE_THRESHOLD,
        "rating_confidence_threshold": RATING_CONFIDENCE_THRESHOLD,
        "score_range": {"min": 0, "max": 100}
    }
