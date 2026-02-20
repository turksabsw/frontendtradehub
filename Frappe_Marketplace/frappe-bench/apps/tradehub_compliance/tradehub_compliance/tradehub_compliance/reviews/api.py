# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Reviews & Moderation API Endpoints

REST API for review and moderation operations.
"""

import frappe
from frappe import _
from typing import Dict, Any
import json


def _response(success: bool, data: Any = None, message: str = None, errors: list = None) -> Dict:
    """Standard API response format."""
    return {
        "success": success,
        "data": data,
        "message": message,
        "errors": errors or []
    }


# ============= Review API =============

@frappe.whitelist()
def submit_review(
    review_type: str,
    rating: int,
    review_text: str,
    listing: str = None,
    seller: str = None,
    title: str = None,
    pros: str = None,
    cons: str = None,
    marketplace_order: str = None,
    images: str = None,
    is_anonymous: bool = False,
    detailed_ratings: str = None
) -> Dict:
    """
    Submit a new review.

    Args:
        review_type: Type of review (Product, Seller, Order Experience)
        rating: Overall rating (1-5)
        review_text: Review content
        listing: Listing being reviewed (for Product reviews)
        seller: Seller being reviewed (for Seller reviews)
        title: Review title
        pros: Positive aspects
        cons: Negative aspects
        marketplace_order: Order reference for verification
        images: JSON array of image URLs
        is_anonymous: Whether to hide identity
        detailed_ratings: JSON object with category ratings

    Returns:
        API response with review details
    """
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import submit_review as _submit_review

    # Parse JSON strings
    images_list = json.loads(images) if images else None
    detailed_ratings_dict = json.loads(detailed_ratings) if detailed_ratings else None

    result = _submit_review(
        reviewer=frappe.session.user,
        review_type=review_type,
        listing=listing,
        seller=seller,
        rating=int(rating),
        title=title,
        review_text=review_text,
        pros=pros,
        cons=cons,
        marketplace_order=marketplace_order,
        images=images_list,
        is_anonymous=is_anonymous,
        detailed_ratings=detailed_ratings_dict
    )

    return result


@frappe.whitelist()
def update_review(
    review_name: str,
    rating: int = None,
    title: str = None,
    review_text: str = None,
    pros: str = None,
    cons: str = None
) -> Dict:
    """Update an existing review."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import update_review as _update_review

    return _update_review(
        review_name=review_name,
        rating=int(rating) if rating else None,
        title=title,
        review_text=review_text,
        pros=pros,
        cons=cons
    )


@frappe.whitelist()
def delete_review(review_name: str) -> Dict:
    """Delete/remove a review."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import delete_review as _delete_review
    return _delete_review(review_name)


@frappe.whitelist()
def get_listing_reviews(
    listing: str,
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "helpful",
    rating_filter: int = None,
    verified_only: bool = False
) -> Dict:
    """Get reviews for a listing."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import get_reviews_for_listing

    return get_reviews_for_listing(
        listing=listing,
        limit=int(limit),
        offset=int(offset),
        sort_by=sort_by,
        rating_filter=int(rating_filter) if rating_filter else None,
        verified_only=verified_only
    )


@frappe.whitelist()
def get_seller_reviews(
    seller: str,
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "helpful"
) -> Dict:
    """Get reviews for a seller."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import get_reviews_for_seller

    return get_reviews_for_seller(
        seller=seller,
        limit=int(limit),
        offset=int(offset),
        sort_by=sort_by
    )


@frappe.whitelist()
def vote_review(review_name: str, is_helpful: bool) -> Dict:
    """Vote on review helpfulness."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import vote_helpful

    return vote_helpful(
        review_name=review_name,
        voter=frappe.session.user,
        is_helpful=is_helpful
    )


@frappe.whitelist()
def add_seller_response(review_name: str, response_text: str) -> Dict:
    """Add seller response to a review."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import add_seller_response as _add_response

    return _add_response(
        review_name=review_name,
        seller_user=frappe.session.user,
        response_text=response_text
    )


@frappe.whitelist()
def get_my_reviews() -> Dict:
    """Get current user's reviews."""
    try:
        reviews = frappe.get_all(
            "Review",
            filters={"reviewer": frappe.session.user},
            fields=[
                "name", "review_id", "review_type", "listing", "listing_title",
                "seller", "seller_name", "rating", "title", "status",
                "submitted_at", "published_at", "helpful_count"
            ],
            order_by="submitted_at desc"
        )

        return _response(True, data={"reviews": reviews})

    except Exception as e:
        return _response(False, message=str(e))


# ============= Moderation API =============

@frappe.whitelist()
def report_content(
    content_type: str,
    content_id: str,
    reason: str,
    description: str = None,
    evidence: str = None
) -> Dict:
    """
    Report content for moderation review.

    Args:
        content_type: DocType of content (Review, Listing, etc.)
        content_id: Document name
        reason: Report reason
        description: Detailed description
        evidence: Evidence file attachment

    Returns:
        API response with case details
    """
    from tradehub_compliance.tradehub_compliance.reviews.moderation import create_moderation_case

    result = create_moderation_case(
        content_type=content_type,
        content_id=content_id,
        report_source="User Report",
        reporter=frappe.session.user,
        report_reason=reason,
        report_description=description,
        report_evidence=evidence
    )

    return result


@frappe.whitelist()
def get_moderation_queue(
    status: str = None,
    priority: str = None,
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get moderation queue (for moderators).

    Args:
        status: Filter by status
        priority: Filter by priority
        limit: Number of cases
        offset: Pagination offset

    Returns:
        List of moderation cases
    """
    try:
        # Check moderator permission
        if not _is_moderator():
            return _response(False, message=_("Access denied"))

        filters = {}
        if status:
            filters["status"] = status
        else:
            filters["status"] = ["not in", ["Resolved", "Closed"]]

        if priority:
            filters["priority"] = priority

        cases = frappe.get_all(
            "Moderation Case",
            filters=filters,
            fields=[
                "name", "case_id", "case_type", "priority", "status",
                "content_type", "content_id", "content_title",
                "report_reason", "assigned_to", "creation_date",
                "sla_target_hours", "sla_status"
            ],
            order_by="FIELD(priority, 'Critical', 'High', 'Medium', 'Low'), creation_date asc",
            limit=int(limit),
            start=int(offset)
        )

        total = frappe.db.count("Moderation Case", filters)

        return _response(True, data={"cases": cases, "total": total})

    except Exception as e:
        return _response(False, message=str(e))


@frappe.whitelist()
def assign_case(case_name: str, moderator: str) -> Dict:
    """Assign a case to a moderator."""
    from tradehub_compliance.tradehub_compliance.reviews.moderation import assign_case as _assign_case

    if not _is_moderator():
        return _response(False, message=_("Access denied"))

    return _assign_case(
        case_name=case_name,
        moderator=moderator,
        assigner=frappe.session.user
    )


@frappe.whitelist()
def start_review(case_name: str) -> Dict:
    """Start reviewing a case."""
    try:
        if not _is_moderator():
            return _response(False, message=_("Access denied"))

        case = frappe.get_doc("Moderation Case", case_name)

        if case.status not in ["Open", "Assigned"]:
            return _response(False, message=_("Case cannot be started"))

        case.status = "In Review"
        case.review_started_at = frappe.utils.now_datetime()

        if not case.assigned_to:
            case.assigned_to = frappe.session.user
            case.assigned_at = frappe.utils.now_datetime()

        case.save(ignore_permissions=True)
        frappe.db.commit()

        return _response(True, message=_("Review started"))

    except Exception as e:
        return _response(False, message=str(e))


@frappe.whitelist()
def resolve_case(
    case_name: str,
    decision: str,
    decision_reason: str = None,
    decision_notes: str = None,
    action_taken: str = "None",
    content_action: str = "No Change",
    warning_issued: bool = False
) -> Dict:
    """Resolve a moderation case."""
    from tradehub_compliance.tradehub_compliance.reviews.moderation import resolve_case as _resolve_case

    if not _is_moderator():
        return _response(False, message=_("Access denied"))

    return _resolve_case(
        case_name=case_name,
        decision=decision,
        decision_reason=decision_reason,
        decision_notes=decision_notes,
        action_taken=action_taken,
        content_action=content_action,
        warning_issued=warning_issued
    )


@frappe.whitelist()
def escalate_case(
    case_name: str,
    escalation_level: str,
    escalate_to: str = None,
    reason: str = None
) -> Dict:
    """Escalate a moderation case."""
    from tradehub_compliance.tradehub_compliance.reviews.moderation import escalate_case as _escalate_case

    if not _is_moderator():
        return _response(False, message=_("Access denied"))

    return _escalate_case(
        case_name=case_name,
        escalation_level=escalation_level,
        escalate_to=escalate_to,
        reason=reason
    )


@frappe.whitelist()
def submit_appeal(case_name: str, appeal_reason: str, appeal_evidence: str = None) -> Dict:
    """Submit an appeal for a moderation decision."""
    from tradehub_compliance.tradehub_compliance.reviews.moderation import submit_appeal as _submit_appeal

    return _submit_appeal(
        case_name=case_name,
        appellant=frappe.session.user,
        appeal_reason=appeal_reason,
        appeal_evidence=appeal_evidence
    )


@frappe.whitelist()
def get_moderation_stats() -> Dict:
    """Get moderation statistics (for dashboard)."""
    try:
        if not _is_moderator():
            return _response(False, message=_("Access denied"))

        # Count by status
        status_counts = frappe.db.sql("""
            SELECT status, COUNT(*) as count
            FROM `tabModeration Case`
            GROUP BY status
        """, as_dict=True)

        # Count by priority
        priority_counts = frappe.db.sql("""
            SELECT priority, COUNT(*) as count
            FROM `tabModeration Case`
            WHERE status NOT IN ('Resolved', 'Closed')
            GROUP BY priority
        """, as_dict=True)

        # SLA stats
        sla_stats = frappe.db.sql("""
            SELECT
                SUM(CASE WHEN sla_status = 'On Track' THEN 1 ELSE 0 END) as on_track,
                SUM(CASE WHEN sla_status = 'At Risk' THEN 1 ELSE 0 END) as at_risk,
                SUM(CASE WHEN sla_status = 'Breached' THEN 1 ELSE 0 END) as breached,
                AVG(resolution_time_hours) as avg_resolution_hours
            FROM `tabModeration Case`
            WHERE status IN ('Resolved', 'Closed')
            AND creation_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, as_dict=True)[0]

        # Today's stats
        today_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_today,
                SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved_today
            FROM `tabModeration Case`
            WHERE DATE(creation_date) = CURDATE()
        """, as_dict=True)[0]

        return _response(True, data={
            "status_counts": {s["status"]: s["count"] for s in status_counts},
            "priority_counts": {p["priority"]: p["count"] for p in priority_counts},
            "sla_stats": sla_stats,
            "today_stats": today_stats
        })

    except Exception as e:
        return _response(False, message=str(e))


# ============= Review Moderation API =============

@frappe.whitelist()
def approve_review(review_name: str) -> Dict:
    """Approve and publish a review."""
    from tradehub_compliance.tradehub_compliance.reviews.review_manager import publish_review

    if not _is_moderator():
        return _response(False, message=_("Access denied"))

    return publish_review(review_name, moderator=frappe.session.user)


@frappe.whitelist()
def reject_review(review_name: str, reason: str = None, notes: str = None) -> Dict:
    """Reject a review."""
    try:
        if not _is_moderator():
            return _response(False, message=_("Access denied"))

        review = frappe.get_doc("Review", review_name)

        review.status = "Rejected"
        review.moderation_status = "Rejected"
        review.rejection_reason = reason
        review.moderation_notes = notes
        review.moderated_by = frappe.session.user
        review.moderated_at = frappe.utils.now_datetime()

        review.save(ignore_permissions=True)
        frappe.db.commit()

        return _response(True, message=_("Review rejected"))

    except Exception as e:
        return _response(False, message=str(e))


@frappe.whitelist()
def get_pending_reviews(limit: int = 20, offset: int = 0) -> Dict:
    """Get reviews pending moderation."""
    try:
        if not _is_moderator():
            return _response(False, message=_("Access denied"))

        reviews = frappe.get_all(
            "Review",
            filters={"status": "Pending Review", "moderation_status": "Pending"},
            fields=[
                "name", "review_id", "review_type", "rating", "title",
                "review_text", "listing", "listing_title", "seller",
                "reviewer", "is_verified_purchase", "submitted_at"
            ],
            order_by="submitted_at asc",
            limit=int(limit),
            start=int(offset)
        )

        total = frappe.db.count("Review", {
            "status": "Pending Review",
            "moderation_status": "Pending"
        })

        return _response(True, data={"reviews": reviews, "total": total})

    except Exception as e:
        return _response(False, message=str(e))


# Helper functions

def _is_moderator() -> bool:
    """Check if current user is a moderator."""
    roles = frappe.get_roles()
    return any(r in roles for r in ["System Manager", "Marketplace Admin", "Marketplace Moderator"])
