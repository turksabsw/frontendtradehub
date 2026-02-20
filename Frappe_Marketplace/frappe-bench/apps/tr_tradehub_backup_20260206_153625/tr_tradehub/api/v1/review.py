# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Ratings & Reviews API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Review creation (product, seller, order experience)
- Review listing and filtering
- Review eligibility checking
- Helpfulness voting
- Review reporting and flagging
- Seller response management
- Review moderation (admin)
- Review statistics and analytics

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.review.<function_name>

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
    get_datetime,
    strip_html_tags,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "review_create": {"limit": 10, "window": 3600},  # 10 reviews per hour
    "review_update": {"limit": 20, "window": 300},  # 20 updates per 5 min
    "review_vote": {"limit": 50, "window": 300},  # 50 votes per 5 min
    "review_report": {"limit": 10, "window": 3600},  # 10 reports per hour
    "seller_response": {"limit": 30, "window": 300},  # 30 responses per 5 min
    "moderation": {"limit": 100, "window": 300},  # 100 moderations per 5 min
}

# Review constraints
MIN_REVIEW_LENGTH = 20
MAX_REVIEW_LENGTH = 5000
MAX_TITLE_LENGTH = 200
MAX_IMAGES = 5


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

    cache_key = f"rate_limit:review:{action}:{identifier}"

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
# VALIDATION HELPERS
# =============================================================================


def validate_rating(rating: Any) -> float:
    """
    Validate and normalize rating value.

    Args:
        rating: Rating value (1-5)

    Returns:
        float: Normalized rating value

    Raises:
        frappe.ValidationError: If rating is invalid
    """
    try:
        rating = flt(rating)
    except (ValueError, TypeError):
        frappe.throw(_("Invalid rating value"))

    if rating < 1 or rating > 5:
        frappe.throw(_("Rating must be between 1 and 5"))

    return rating


def validate_review_text(text: str, field_name: str = "Review") -> str:
    """
    Validate review text content.

    Args:
        text: Review text to validate
        field_name: Name of field for error messages

    Returns:
        str: Cleaned text

    Raises:
        frappe.ValidationError: If text is invalid
    """
    if not text:
        frappe.throw(_(f"{field_name} text is required"))

    # Strip HTML and check length
    plain_text = strip_html_tags(text).strip()

    if len(plain_text) < MIN_REVIEW_LENGTH:
        frappe.throw(
            _(f"{field_name} must be at least {MIN_REVIEW_LENGTH} characters long")
        )

    if len(plain_text) > MAX_REVIEW_LENGTH:
        frappe.throw(
            _(f"{field_name} cannot exceed {MAX_REVIEW_LENGTH} characters")
        )

    return text


def validate_images(images: Any) -> str:
    """
    Validate review images.

    Args:
        images: Image URLs (list or JSON string)

    Returns:
        str: JSON string of validated images

    Raises:
        frappe.ValidationError: If images are invalid
    """
    if not images:
        return "[]"

    if isinstance(images, str):
        try:
            images = json.loads(images)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid image format"))

    if not isinstance(images, list):
        frappe.throw(_("Images must be a list"))

    if len(images) > MAX_IMAGES:
        frappe.throw(_(f"Maximum {MAX_IMAGES} images allowed per review"))

    return json.dumps(images)


def validate_detailed_ratings(ratings: Any) -> Dict[str, int]:
    """
    Validate detailed ratings object.

    Args:
        ratings: Detailed ratings (dict or JSON string)

    Returns:
        dict: Validated ratings

    Raises:
        frappe.ValidationError: If ratings are invalid
    """
    if not ratings:
        return {}

    if isinstance(ratings, str):
        try:
            ratings = json.loads(ratings)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid detailed ratings format"))

    if not isinstance(ratings, dict):
        frappe.throw(_("Detailed ratings must be an object"))

    # Validate each rating field
    valid_fields = [
        "product_quality",
        "value_for_money",
        "shipping",
        "seller_communication",
        "accuracy"
    ]

    validated = {}
    for field in valid_fields:
        if field in ratings:
            value = cint(ratings[field])
            validated[field] = max(0, min(5, value))

    return validated


def _log_review_event(event_type: str, review_name: str, details: Optional[Dict] = None):
    """
    Log review-related events for audit trail.

    Args:
        event_type: Type of event (create, update, vote, report, etc.)
        review_name: Review document name
        details: Additional event details
    """
    try:
        frappe.get_doc({
            "doctype": "Activity Log",
            "user": frappe.session.user,
            "reference_doctype": "Review",
            "reference_name": review_name,
            "subject": f"Review {event_type}",
            "content": json.dumps(details or {}),
        }).insert(ignore_permissions=True)
    except Exception:
        pass  # Don't fail on logging errors


# =============================================================================
# REVIEW ELIGIBILITY ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def check_eligibility(listing: Optional[str] = None, seller: Optional[str] = None) -> Dict[str, Any]:
    """
    Check if current user is eligible to review a listing or seller.

    Args:
        listing: Listing name (for product reviews)
        seller: Seller Profile name (for seller reviews)

    Returns:
        dict: Eligibility status with details
            - eligible: bool - Whether user can review
            - has_purchased: bool - Whether user has purchased
            - already_reviewed: bool - Whether user already reviewed
            - eligible_orders: list - Orders eligible for review
            - reason: str - Explanation if not eligible

    API: POST /api/method/tr_tradehub.api.v1.review.check_eligibility
    """
    if not listing and not seller:
        frappe.throw(_("Either listing or seller is required"))

    # Import Review class from DocType
    from tr_tradehub.tr_tradehub.doctype.review.review import Review

    return Review.check_review_eligibility(
        reviewer=frappe.session.user,
        listing=listing,
        seller=seller
    )


@frappe.whitelist(allow_guest=False)
def get_reviewable_orders(
    listing: Optional[str] = None,
    seller: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Get orders that the user can review for a listing or seller.

    Args:
        listing: Listing name
        seller: Seller Profile name
        limit: Maximum orders to return

    Returns:
        dict: Reviewable orders with details

    API: POST /api/method/tr_tradehub.api.v1.review.get_reviewable_orders
    """
    if not listing and not seller:
        frappe.throw(_("Either listing or seller is required"))

    user = frappe.session.user

    # Build query based on target
    if listing:
        orders = frappe.db.sql("""
            SELECT DISTINCT
                mo.name as order_name,
                mo.order_date,
                mo.status,
                moi.listing,
                moi.listing_title,
                moi.qty,
                moi.rate,
                CASE WHEN EXISTS (
                    SELECT 1 FROM `tabReview` r
                    WHERE r.reviewer = %(user)s
                    AND r.listing = %(listing)s
                    AND r.status NOT IN ('Removed', 'Rejected')
                ) THEN 1 ELSE 0 END as already_reviewed
            FROM `tabMarketplace Order` mo
            JOIN `tabMarketplace Order Item` moi ON moi.parent = mo.name
            WHERE mo.buyer = %(user)s
            AND moi.listing = %(listing)s
            AND mo.status IN ('Delivered', 'Completed')
            AND mo.docstatus != 2
            ORDER BY mo.order_date DESC
            LIMIT %(limit)s
        """, {
            "user": user,
            "listing": listing,
            "limit": cint(limit)
        }, as_dict=True)
    else:
        orders = frappe.db.sql("""
            SELECT DISTINCT
                mo.name as order_name,
                mo.order_date,
                mo.status,
                moi.seller,
                moi.seller_name,
                COUNT(moi.name) as items_from_seller,
                SUM(moi.amount) as total_from_seller,
                CASE WHEN EXISTS (
                    SELECT 1 FROM `tabReview` r
                    WHERE r.reviewer = %(user)s
                    AND r.seller = %(seller)s
                    AND r.status NOT IN ('Removed', 'Rejected')
                ) THEN 1 ELSE 0 END as already_reviewed
            FROM `tabMarketplace Order` mo
            JOIN `tabMarketplace Order Item` moi ON moi.parent = mo.name
            WHERE mo.buyer = %(user)s
            AND moi.seller = %(seller)s
            AND mo.status IN ('Delivered', 'Completed')
            AND mo.docstatus != 2
            GROUP BY mo.name
            ORDER BY mo.order_date DESC
            LIMIT %(limit)s
        """, {
            "user": user,
            "seller": seller,
            "limit": cint(limit)
        }, as_dict=True)

    already_reviewed = any(o.get("already_reviewed") for o in orders) if orders else False

    return {
        "orders": orders,
        "can_review": len(orders) > 0 and not already_reviewed,
        "already_reviewed": already_reviewed,
        "total_orders": len(orders)
    }


# =============================================================================
# REVIEW CRUD ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def create_review(
    review_type: str,
    rating: float,
    review_text: str,
    listing: Optional[str] = None,
    seller: Optional[str] = None,
    order: Optional[str] = None,
    title: Optional[str] = None,
    pros: Optional[str] = None,
    cons: Optional[str] = None,
    images: Optional[str] = None,
    video_url: Optional[str] = None,
    detailed_ratings: Optional[str] = None,
    is_anonymous: bool = False
) -> Dict[str, Any]:
    """
    Create a new review for a product or seller.

    Args:
        review_type: Type of review - 'Product', 'Seller', or 'Order Experience'
        rating: Overall rating (1-5)
        review_text: Main review content (min 20 chars)
        listing: Listing name (required for Product reviews)
        seller: Seller Profile name (required for Seller reviews)
        order: Marketplace Order name for verification
        title: Optional review title
        pros: Optional pros text
        cons: Optional cons text
        images: JSON array of image URLs (max 5)
        video_url: Optional video URL (YouTube, Vimeo, etc.)
        detailed_ratings: JSON object with detailed ratings
        is_anonymous: Whether to show review anonymously

    Returns:
        dict: Created review details
            - status: str - 'success' or 'error'
            - review: str - Review document name
            - review_id: str - Review identifier
            - message: str - Status message

    API: POST /api/method/tr_tradehub.api.v1.review.create_review
    """
    # Rate limiting
    check_rate_limit("review_create")

    # Validate inputs
    if review_type not in ["Product", "Seller", "Order Experience"]:
        frappe.throw(_("Invalid review type"))

    rating = validate_rating(rating)
    review_text = validate_review_text(review_text)
    images = validate_images(images)
    detailed_ratings_dict = validate_detailed_ratings(detailed_ratings)

    # Validate title if provided
    if title and len(title) > MAX_TITLE_LENGTH:
        frappe.throw(_(f"Title cannot exceed {MAX_TITLE_LENGTH} characters"))

    # Validate target based on review type
    if review_type == "Product":
        if not listing:
            frappe.throw(_("Listing is required for product reviews"))
        if not frappe.db.exists("Listing", listing):
            frappe.throw(_("Listing not found"))
    elif review_type == "Seller":
        if not seller:
            frappe.throw(_("Seller is required for seller reviews"))
        if not frappe.db.exists("Seller Profile", seller):
            frappe.throw(_("Seller not found"))

    # Check eligibility
    from tr_tradehub.tr_tradehub.doctype.review.review import Review

    eligibility = Review.check_review_eligibility(
        reviewer=frappe.session.user,
        listing=listing,
        seller=seller
    )

    if not eligibility["eligible"]:
        if eligibility["already_reviewed"]:
            frappe.throw(_("You have already reviewed this item"))
        else:
            frappe.throw(eligibility.get("reason") or _("You are not eligible to review"))

    # Create review document
    review_doc = frappe.get_doc({
        "doctype": "Review",
        "review_type": review_type,
        "listing": listing,
        "seller": seller,
        "rating": rating,
        "title": title,
        "review_text": review_text,
        "pros": pros,
        "cons": cons,
        "marketplace_order": order,
        "images": images,
        "video_url": video_url,
        "is_anonymous": cint(is_anonymous),
        "status": "Pending Review",
        "moderation_status": "Pending"
    })

    # Apply detailed ratings
    if detailed_ratings_dict:
        review_doc.product_quality_rating = detailed_ratings_dict.get("product_quality", 0)
        review_doc.value_for_money_rating = detailed_ratings_dict.get("value_for_money", 0)
        review_doc.shipping_rating = detailed_ratings_dict.get("shipping", 0)
        review_doc.seller_communication_rating = detailed_ratings_dict.get("seller_communication", 0)
        review_doc.accuracy_rating = detailed_ratings_dict.get("accuracy", 0)

    review_doc.insert()

    # Log event
    _log_review_event("created", review_doc.name, {
        "review_type": review_type,
        "rating": rating,
        "listing": listing,
        "seller": seller
    })

    return {
        "status": "success",
        "review": review_doc.name,
        "review_id": review_doc.review_id,
        "message": _("Review submitted for moderation")
    }


@frappe.whitelist(allow_guest=False)
def update_review(
    review_name: str,
    rating: Optional[float] = None,
    review_text: Optional[str] = None,
    title: Optional[str] = None,
    pros: Optional[str] = None,
    cons: Optional[str] = None,
    images: Optional[str] = None,
    video_url: Optional[str] = None,
    detailed_ratings: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update an existing review.

    Args:
        review_name: Review document name
        rating: New rating (1-5)
        review_text: New review text
        title: New title
        pros: New pros text
        cons: New cons text
        images: New images JSON
        video_url: New video URL
        detailed_ratings: New detailed ratings JSON

    Returns:
        dict: Update result

    API: POST /api/method/tr_tradehub.api.v1.review.update_review
    """
    # Rate limiting
    check_rate_limit("review_update")

    # Get review document
    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Check ownership
    if review.reviewer != frappe.session.user:
        frappe.throw(_("You can only edit your own reviews"))

    # Check if review can be edited
    if review.status in ["Removed", "Rejected"]:
        frappe.throw(_("This review cannot be edited"))

    # Update fields if provided
    if rating is not None:
        review.rating = validate_rating(rating)

    if review_text is not None:
        review.review_text = validate_review_text(review_text)

    if title is not None:
        if len(title) > MAX_TITLE_LENGTH:
            frappe.throw(_(f"Title cannot exceed {MAX_TITLE_LENGTH} characters"))
        review.title = title

    if pros is not None:
        review.pros = pros

    if cons is not None:
        review.cons = cons

    if images is not None:
        review.images = validate_images(images)

    if video_url is not None:
        review.video_url = video_url

    # Apply detailed ratings if provided
    if detailed_ratings:
        detailed = validate_detailed_ratings(detailed_ratings)
        if "product_quality" in detailed:
            review.product_quality_rating = detailed["product_quality"]
        if "value_for_money" in detailed:
            review.value_for_money_rating = detailed["value_for_money"]
        if "shipping" in detailed:
            review.shipping_rating = detailed["shipping"]
        if "seller_communication" in detailed:
            review.seller_communication_rating = detailed["seller_communication"]
        if "accuracy" in detailed:
            review.accuracy_rating = detailed["accuracy"]

    # If review was published, it needs re-moderation
    if review.status == "Published":
        review.status = "Pending Review"
        review.moderation_status = "Pending"

    review.save()

    # Log event
    _log_review_event("updated", review_name)

    return {
        "status": "success",
        "review": review.name,
        "message": _("Review updated successfully")
    }


@frappe.whitelist(allow_guest=False)
def delete_review(review_name: str) -> Dict[str, Any]:
    """
    Delete a review (soft delete by owner).

    Args:
        review_name: Review document name

    Returns:
        dict: Deletion result

    API: POST /api/method/tr_tradehub.api.v1.review.delete_review
    """
    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Check ownership
    if review.reviewer != frappe.session.user:
        frappe.throw(_("You can only delete your own reviews"))

    # Soft delete
    review.remove(reason="Deleted by owner")

    # Log event
    _log_review_event("deleted", review_name)

    return {
        "status": "success",
        "message": _("Review deleted successfully")
    }


@frappe.whitelist(allow_guest=True)
def get_review(
    review_name: Optional[str] = None,
    review_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a single review's details.

    Args:
        review_name: Review document name
        review_id: Review identifier

    Returns:
        dict: Review details

    API: POST /api/method/tr_tradehub.api.v1.review.get_review
    """
    if not review_name and not review_id:
        frappe.throw(_("Either review_name or review_id is required"))

    if review_id and not review_name:
        review_name = frappe.db.get_value("Review", {"review_id": review_id}, "name")

    if not review_name or not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Only show published reviews to public, unless it's the owner
    if review.status != "Published" and review.reviewer != frappe.session.user:
        frappe.throw(_("Review not found"))

    return review.get_display_data()


# =============================================================================
# REVIEW LISTING ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_listing_reviews(
    listing: str,
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "recent",
    rating_filter: Optional[int] = None,
    verified_only: bool = False,
    with_images_only: bool = False
) -> Dict[str, Any]:
    """
    Get reviews for a specific listing.

    Args:
        listing: Listing name
        page: Page number (default 1)
        page_size: Results per page (default 10, max 50)
        sort_by: Sort order - 'recent', 'helpful', 'rating_high', 'rating_low'
        rating_filter: Filter by specific rating (1-5)
        verified_only: Only show verified purchase reviews
        with_images_only: Only show reviews with images

    Returns:
        dict: Reviews with pagination and statistics

    API: POST /api/method/tr_tradehub.api.v1.review.get_listing_reviews
    """
    if not frappe.db.exists("Listing", listing):
        frappe.throw(_("Listing not found"))

    # Normalize pagination
    page = max(1, cint(page))
    page_size = min(50, max(1, cint(page_size)))

    # Build filters
    filters = {
        "listing": listing,
        "status": "Published",
        "review_type": "Product"
    }

    if rating_filter:
        filters["rating"] = cint(rating_filter)

    if verified_only:
        filters["is_verified_purchase"] = 1

    if with_images_only:
        filters["images"] = ["!=", "[]"]

    # Determine sort order
    sort_orders = {
        "recent": "published_at DESC",
        "helpful": "helpful_count DESC, published_at DESC",
        "rating_high": "rating DESC, published_at DESC",
        "rating_low": "rating ASC, published_at DESC"
    }
    order_by = sort_orders.get(sort_by, "published_at DESC")

    # Calculate pagination
    start = (page - 1) * page_size
    total = frappe.db.count("Review", filters)

    # Fetch reviews
    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "rating", "title", "review_text",
            "pros", "cons", "display_name", "is_anonymous",
            "is_verified_purchase", "helpful_count", "unhelpful_count",
            "images", "video_url", "published_at", "has_seller_response",
            "seller_response", "seller_response_at", "is_featured", "is_pinned",
            "product_quality_rating", "value_for_money_rating",
            "shipping_rating", "seller_communication_rating", "accuracy_rating"
        ],
        order_by=order_by,
        start=start,
        limit_page_length=page_size
    )

    # Parse images for each review
    for review in reviews:
        try:
            review["images"] = json.loads(review.get("images") or "[]")
        except (json.JSONDecodeError, TypeError):
            review["images"] = []

    # Get statistics
    stats = _get_listing_review_stats(listing)

    return {
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "statistics": stats
    }


@frappe.whitelist(allow_guest=True)
def get_seller_reviews(
    seller: str,
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "recent",
    rating_filter: Optional[int] = None,
    review_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get reviews for a specific seller.

    Args:
        seller: Seller Profile name
        page: Page number
        page_size: Results per page
        sort_by: Sort order
        rating_filter: Filter by specific rating
        review_type: Filter by review type ('Product' or 'Seller')

    Returns:
        dict: Reviews with pagination and statistics

    API: POST /api/method/tr_tradehub.api.v1.review.get_seller_reviews
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    # Normalize pagination
    page = max(1, cint(page))
    page_size = min(50, max(1, cint(page_size)))

    # Build filters
    filters = {
        "seller": seller,
        "status": "Published"
    }

    if rating_filter:
        filters["rating"] = cint(rating_filter)

    if review_type:
        filters["review_type"] = review_type

    # Determine sort order
    sort_orders = {
        "recent": "published_at DESC",
        "helpful": "helpful_count DESC, published_at DESC",
        "rating_high": "rating DESC, published_at DESC",
        "rating_low": "rating ASC, published_at DESC"
    }
    order_by = sort_orders.get(sort_by, "published_at DESC")

    # Calculate pagination
    start = (page - 1) * page_size
    total = frappe.db.count("Review", filters)

    # Fetch reviews
    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "review_text", "display_name", "is_anonymous",
            "is_verified_purchase", "helpful_count", "unhelpful_count",
            "images", "video_url", "published_at", "has_seller_response",
            "seller_response", "seller_response_at", "listing", "listing_title"
        ],
        order_by=order_by,
        start=start,
        limit_page_length=page_size
    )

    # Parse images
    for review in reviews:
        try:
            review["images"] = json.loads(review.get("images") or "[]")
        except (json.JSONDecodeError, TypeError):
            review["images"] = []

    # Get statistics
    stats = _get_seller_review_stats(seller)

    return {
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "statistics": stats
    }


@frappe.whitelist(allow_guest=False)
def get_my_reviews(
    page: int = 1,
    page_size: int = 10,
    status: Optional[str] = None,
    review_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get reviews created by the current user.

    Args:
        page: Page number
        page_size: Results per page
        status: Filter by status
        review_type: Filter by type

    Returns:
        dict: User's reviews with pagination

    API: POST /api/method/tr_tradehub.api.v1.review.get_my_reviews
    """
    # Normalize pagination
    page = max(1, cint(page))
    page_size = min(50, max(1, cint(page_size)))

    # Build filters
    filters = {
        "reviewer": frappe.session.user
    }

    if status:
        filters["status"] = status

    if review_type:
        filters["review_type"] = review_type

    # Calculate pagination
    start = (page - 1) * page_size
    total = frappe.db.count("Review", filters)

    # Fetch reviews
    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "status", "moderation_status", "listing", "listing_title",
            "seller", "seller_name", "is_verified_purchase",
            "published_at", "submitted_at", "has_seller_response",
            "helpful_count", "unhelpful_count", "rejection_reason"
        ],
        order_by="creation DESC",
        start=start,
        limit_page_length=page_size
    )

    return {
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0
    }


@frappe.whitelist(allow_guest=True)
def get_featured_reviews(
    listing: Optional[str] = None,
    seller: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Get featured/pinned reviews.

    Args:
        listing: Filter by listing
        seller: Filter by seller
        limit: Maximum reviews to return

    Returns:
        list: Featured reviews

    API: POST /api/method/tr_tradehub.api.v1.review.get_featured_reviews
    """
    limit = min(20, max(1, cint(limit)))

    filters = {
        "status": "Published",
        "is_featured": 1
    }

    if listing:
        filters["listing"] = listing
    if seller:
        filters["seller"] = seller

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "rating", "title", "review_text",
            "display_name", "is_verified_purchase", "helpful_count",
            "images", "published_at", "listing_title", "seller_name"
        ],
        order_by="is_pinned DESC, helpful_count DESC",
        limit_page_length=limit
    )

    # Parse images
    for review in reviews:
        try:
            review["images"] = json.loads(review.get("images") or "[]")
        except (json.JSONDecodeError, TypeError):
            review["images"] = []

    return reviews


# =============================================================================
# REVIEW INTERACTION ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def vote_helpful(review_name: str) -> Dict[str, Any]:
    """
    Mark a review as helpful.

    Args:
        review_name: Review document name

    Returns:
        dict: Vote result

    API: POST /api/method/tr_tradehub.api.v1.review.vote_helpful
    """
    check_rate_limit("review_vote")

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Can't vote on own reviews
    if review.reviewer == frappe.session.user:
        frappe.throw(_("You cannot vote on your own review"))

    result = review.vote_helpful(frappe.session.user)

    # Log event
    _log_review_event("voted_helpful", review_name)

    return result


@frappe.whitelist(allow_guest=False)
def vote_unhelpful(review_name: str) -> Dict[str, Any]:
    """
    Mark a review as unhelpful.

    Args:
        review_name: Review document name

    Returns:
        dict: Vote result

    API: POST /api/method/tr_tradehub.api.v1.review.vote_unhelpful
    """
    check_rate_limit("review_vote")

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Can't vote on own reviews
    if review.reviewer == frappe.session.user:
        frappe.throw(_("You cannot vote on your own review"))

    result = review.vote_unhelpful(frappe.session.user)

    # Log event
    _log_review_event("voted_unhelpful", review_name)

    return result


@frappe.whitelist(allow_guest=False)
def report_review(
    review_name: str,
    report_type: str,
    details: Optional[str] = None
) -> Dict[str, Any]:
    """
    Report a review for moderation.

    Args:
        review_name: Review document name
        report_type: Type of report (spam, inappropriate, fake, offensive, other)
        details: Additional details about the report

    Returns:
        dict: Report result

    API: POST /api/method/tr_tradehub.api.v1.review.report_review
    """
    check_rate_limit("review_report")

    valid_report_types = ["spam", "inappropriate", "fake", "offensive", "copyright", "other"]
    if report_type not in valid_report_types:
        frappe.throw(_("Invalid report type"))

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Can't report own reviews
    if review.reviewer == frappe.session.user:
        frappe.throw(_("You cannot report your own review"))

    # Flag the review
    review.flag(flag_type=report_type, reporter=frappe.session.user)

    # Log event
    _log_review_event("reported", review_name, {
        "report_type": report_type,
        "details": details
    })

    return {
        "status": "success",
        "message": _("Thank you for your report. Our team will review it.")
    }


# =============================================================================
# SELLER RESPONSE ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False)
def add_seller_response(
    review_name: str,
    response_text: str
) -> Dict[str, Any]:
    """
    Add a seller response to a review.

    Args:
        review_name: Review document name
        response_text: Response content

    Returns:
        dict: Response result

    API: POST /api/method/tr_tradehub.api.v1.review.add_seller_response
    """
    check_rate_limit("seller_response")

    if not response_text or len(response_text.strip()) < 10:
        frappe.throw(_("Response must be at least 10 characters"))

    if len(response_text) > 2000:
        frappe.throw(_("Response cannot exceed 2000 characters"))

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Verify the responder is the seller
    seller_user = frappe.db.get_value("Seller Profile", review.seller, "user")
    if frappe.session.user != seller_user:
        # Check for admin permission
        if not frappe.has_permission("Review", "write"):
            frappe.throw(_("Only the seller can respond to this review"))

    result = review.add_seller_response(response_text)

    # Log event
    _log_review_event("seller_response_added", review_name)

    return result


@frappe.whitelist(allow_guest=False)
def edit_seller_response(
    review_name: str,
    response_text: str
) -> Dict[str, Any]:
    """
    Edit an existing seller response.

    Args:
        review_name: Review document name
        response_text: New response content

    Returns:
        dict: Edit result

    API: POST /api/method/tr_tradehub.api.v1.review.edit_seller_response
    """
    check_rate_limit("seller_response")

    if not response_text or len(response_text.strip()) < 10:
        frappe.throw(_("Response must be at least 10 characters"))

    if len(response_text) > 2000:
        frappe.throw(_("Response cannot exceed 2000 characters"))

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Verify the responder is the seller
    seller_user = frappe.db.get_value("Seller Profile", review.seller, "user")
    if frappe.session.user != seller_user:
        if not frappe.has_permission("Review", "write"):
            frappe.throw(_("Only the seller can edit their response"))

    result = review.edit_seller_response(response_text)

    # Log event
    _log_review_event("seller_response_edited", review_name)

    return result


@frappe.whitelist(allow_guest=False)
def delete_seller_response(review_name: str) -> Dict[str, Any]:
    """
    Delete a seller response.

    Args:
        review_name: Review document name

    Returns:
        dict: Deletion result

    API: POST /api/method/tr_tradehub.api.v1.review.delete_seller_response
    """
    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Verify the responder is the seller
    seller_user = frappe.db.get_value("Seller Profile", review.seller, "user")
    if frappe.session.user != seller_user:
        if not frappe.has_permission("Review", "write"):
            frappe.throw(_("Only the seller can delete their response"))

    result = review.remove_seller_response()

    # Log event
    _log_review_event("seller_response_deleted", review_name)

    return result


@frappe.whitelist(allow_guest=False)
def get_reviews_needing_response(
    seller: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    """
    Get reviews that don't have a seller response yet.

    Args:
        seller: Seller Profile name (defaults to current user's seller)
        page: Page number
        page_size: Results per page

    Returns:
        dict: Reviews needing response

    API: POST /api/method/tr_tradehub.api.v1.review.get_reviews_needing_response
    """
    # Get seller if not provided
    if not seller:
        seller = frappe.db.get_value(
            "Seller Profile",
            {"user": frappe.session.user, "status": "Active"},
            "name"
        )
        if not seller:
            frappe.throw(_("You are not a registered seller"))

    # Verify ownership
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if frappe.session.user != seller_user:
        if not frappe.has_permission("Review", "write"):
            frappe.throw(_("Access denied"))

    # Normalize pagination
    page = max(1, cint(page))
    page_size = min(50, max(1, cint(page_size)))

    filters = {
        "seller": seller,
        "status": "Published",
        "has_seller_response": 0
    }

    start = (page - 1) * page_size
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "review_text", "display_name", "is_verified_purchase",
            "published_at", "listing", "listing_title"
        ],
        order_by="published_at DESC",
        start=start,
        limit_page_length=page_size
    )

    return {
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0
    }


# =============================================================================
# STATISTICS ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_listing_stats(listing: str) -> Dict[str, Any]:
    """
    Get review statistics for a listing.

    Args:
        listing: Listing name

    Returns:
        dict: Review statistics

    API: POST /api/method/tr_tradehub.api.v1.review.get_listing_stats
    """
    if not frappe.db.exists("Listing", listing):
        frappe.throw(_("Listing not found"))

    return _get_listing_review_stats(listing)


@frappe.whitelist(allow_guest=True)
def get_seller_stats(seller: str) -> Dict[str, Any]:
    """
    Get review statistics for a seller.

    Args:
        seller: Seller Profile name

    Returns:
        dict: Review statistics

    API: POST /api/method/tr_tradehub.api.v1.review.get_seller_stats
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    return _get_seller_review_stats(seller)


@frappe.whitelist(allow_guest=False)
def get_review_analytics(
    days: int = 30,
    seller: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get review analytics for dashboard.

    Args:
        days: Number of days to analyze
        seller: Filter by seller (optional, for seller dashboard)

    Returns:
        dict: Review analytics

    API: POST /api/method/tr_tradehub.api.v1.review.get_review_analytics
    """
    from_date = add_days(nowdate(), -cint(days))

    seller_filter = ""
    params = {"from_date": from_date}

    if seller:
        # Verify access
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if frappe.session.user != seller_user:
            if not frappe.has_permission("Review", "write"):
                frappe.throw(_("Access denied"))
        seller_filter = "AND seller = %(seller)s"
        params["seller"] = seller

    # Overall statistics
    stats = frappe.db.sql(f"""
        SELECT
            COUNT(*) as total_reviews,
            SUM(CASE WHEN status = 'Pending Review' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'Published' THEN 1 ELSE 0 END) as published,
            SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) as rejected,
            SUM(CASE WHEN moderation_status = 'Flagged' THEN 1 ELSE 0 END) as flagged,
            AVG(rating) as avg_rating,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count,
            SUM(CASE WHEN has_seller_response = 1 THEN 1 ELSE 0 END) as responded_count
        FROM `tabReview`
        WHERE creation >= %(from_date)s
        {seller_filter}
    """, params, as_dict=True)[0]

    # Daily breakdown
    daily_stats = frappe.db.sql(f"""
        SELECT
            DATE(creation) as date,
            COUNT(*) as count,
            AVG(rating) as avg_rating
        FROM `tabReview`
        WHERE creation >= %(from_date)s
        {seller_filter}
        GROUP BY DATE(creation)
        ORDER BY date
    """, params, as_dict=True)

    # Rating distribution
    rating_dist = frappe.db.sql(f"""
        SELECT
            rating,
            COUNT(*) as count
        FROM `tabReview`
        WHERE creation >= %(from_date)s
        AND status = 'Published'
        {seller_filter}
        GROUP BY rating
        ORDER BY rating DESC
    """, params, as_dict=True)

    total = cint(stats.total_reviews)

    return {
        "period_days": cint(days),
        "summary": {
            "total_reviews": total,
            "pending_moderation": cint(stats.pending),
            "published": cint(stats.published),
            "rejected": cint(stats.rejected),
            "flagged": cint(stats.flagged),
            "average_rating": flt(stats.avg_rating, 1) if stats.avg_rating else 0,
            "verified_percentage": round(
                cint(stats.verified_count) / total * 100, 1
            ) if total else 0,
            "response_rate": round(
                cint(stats.responded_count) / total * 100, 1
            ) if total else 0
        },
        "daily_trend": [
            {
                "date": str(d.date),
                "count": d.count,
                "avg_rating": flt(d.avg_rating, 1)
            }
            for d in daily_stats
        ],
        "rating_distribution": {
            str(int(r.rating)): r.count for r in rating_dist
        }
    }


# =============================================================================
# MODERATION ENDPOINTS (Admin)
# =============================================================================


@frappe.whitelist(allow_guest=False)
def get_pending_moderation(
    page: int = 1,
    page_size: int = 20,
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get reviews pending moderation (admin only).

    Args:
        page: Page number
        page_size: Results per page
        priority: Filter by priority - 'flagged', 'pending', 'all'

    Returns:
        dict: Pending reviews for moderation

    API: POST /api/method/tr_tradehub.api.v1.review.get_pending_moderation
    """
    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to moderate reviews"))

    # Normalize pagination
    page = max(1, cint(page))
    page_size = min(100, max(1, cint(page_size)))

    # Build filters based on priority
    if priority == "flagged":
        filters = {"moderation_status": "Flagged"}
    elif priority == "pending":
        filters = {"moderation_status": "Pending"}
    else:
        filters = {"moderation_status": ["in", ["Pending", "Flagged", "Under Review"]]}

    start = (page - 1) * page_size
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "review_text", "pros", "cons", "reviewer", "reviewer_name",
            "display_name", "listing", "listing_title", "seller",
            "seller_name", "is_verified_purchase", "is_anonymous",
            "report_count", "moderation_status", "flags", "submitted_at",
            "ip_address", "user_agent"
        ],
        order_by="report_count DESC, submitted_at ASC",
        start=start,
        limit_page_length=page_size
    )

    # Parse flags
    for review in reviews:
        try:
            review["flags"] = json.loads(review.get("flags") or "[]")
        except (json.JSONDecodeError, TypeError):
            review["flags"] = []

    # Get queue stats
    queue_stats = {
        "total_pending": frappe.db.count("Review", {"moderation_status": "Pending"}),
        "total_flagged": frappe.db.count("Review", {"moderation_status": "Flagged"}),
        "total_under_review": frappe.db.count("Review", {"moderation_status": "Under Review"})
    }

    return {
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "queue_stats": queue_stats
    }


@frappe.whitelist(allow_guest=False)
def moderate_review(
    review_name: str,
    action: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Moderate a review (approve, reject, hide, remove).

    Args:
        review_name: Review document name
        action: Moderation action - 'approve', 'reject', 'hide', 'remove'
        reason: Reason for rejection/removal
        notes: Internal moderation notes

    Returns:
        dict: Moderation result

    API: POST /api/method/tr_tradehub.api.v1.review.moderate_review
    """
    check_rate_limit("moderation")

    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to moderate reviews"))

    valid_actions = ["approve", "reject", "hide", "remove"]
    if action not in valid_actions:
        frappe.throw(_("Invalid action"))

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    review = frappe.get_doc("Review", review_name)

    # Perform action
    if action == "approve":
        review.approve(moderator=frappe.session.user)
    elif action == "reject":
        review.reject(reason=reason, notes=notes, moderator=frappe.session.user)
    elif action == "hide":
        review.hide(reason=reason)
    elif action == "remove":
        review.remove(reason=reason)

    # Log event
    _log_review_event(f"moderated_{action}", review_name, {
        "action": action,
        "reason": reason
    })

    return {
        "status": "success",
        "review_status": review.status,
        "moderation_status": review.moderation_status,
        "message": _(f"Review {action}d successfully")
    }


@frappe.whitelist(allow_guest=False)
def bulk_moderate(
    review_names: List[str],
    action: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Moderate multiple reviews at once.

    Args:
        review_names: List of review document names
        action: Moderation action
        reason: Reason for action

    Returns:
        dict: Bulk moderation result

    API: POST /api/method/tr_tradehub.api.v1.review.bulk_moderate
    """
    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to moderate reviews"))

    if isinstance(review_names, str):
        review_names = json.loads(review_names)

    if not isinstance(review_names, list) or len(review_names) == 0:
        frappe.throw(_("No reviews provided"))

    if len(review_names) > 50:
        frappe.throw(_("Maximum 50 reviews can be moderated at once"))

    valid_actions = ["approve", "reject", "hide", "remove"]
    if action not in valid_actions:
        frappe.throw(_("Invalid action"))

    results = {
        "success": [],
        "failed": []
    }

    for review_name in review_names:
        try:
            if not frappe.db.exists("Review", review_name):
                results["failed"].append({
                    "review": review_name,
                    "error": "Not found"
                })
                continue

            review = frappe.get_doc("Review", review_name)

            if action == "approve":
                review.approve(moderator=frappe.session.user)
            elif action == "reject":
                review.reject(reason=reason, moderator=frappe.session.user)
            elif action == "hide":
                review.hide(reason=reason)
            elif action == "remove":
                review.remove(reason=reason)

            results["success"].append(review_name)
        except Exception as e:
            results["failed"].append({
                "review": review_name,
                "error": str(e)
            })

    # Log event
    _log_review_event("bulk_moderation", ",".join(results["success"]), {
        "action": action,
        "count": len(results["success"])
    })

    return {
        "status": "success",
        "processed": len(results["success"]),
        "failed": len(results["failed"]),
        "results": results
    }


@frappe.whitelist(allow_guest=False)
def feature_review(
    review_name: str,
    is_featured: bool = True,
    is_pinned: bool = False
) -> Dict[str, Any]:
    """
    Feature or pin a review.

    Args:
        review_name: Review document name
        is_featured: Whether to feature the review
        is_pinned: Whether to pin the review at top

    Returns:
        dict: Feature result

    API: POST /api/method/tr_tradehub.api.v1.review.feature_review
    """
    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to feature reviews"))

    if not frappe.db.exists("Review", review_name):
        frappe.throw(_("Review not found"))

    frappe.db.set_value("Review", review_name, {
        "is_featured": cint(is_featured),
        "is_pinned": cint(is_pinned)
    })

    return {
        "status": "success",
        "message": _("Review featured successfully") if is_featured else _("Review unfeatured")
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_listing_review_stats(listing: str) -> Dict[str, Any]:
    """Get review statistics for a listing."""
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count,
            SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) as with_images,
            AVG(product_quality_rating) as avg_quality,
            AVG(value_for_money_rating) as avg_value,
            AVG(shipping_rating) as avg_shipping,
            AVG(accuracy_rating) as avg_accuracy
        FROM `tabReview`
        WHERE listing = %(listing)s
        AND status = 'Published'
    """, {"listing": listing}, as_dict=True)[0]

    total = cint(stats.total_reviews)

    return {
        "total_reviews": total,
        "average_rating": flt(stats.average_rating, 1) if stats.average_rating else 0,
        "verified_count": cint(stats.verified_count),
        "with_images_count": cint(stats.with_images),
        "rating_distribution": {
            "5": cint(stats.five_star),
            "4": cint(stats.four_star),
            "3": cint(stats.three_star),
            "2": cint(stats.two_star),
            "1": cint(stats.one_star)
        },
        "rating_percentages": {
            "5": round(cint(stats.five_star) / total * 100, 1) if total else 0,
            "4": round(cint(stats.four_star) / total * 100, 1) if total else 0,
            "3": round(cint(stats.three_star) / total * 100, 1) if total else 0,
            "2": round(cint(stats.two_star) / total * 100, 1) if total else 0,
            "1": round(cint(stats.one_star) / total * 100, 1) if total else 0
        },
        "detailed_averages": {
            "quality": flt(stats.avg_quality, 1) if stats.avg_quality else 0,
            "value": flt(stats.avg_value, 1) if stats.avg_value else 0,
            "shipping": flt(stats.avg_shipping, 1) if stats.avg_shipping else 0,
            "accuracy": flt(stats.avg_accuracy, 1) if stats.avg_accuracy else 0
        }
    }


def _get_seller_review_stats(seller: str) -> Dict[str, Any]:
    """Get review statistics for a seller."""
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count,
            AVG(seller_communication_rating) as avg_communication,
            SUM(CASE WHEN has_seller_response = 1 THEN 1 ELSE 0 END) as with_response
        FROM `tabReview`
        WHERE seller = %(seller)s
        AND status = 'Published'
    """, {"seller": seller}, as_dict=True)[0]

    total = cint(stats.total_reviews)

    return {
        "total_reviews": total,
        "average_rating": flt(stats.average_rating, 1) if stats.average_rating else 0,
        "verified_count": cint(stats.verified_count),
        "response_count": cint(stats.with_response),
        "response_rate": round(cint(stats.with_response) / total * 100, 1) if total else 0,
        "rating_distribution": {
            "5": cint(stats.five_star),
            "4": cint(stats.four_star),
            "3": cint(stats.three_star),
            "2": cint(stats.two_star),
            "1": cint(stats.one_star)
        },
        "rating_percentages": {
            "5": round(cint(stats.five_star) / total * 100, 1) if total else 0,
            "4": round(cint(stats.four_star) / total * 100, 1) if total else 0,
            "3": round(cint(stats.three_star) / total * 100, 1) if total else 0,
            "2": round(cint(stats.two_star) / total * 100, 1) if total else 0,
            "1": round(cint(stats.one_star) / total * 100, 1) if total else 0
        },
        "avg_communication_rating": flt(stats.avg_communication, 1) if stats.avg_communication else 0
    }
