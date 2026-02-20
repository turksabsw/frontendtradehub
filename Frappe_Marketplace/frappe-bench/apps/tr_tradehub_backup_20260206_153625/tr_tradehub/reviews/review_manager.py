# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Review Manager - Core review operations

Handles review submission, updating, publishing, and aggregation.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, cint, flt
from typing import Dict, Any, List, Optional
import hashlib
import json


def submit_review(
    reviewer: str,
    review_type: str,
    listing: str = None,
    seller: str = None,
    rating: int = 5,
    title: str = None,
    review_text: str = None,
    pros: str = None,
    cons: str = None,
    marketplace_order: str = None,
    sub_order: str = None,
    images: List[str] = None,
    is_anonymous: bool = False,
    detailed_ratings: Dict[str, int] = None
) -> Dict[str, Any]:
    """
    Submit a new review.

    Args:
        reviewer: User submitting the review
        review_type: Type of review (Product, Seller, Order Experience)
        listing: Listing being reviewed (for Product reviews)
        seller: Seller being reviewed (for Seller reviews)
        rating: Overall rating (1-5)
        title: Review title
        review_text: Review content
        pros: Positive points
        cons: Negative points
        marketplace_order: Order reference for verification
        sub_order: Sub-order reference
        images: List of image URLs
        is_anonymous: Whether to hide reviewer identity
        detailed_ratings: Dict of category ratings

    Returns:
        Dict with review details or error
    """
    try:
        # Validate rating
        if not 1 <= rating <= 5:
            return {"success": False, "message": _("Rating must be between 1 and 5")}

        # Validate required fields based on review type
        if review_type == "Product" and not listing:
            return {"success": False, "message": _("Listing is required for product reviews")}

        if review_type == "Seller" and not seller:
            return {"success": False, "message": _("Seller is required for seller reviews")}

        # Check minimum review text length
        if review_text and len(review_text.strip()) < 20:
            return {"success": False, "message": _("Review text must be at least 20 characters")}

        # Check for duplicate review
        existing = _check_duplicate_review(reviewer, review_type, listing, seller, marketplace_order)
        if existing:
            return {
                "success": False,
                "message": _("You have already submitted a review for this item"),
                "existing_review": existing
            }

        # Verify purchase if order provided
        is_verified_purchase = False
        purchase_date = None
        if marketplace_order:
            verification = _verify_purchase(reviewer, marketplace_order, listing, seller)
            is_verified_purchase = verification.get("is_verified", False)
            purchase_date = verification.get("purchase_date")

        # Get seller from listing if not provided
        if review_type == "Product" and listing and not seller:
            seller = frappe.db.get_value("Listing", listing, "seller")

        # Create review document
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": review_type,
            "reviewer": reviewer,
            "listing": listing,
            "seller": seller,
            "rating": rating,
            "title": title,
            "review_text": review_text,
            "pros": pros,
            "cons": cons,
            "marketplace_order": marketplace_order,
            "sub_order": sub_order,
            "is_verified_purchase": is_verified_purchase,
            "purchase_date": purchase_date,
            "verification_date": now_datetime() if is_verified_purchase else None,
            "images": json.dumps(images) if images else None,
            "is_anonymous": is_anonymous,
            "status": "Pending Review",
            "moderation_status": "Pending",
            "submitted_at": now_datetime()
        })

        # Set display name
        if is_anonymous:
            review.display_name = _mask_name(
                frappe.db.get_value("User", reviewer, "full_name") or "Anonymous"
            )
        else:
            review.display_name = frappe.db.get_value("User", reviewer, "full_name")

        # Add detailed ratings
        if detailed_ratings:
            review.product_quality_rating = detailed_ratings.get("product_quality", 0)
            review.value_for_money_rating = detailed_ratings.get("value_for_money", 0)
            review.shipping_rating = detailed_ratings.get("shipping", 0)
            review.seller_communication_rating = detailed_ratings.get("seller_communication", 0)
            review.accuracy_rating = detailed_ratings.get("accuracy", 0)

        review.insert(ignore_permissions=True)
        frappe.db.commit()

        # Check for auto-moderation
        _auto_moderate_review(review.name)

        return {
            "success": True,
            "data": {
                "review": review.name,
                "status": review.status,
                "is_verified_purchase": is_verified_purchase
            },
            "message": _("Review submitted successfully")
        }

    except Exception as e:
        frappe.log_error(f"Error submitting review: {str(e)}", "Review Submission")
        return {"success": False, "message": str(e)}


def update_review(
    review_name: str,
    rating: int = None,
    title: str = None,
    review_text: str = None,
    pros: str = None,
    cons: str = None
) -> Dict[str, Any]:
    """
    Update an existing review.

    Only the reviewer can update their own review.
    Updates increment the edit_count.
    """
    try:
        review = frappe.get_doc("Review", review_name)

        # Check permission
        if review.reviewer != frappe.session.user:
            return {"success": False, "message": _("You can only edit your own reviews")}

        # Check if review is editable
        if review.status in ["Removed", "Rejected"]:
            return {"success": False, "message": _("This review cannot be edited")}

        # Update fields
        if rating is not None:
            if not 1 <= rating <= 5:
                return {"success": False, "message": _("Rating must be between 1 and 5")}
            review.rating = rating

        if title is not None:
            review.title = title

        if review_text is not None:
            if len(review_text.strip()) < 20:
                return {"success": False, "message": _("Review text must be at least 20 characters")}
            review.review_text = review_text

        if pros is not None:
            review.pros = pros

        if cons is not None:
            review.cons = cons

        review.edit_count = (review.edit_count or 0) + 1
        review.last_edited_at = now_datetime()

        # Reset moderation if published
        if review.status == "Published":
            review.status = "Pending Review"
            review.moderation_status = "Pending"

        review.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "data": {"review": review.name, "status": review.status},
            "message": _("Review updated successfully")
        }

    except Exception as e:
        frappe.log_error(f"Error updating review: {str(e)}", "Review Update")
        return {"success": False, "message": str(e)}


def publish_review(review_name: str, moderator: str = None) -> Dict[str, Any]:
    """
    Publish an approved review.

    Args:
        review_name: Review document name
        moderator: User who approved (for audit)

    Returns:
        Success status
    """
    try:
        review = frappe.get_doc("Review", review_name)

        if review.status == "Published":
            return {"success": False, "message": _("Review is already published")}

        review.status = "Published"
        review.moderation_status = "Approved"
        review.published_at = now_datetime()

        if moderator:
            review.moderated_by = moderator
            review.moderated_at = now_datetime()

        review.save(ignore_permissions=True)

        # Update aggregated ratings
        _update_listing_ratings(review.listing)
        _update_seller_ratings(review.seller)

        frappe.db.commit()

        return {"success": True, "message": _("Review published successfully")}

    except Exception as e:
        frappe.log_error(f"Error publishing review: {str(e)}", "Review Publish")
        return {"success": False, "message": str(e)}


def hide_review(review_name: str, reason: str = None) -> Dict[str, Any]:
    """Hide a review from public view."""
    try:
        review = frappe.get_doc("Review", review_name)

        review.status = "Hidden"
        review.moderation_notes = reason
        review.save(ignore_permissions=True)

        # Update aggregated ratings
        _update_listing_ratings(review.listing)
        _update_seller_ratings(review.seller)

        frappe.db.commit()

        return {"success": True, "message": _("Review hidden successfully")}

    except Exception as e:
        frappe.log_error(f"Error hiding review: {str(e)}", "Review Hide")
        return {"success": False, "message": str(e)}


def delete_review(review_name: str) -> Dict[str, Any]:
    """
    Mark a review as removed.

    We don't actually delete for audit purposes.
    """
    try:
        review = frappe.get_doc("Review", review_name)

        # Check permission - only reviewer or admin can delete
        if review.reviewer != frappe.session.user and "System Manager" not in frappe.get_roles():
            return {"success": False, "message": _("You don't have permission to delete this review")}

        review.status = "Removed"
        review.save(ignore_permissions=True)

        # Update aggregated ratings
        _update_listing_ratings(review.listing)
        _update_seller_ratings(review.seller)

        frappe.db.commit()

        return {"success": True, "message": _("Review removed successfully")}

    except Exception as e:
        frappe.log_error(f"Error deleting review: {str(e)}", "Review Delete")
        return {"success": False, "message": str(e)}


def get_reviews_for_listing(
    listing: str,
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "helpful",
    rating_filter: int = None,
    verified_only: bool = False
) -> Dict[str, Any]:
    """
    Get reviews for a listing.

    Args:
        listing: Listing name
        limit: Number of reviews to return
        offset: Pagination offset
        sort_by: Sort order (helpful, recent, rating_high, rating_low)
        rating_filter: Filter by specific rating
        verified_only: Only show verified purchases

    Returns:
        List of reviews with statistics
    """
    try:
        filters = {
            "listing": listing,
            "status": "Published",
            "review_type": "Product"
        }

        if rating_filter:
            filters["rating"] = rating_filter

        if verified_only:
            filters["is_verified_purchase"] = 1

        # Determine sort order
        order_by = "helpfulness_score desc, published_at desc"
        if sort_by == "recent":
            order_by = "published_at desc"
        elif sort_by == "rating_high":
            order_by = "rating desc, published_at desc"
        elif sort_by == "rating_low":
            order_by = "rating asc, published_at desc"

        reviews = frappe.get_all(
            "Review",
            filters=filters,
            fields=[
                "name", "review_id", "reviewer", "display_name", "rating",
                "title", "review_text", "pros", "cons", "images",
                "is_verified_purchase", "is_anonymous",
                "helpful_count", "unhelpful_count", "helpfulness_score",
                "has_seller_response", "seller_response", "seller_response_at",
                "published_at", "product_quality_rating", "value_for_money_rating",
                "shipping_rating", "seller_communication_rating", "accuracy_rating"
            ],
            order_by=order_by,
            limit=limit,
            start=offset
        )

        # Get statistics
        total = frappe.db.count("Review", filters)
        stats = _get_review_statistics(listing, "listing")

        return {
            "success": True,
            "data": {
                "reviews": reviews,
                "total": total,
                "statistics": stats
            }
        }

    except Exception as e:
        frappe.log_error(f"Error getting reviews: {str(e)}", "Get Reviews")
        return {"success": False, "message": str(e)}


def get_reviews_for_seller(
    seller: str,
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "helpful"
) -> Dict[str, Any]:
    """Get reviews for a seller."""
    try:
        filters = {
            "seller": seller,
            "status": "Published"
        }

        order_by = "helpfulness_score desc, published_at desc"
        if sort_by == "recent":
            order_by = "published_at desc"

        reviews = frappe.get_all(
            "Review",
            filters=filters,
            fields=[
                "name", "review_id", "reviewer", "display_name", "rating",
                "title", "review_text", "listing", "listing_title",
                "is_verified_purchase", "helpful_count",
                "has_seller_response", "seller_response",
                "published_at"
            ],
            order_by=order_by,
            limit=limit,
            start=offset
        )

        total = frappe.db.count("Review", filters)
        stats = _get_review_statistics(seller, "seller")

        return {
            "success": True,
            "data": {
                "reviews": reviews,
                "total": total,
                "statistics": stats
            }
        }

    except Exception as e:
        frappe.log_error(f"Error getting seller reviews: {str(e)}", "Get Seller Reviews")
        return {"success": False, "message": str(e)}


def vote_helpful(review_name: str, voter: str, is_helpful: bool) -> Dict[str, Any]:
    """
    Vote on review helpfulness.

    Args:
        review_name: Review document name
        voter: User voting
        is_helpful: True for helpful, False for unhelpful

    Returns:
        Updated helpfulness counts
    """
    try:
        review = frappe.get_doc("Review", review_name)

        # Can't vote on own review
        if review.reviewer == voter:
            return {"success": False, "message": _("You cannot vote on your own review")}

        # Check for existing vote (would need a child table or separate DocType)
        # For now, just update the counts

        if is_helpful:
            review.helpful_count = (review.helpful_count or 0) + 1
        else:
            review.unhelpful_count = (review.unhelpful_count or 0) + 1

        # Calculate helpfulness score (Wilson score interval lower bound)
        review.helpfulness_score = _calculate_helpfulness_score(
            review.helpful_count or 0,
            review.unhelpful_count or 0
        )

        review.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "data": {
                "helpful_count": review.helpful_count,
                "unhelpful_count": review.unhelpful_count,
                "helpfulness_score": review.helpfulness_score
            }
        }

    except Exception as e:
        frappe.log_error(f"Error voting on review: {str(e)}", "Review Vote")
        return {"success": False, "message": str(e)}


def add_seller_response(
    review_name: str,
    seller_user: str,
    response_text: str
) -> Dict[str, Any]:
    """
    Add seller response to a review.

    Args:
        review_name: Review document name
        seller_user: Seller's user account
        response_text: Response text

    Returns:
        Success status
    """
    try:
        review = frappe.get_doc("Review", review_name)

        # Verify seller owns the listing/is the reviewed seller
        seller_profile = frappe.db.get_value(
            "Seller Profile",
            {"user": seller_user},
            "name"
        )

        if review.seller != seller_profile:
            return {"success": False, "message": _("You can only respond to reviews of your products")}

        if review.has_seller_response:
            return {"success": False, "message": _("A response already exists")}

        review.has_seller_response = 1
        review.seller_response = response_text
        review.seller_response_by = seller_user
        review.seller_response_at = now_datetime()

        review.save(ignore_permissions=True)
        frappe.db.commit()

        return {"success": True, "message": _("Response added successfully")}

    except Exception as e:
        frappe.log_error(f"Error adding seller response: {str(e)}", "Seller Response")
        return {"success": False, "message": str(e)}


# Helper functions

def _check_duplicate_review(
    reviewer: str,
    review_type: str,
    listing: str = None,
    seller: str = None,
    order: str = None
) -> Optional[str]:
    """Check for existing review from same user."""
    filters = {
        "reviewer": reviewer,
        "review_type": review_type,
        "status": ["not in", ["Removed", "Rejected"]]
    }

    if listing:
        filters["listing"] = listing
    if seller and review_type == "Seller":
        filters["seller"] = seller
    if order:
        filters["marketplace_order"] = order

    return frappe.db.get_value("Review", filters, "name")


def _verify_purchase(
    reviewer: str,
    order: str,
    listing: str = None,
    seller: str = None
) -> Dict[str, Any]:
    """Verify that the reviewer made a purchase."""
    try:
        order_doc = frappe.get_doc("Marketplace Order", order)

        # Check order belongs to reviewer
        buyer_user = frappe.db.get_value("Buyer Profile", order_doc.buyer, "user")
        if buyer_user != reviewer:
            return {"is_verified": False}

        # Check order status (must be delivered/completed)
        if order_doc.status not in ["Delivered", "Completed"]:
            return {"is_verified": False}

        # Check listing/seller match if provided
        if listing:
            has_item = frappe.db.exists(
                "Marketplace Order Item",
                {"parent": order, "listing": listing}
            )
            if not has_item:
                return {"is_verified": False}

        return {
            "is_verified": True,
            "purchase_date": order_doc.creation
        }

    except Exception:
        return {"is_verified": False}


def _mask_name(name: str) -> str:
    """Mask a name for anonymous reviews."""
    if not name or len(name) < 2:
        return "A***"
    return name[0] + "***" + name[-1]


def _auto_moderate_review(review_name: str):
    """
    Run auto-moderation checks on a review.

    Checks for:
    - Profanity/offensive language
    - Spam patterns
    - Suspicious content
    """
    from tr_tradehub.reviews.moderation import auto_check_content

    review = frappe.get_doc("Review", review_name)

    # Run content checks
    result = auto_check_content(
        content=review.review_text or "",
        title=review.title or "",
        content_type="Review"
    )

    if result.get("flagged"):
        # Create moderation case
        from tr_tradehub.reviews.moderation import create_moderation_case

        create_moderation_case(
            content_type="Review",
            content_id=review_name,
            report_source="Auto Detection",
            report_reason=result.get("reason", "Auto-flagged content"),
            is_auto_detected=True,
            detection_method=result.get("detection_method", "Text Analysis"),
            detection_confidence=result.get("confidence", 0),
            detection_flags=result.get("flags", [])
        )


def _update_listing_ratings(listing: str):
    """Update aggregated ratings for a listing."""
    if not listing:
        return

    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as review_count,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star
        FROM `tabReview`
        WHERE listing = %s AND status = 'Published' AND review_type = 'Product'
    """, (listing,), as_dict=True)[0]

    frappe.db.set_value(
        "Listing",
        listing,
        {
            "review_count": stats.review_count or 0,
            "average_rating": flt(stats.average_rating, 2)
        },
        update_modified=False
    )


def _update_seller_ratings(seller: str):
    """Update aggregated ratings for a seller."""
    if not seller:
        return

    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as review_count,
            AVG(rating) as average_rating
        FROM `tabReview`
        WHERE seller = %s AND status = 'Published'
    """, (seller,), as_dict=True)[0]

    frappe.db.set_value(
        "Seller Profile",
        seller,
        {
            "total_reviews": stats.review_count or 0,
            "average_rating": flt(stats.average_rating, 2)
        },
        update_modified=False
    )


def _get_review_statistics(entity: str, entity_type: str) -> Dict[str, Any]:
    """Get review statistics for an entity."""
    if entity_type == "listing":
        filters = {"listing": entity, "status": "Published", "review_type": "Product"}
    else:
        filters = {"seller": entity, "status": "Published"}

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=["rating", "is_verified_purchase"]
    )

    if not reviews:
        return {
            "total_reviews": 0,
            "average_rating": 0,
            "verified_count": 0,
            "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        }

    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    verified_count = 0
    total_rating = 0

    for r in reviews:
        distribution[r.rating] = distribution.get(r.rating, 0) + 1
        total_rating += r.rating
        if r.is_verified_purchase:
            verified_count += 1

    return {
        "total_reviews": len(reviews),
        "average_rating": round(total_rating / len(reviews), 2),
        "verified_count": verified_count,
        "rating_distribution": distribution
    }


def _calculate_helpfulness_score(helpful: int, unhelpful: int) -> float:
    """
    Calculate helpfulness score using Wilson score interval.

    This gives a better ranking than simple helpful/total ratio,
    especially for reviews with few votes.
    """
    import math

    n = helpful + unhelpful
    if n == 0:
        return 0.0

    z = 1.96  # 95% confidence
    p = helpful / n

    # Wilson score interval lower bound
    score = (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)

    return round(score * 100, 2)
