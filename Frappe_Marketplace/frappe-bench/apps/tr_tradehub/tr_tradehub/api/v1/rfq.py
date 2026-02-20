# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub RFQ API v1.

This module provides a comprehensive REST API for the RFQ (Request for Quotation)
workflow in the Trade Hub B2B marketplace. It enables buyers to create RFQs,
invite sellers, receive and compare quotations, and select winners.

Key Features:
- Complete RFQ lifecycle management (create, publish, evaluate, close)
- Seller invitation and notification
- Quotation submission and management
- Quotation comparison and analytics
- Multi-tenant data isolation

Usage Flow (Buyer):
1. create_rfq() - Create a new RFQ with items
2. add_rfq_items() - Add more items to draft RFQ
3. invite_sellers() - Invite specific sellers to respond
4. publish_rfq() - Make RFQ active and visible to sellers
5. get_rfq_quotations() - View received quotations
6. compare_rfq_quotations() - Compare quotations side-by-side
7. select_quotation() - Select winning quotation
8. create_order_from_rfq() - Create order from selected quotation

Usage Flow (Seller):
1. get_active_rfqs() - Browse active RFQs
2. get_rfq_details() - View RFQ details
3. submit_quote() - Submit a quotation for an RFQ
4. update_quote() - Update draft quotation
5. get_my_quotations() - View submitted quotations
"""

import json
from typing import Optional, Dict, Any, List

import frappe
from frappe import _
from frappe.utils import (
    cint, flt, nowdate, now_datetime, get_datetime, getdate, add_days
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# RFQ Types
RFQ_TYPES = ["Standard", "Urgent", "Bulk", "Custom Production", "Sample First"]

# RFQ Statuses
RFQ_STATUSES = ["Draft", "Active", "Evaluating", "Closed", "Cancelled", "Expired"]

# Quotation Statuses
QUOTATION_STATUSES = [
    "Draft", "Submitted", "Under Review", "Selected", "Rejected", "Expired", "Cancelled"
]

# Incoterms
INCOTERMS = ["EXW", "FOB", "CIF", "DDP", "FCA", "CPT", "CIP", "DAP", "DPU"]

# Payment Terms
PAYMENT_TERMS = [
    "Prepayment", "Net 30", "Net 60", "Net 90",
    "50% Advance 50% Delivery", "Letter of Credit", "Custom"
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


def get_user_buyer_profile() -> Optional[str]:
    """Get the Buyer Profile for the current user."""
    return frappe.db.get_value(
        "Buyer Profile",
        {"user": frappe.session.user, "status": ["in", ["Active", "Verified"]]},
        "name"
    )


def get_user_seller_profile() -> Optional[str]:
    """Get the Seller Profile for the current user."""
    return frappe.db.get_value(
        "Seller Profile",
        {"user": frappe.session.user, "status": ["in", ["Active", "Verified"]]},
        "name"
    )


def validate_buyer_access(buyer: str = None):
    """Validate that current user has access to buyer operations."""
    if "System Manager" in frappe.get_roles():
        return True

    user_buyer = get_user_buyer_profile()
    if not user_buyer:
        frappe.throw(_("You do not have a valid Buyer Profile"))

    if buyer and user_buyer != buyer:
        frappe.throw(_("Access denied: You can only access your own buyer profile"))

    return user_buyer


def validate_seller_access(seller: str = None):
    """Validate that current user has access to seller operations."""
    if "System Manager" in frappe.get_roles():
        return True

    user_seller = get_user_seller_profile()
    if not user_seller:
        frappe.throw(_("You do not have a valid Seller Profile"))

    if seller and user_seller != seller:
        frappe.throw(_("Access denied: You can only access your own seller profile"))

    return user_seller


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
# RFQ LISTING AND SEARCH APIs (GET)
# =============================================================================

@frappe.whitelist()
def get_rfq_list(
    buyer: str = None,
    status: str = None,
    rfq_type: str = None,
    category: str = None,
    tenant: str = None,
    search: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get a paginated list of RFQs with optional filters.

    This is the primary endpoint for listing RFQs, used by both buyers
    (to manage their RFQs) and sellers (to find opportunities).

    Args:
        buyer: Filter by Buyer Profile name
        status: Filter by status (Draft, Active, Evaluating, Closed, etc.)
        rfq_type: Filter by RFQ type (Standard, Urgent, Bulk, etc.)
        category: Filter by Product Category
        tenant: Filter by tenant (multi-tenant support)
        search: Search in title and description
        date_from: Filter RFQs created on or after this date
        date_to: Filter RFQs created on or before this date
        limit: Number of records per page (default 20, max 100)
        offset: Starting position for pagination

    Returns:
        dict: {
            "success": True,
            "rfqs": [...],
            "count": int,
            "limit": int,
            "offset": int,
            "has_more": bool
        }
    """
    limit, offset = validate_page_params(limit, offset)

    filters = {}
    or_filters = {}

    # Apply filters
    if buyer:
        filters["buyer"] = buyer
    if status:
        if status in RFQ_STATUSES:
            filters["status"] = status
        else:
            frappe.throw(_("Invalid status. Must be one of: {0}").format(
                ", ".join(RFQ_STATUSES)
            ))
    if rfq_type:
        filters["rfq_type"] = rfq_type
    if category:
        filters["category"] = category
    if tenant:
        filters["tenant"] = tenant
    elif not "System Manager" in frappe.get_roles():
        # Apply tenant filter for non-admin users
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    # Date filters
    if date_from:
        filters["rfq_date"] = [">=", date_from]
    if date_to:
        if date_from:
            filters["rfq_date"] = ["between", [date_from, date_to]]
        else:
            filters["rfq_date"] = ["<=", date_to]

    # Search filter
    if search:
        or_filters = [
            ["title", "like", f"%{search}%"],
            ["description", "like", f"%{search}%"]
        ]

    # Get RFQs
    rfqs = frappe.get_all(
        "RFQ",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=[
            "name", "title", "status", "rfq_type", "rfq_date",
            "submission_deadline", "buyer", "buyer_name", "buyer_company",
            "category", "category_name", "delivery_country",
            "required_delivery_date", "preferred_currency",
            "estimated_budget", "budget_visibility",
            "total_quotations", "lowest_quote", "highest_quote",
            "priority", "tenant"
        ],
        order_by="rfq_date desc, creation desc",
        start=offset,
        page_length=limit + 1  # Get one extra to check if there are more
    )

    has_more = len(rfqs) > limit
    if has_more:
        rfqs = rfqs[:limit]

    return {
        "success": True,
        "rfqs": rfqs,
        "count": len(rfqs),
        "limit": limit,
        "offset": offset,
        "has_more": has_more
    }


@frappe.whitelist()
def get_active_rfqs(
    seller: str = None,
    category: str = None,
    rfq_type: str = None,
    min_budget: float = None,
    delivery_country: str = None,
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get active RFQs available for sellers to respond to.

    This endpoint is optimized for sellers browsing RFQ opportunities.
    It only returns RFQs that are Active and have not passed their deadline.

    Args:
        seller: Optional seller name to check invitation status
        category: Filter by Product Category
        rfq_type: Filter by RFQ type
        min_budget: Minimum estimated budget
        delivery_country: Filter by delivery country
        limit: Number of records per page
        offset: Starting position

    Returns:
        dict: {
            "success": True,
            "rfqs": [...],
            "count": int,
            "has_more": bool
        }
    """
    limit, offset = validate_page_params(limit, offset)

    filters = {
        "status": "Active",
        "submission_deadline": [">=", now_datetime()]
    }

    if category:
        filters["category"] = category
    if rfq_type:
        filters["rfq_type"] = rfq_type
    if min_budget:
        filters["estimated_budget"] = [">=", flt(min_budget)]
    if delivery_country:
        filters["delivery_country"] = delivery_country

    # Apply tenant filter
    if not "System Manager" in frappe.get_roles():
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    rfqs = frappe.get_all(
        "RFQ",
        filters=filters,
        fields=[
            "name", "title", "rfq_type", "rfq_date",
            "submission_deadline", "buyer_company",
            "category", "category_name", "delivery_country",
            "delivery_city", "required_delivery_date",
            "preferred_currency", "estimated_budget",
            "budget_visibility", "priority"
        ],
        order_by="priority desc, submission_deadline asc",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(rfqs) > limit
    if has_more:
        rfqs = rfqs[:limit]

    # Add invitation and quotation status if seller provided
    if seller:
        for rfq in rfqs:
            # Check if invited
            rfq["is_invited"] = bool(frappe.db.exists(
                "RFQ Invited Seller",
                {"parent": rfq["name"], "seller": seller}
            ))
            # Check if already quoted
            rfq["has_quoted"] = bool(frappe.db.exists(
                "Quotation",
                {"rfq": rfq["name"], "seller": seller, "status": ["!=", "Cancelled"]}
            ))

    return {
        "success": True,
        "rfqs": rfqs,
        "count": len(rfqs),
        "limit": limit,
        "offset": offset,
        "has_more": has_more
    }


@frappe.whitelist()
def get_rfq_details(rfq_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific RFQ.

    Returns the full RFQ document with items, invited sellers,
    and quotation summary. Used for viewing RFQ details page.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "success": True,
            "rfq": {...},
            "items": [...],
            "invited_sellers": [...],
            "quotation_summary": {...}
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    rfq = frappe.get_doc("RFQ", rfq_name)

    # Get items
    items = frappe.get_all(
        "RFQ Item",
        filters={"parent": rfq_name},
        fields=[
            "name", "idx", "sku_product", "product_name", "product_sku_code",
            "variant", "variant_name", "quantity", "uom",
            "target_unit_price", "currency",
            "item_description", "specifications", "required_certifications"
        ],
        order_by="idx"
    )

    # Get invited sellers
    invited_sellers = frappe.get_all(
        "RFQ Invited Seller",
        filters={"parent": rfq_name},
        fields=[
            "seller", "seller_name", "invitation_date",
            "invitation_message", "status", "response_date"
        ],
        order_by="invitation_date"
    )

    # Get quotation summary
    quotations = frappe.get_all(
        "Quotation",
        filters={"rfq": rfq_name, "status": ["not in", ["Draft", "Cancelled"]]},
        fields=["name", "seller_name", "total_amount", "status", "delivery_days"]
    )

    amounts = [flt(q.total_amount) for q in quotations if q.total_amount]
    quotation_summary = {
        "total_quotations": len(quotations),
        "lowest_quote": min(amounts) if amounts else None,
        "highest_quote": max(amounts) if amounts else None,
        "average_quote": sum(amounts) / len(amounts) if amounts else None,
        "quotations_by_status": {}
    }

    for q in quotations:
        status = q.status
        if status not in quotation_summary["quotations_by_status"]:
            quotation_summary["quotations_by_status"][status] = 0
        quotation_summary["quotations_by_status"][status] += 1

    return {
        "success": True,
        "rfq": rfq.as_dict(),
        "items": items,
        "invited_sellers": invited_sellers,
        "quotation_summary": quotation_summary
    }


@frappe.whitelist()
def get_my_rfqs(
    status: str = None,
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get RFQs created by the current user (buyer).

    Convenience endpoint for buyers to view their own RFQs.

    Args:
        status: Filter by status
        limit: Number of records per page
        offset: Starting position

    Returns:
        dict: List of RFQs owned by current user
    """
    buyer = validate_buyer_access()

    return get_rfq_list(
        buyer=buyer,
        status=status,
        limit=limit,
        offset=offset
    )


# =============================================================================
# RFQ CREATION AND MANAGEMENT APIs
# =============================================================================

@frappe.whitelist()
def create_rfq(
    title: str,
    description: str,
    submission_deadline: str,
    buyer: str = None,
    rfq_type: str = "Standard",
    category: str = None,
    items: str = None,
    delivery_location: str = None,
    delivery_city: str = None,
    delivery_country: str = None,
    required_delivery_date: str = None,
    incoterm: str = None,
    preferred_currency: str = "USD",
    estimated_budget: float = None,
    budget_visibility: str = "Hidden",
    priority: str = "Normal",
    evaluation_criteria: str = None,
    additional_requirements: str = None,
    publish: int = 0
) -> Dict[str, Any]:
    """
    Create a new RFQ.

    Creates a new Request for Quotation. The RFQ starts in Draft status
    unless publish=1 is specified.

    Args:
        title: RFQ title (required)
        description: Detailed RFQ description (required)
        submission_deadline: Deadline for quotation submissions (required)
        buyer: Buyer Profile name (optional, defaults to current user's buyer profile)
        rfq_type: Type of RFQ (Standard, Urgent, Bulk, Custom Production, Sample First)
        category: Product Category
        items: JSON array of items (each with sku_product, quantity, etc.)
        delivery_location: Delivery address
        delivery_city: Delivery city
        delivery_country: Delivery country
        required_delivery_date: When goods are needed
        incoterm: Preferred Incoterm
        preferred_currency: Currency (default USD)
        estimated_budget: Estimated budget amount
        budget_visibility: How to display budget (Hidden, Range, Exact)
        priority: Priority level (Low, Normal, High, Urgent)
        evaluation_criteria: How quotations will be evaluated
        additional_requirements: Any additional requirements
        publish: Set to 1 to immediately publish the RFQ

    Returns:
        dict: {
            "success": True,
            "name": "RFQ-00001",
            "status": "Draft" | "Active",
            "message": str
        }
    """
    # Validate buyer
    if not buyer:
        buyer = validate_buyer_access()

    # Validate required fields
    if not title:
        frappe.throw(_("Title is required"))
    if not description:
        frappe.throw(_("Description is required"))
    if not submission_deadline:
        frappe.throw(_("Submission Deadline is required"))

    # Validate deadline is in future
    deadline_dt = get_datetime(submission_deadline)
    if deadline_dt <= now_datetime():
        frappe.throw(_("Submission Deadline must be in the future"))

    # Parse items
    items_list = parse_json_param(items, "items")

    # Create RFQ
    doc = frappe.new_doc("RFQ")
    doc.buyer = buyer
    doc.title = title
    doc.description = description
    doc.submission_deadline = submission_deadline
    doc.rfq_type = rfq_type
    doc.category = category
    doc.delivery_location = delivery_location
    doc.delivery_city = delivery_city
    doc.delivery_country = delivery_country
    doc.required_delivery_date = required_delivery_date
    doc.incoterm = incoterm
    doc.preferred_currency = preferred_currency
    doc.estimated_budget = flt(estimated_budget) if estimated_budget else None
    doc.budget_visibility = budget_visibility
    doc.priority = priority
    doc.evaluation_criteria = evaluation_criteria
    doc.additional_requirements = additional_requirements

    # Add items if provided
    if items_list:
        for item in items_list:
            doc.append("items", {
                "sku_product": item.get("sku_product"),
                "variant": item.get("variant"),
                "quantity": flt(item.get("quantity", 1)),
                "uom": item.get("uom"),
                "target_unit_price": flt(item.get("target_unit_price")) if item.get("target_unit_price") else None,
                "currency": item.get("currency", preferred_currency),
                "item_description": item.get("item_description"),
                "specifications": item.get("specifications"),
                "required_certifications": item.get("required_certifications")
            })

    doc.insert()

    # Publish if requested
    if cint(publish):
        doc.publish()

    return {
        "success": True,
        "name": doc.name,
        "status": doc.status,
        "message": _("RFQ created successfully")
    }


@frappe.whitelist()
def add_rfq_items(rfq_name: str, items: str) -> Dict[str, Any]:
    """
    Add items to an existing RFQ.

    Only works for Draft RFQs. Use this to add more items
    after initial RFQ creation.

    Args:
        rfq_name: The RFQ document name
        items: JSON array of items to add

    Returns:
        dict: {
            "success": True,
            "items_added": int,
            "total_items": int
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    doc = frappe.get_doc("RFQ", rfq_name)

    if doc.status != "Draft":
        frappe.throw(_("Can only add items to Draft RFQs"))

    # Validate buyer access
    validate_buyer_access(doc.buyer)

    items_list = parse_json_param(items, "items")
    if not items_list:
        frappe.throw(_("Items are required"))

    items_added = 0
    for item in items_list:
        doc.append("items", {
            "sku_product": item.get("sku_product"),
            "variant": item.get("variant"),
            "quantity": flt(item.get("quantity", 1)),
            "uom": item.get("uom"),
            "target_unit_price": flt(item.get("target_unit_price")) if item.get("target_unit_price") else None,
            "currency": item.get("currency", doc.preferred_currency),
            "item_description": item.get("item_description"),
            "specifications": item.get("specifications"),
            "required_certifications": item.get("required_certifications")
        })
        items_added += 1

    doc.save()

    return {
        "success": True,
        "items_added": items_added,
        "total_items": len(doc.items)
    }


@frappe.whitelist()
def publish_rfq(rfq_name: str) -> Dict[str, Any]:
    """
    Publish an RFQ to make it active and visible to sellers.

    Validates that all required fields are present before publishing.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "success": True,
            "status": "Active",
            "published_date": datetime
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    doc = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(doc.buyer)

    doc.publish()

    return {
        "success": True,
        "status": doc.status,
        "published_date": doc.published_date,
        "message": _("RFQ published successfully")
    }


@frappe.whitelist()
def update_rfq(
    rfq_name: str,
    title: str = None,
    description: str = None,
    submission_deadline: str = None,
    rfq_type: str = None,
    category: str = None,
    delivery_location: str = None,
    delivery_city: str = None,
    delivery_country: str = None,
    required_delivery_date: str = None,
    incoterm: str = None,
    estimated_budget: float = None,
    budget_visibility: str = None,
    priority: str = None,
    evaluation_criteria: str = None,
    additional_requirements: str = None
) -> Dict[str, Any]:
    """
    Update an existing RFQ.

    Only Draft RFQs can be fully updated. Active RFQs can only
    have their deadline extended.

    Args:
        rfq_name: The RFQ document name
        [other fields]: Fields to update

    Returns:
        dict: Updated RFQ info
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    doc = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(doc.buyer)

    if doc.status == "Draft":
        # Full update allowed for draft
        if title:
            doc.title = title
        if description:
            doc.description = description
        if submission_deadline:
            doc.submission_deadline = submission_deadline
        if rfq_type:
            doc.rfq_type = rfq_type
        if category:
            doc.category = category
        if delivery_location:
            doc.delivery_location = delivery_location
        if delivery_city:
            doc.delivery_city = delivery_city
        if delivery_country:
            doc.delivery_country = delivery_country
        if required_delivery_date:
            doc.required_delivery_date = required_delivery_date
        if incoterm:
            doc.incoterm = incoterm
        if estimated_budget is not None:
            doc.estimated_budget = flt(estimated_budget)
        if budget_visibility:
            doc.budget_visibility = budget_visibility
        if priority:
            doc.priority = priority
        if evaluation_criteria:
            doc.evaluation_criteria = evaluation_criteria
        if additional_requirements:
            doc.additional_requirements = additional_requirements

        doc.save()

    elif doc.status == "Active":
        # Only deadline extension allowed for active RFQs
        if submission_deadline:
            new_deadline = get_datetime(submission_deadline)
            old_deadline = get_datetime(doc.submission_deadline)
            if new_deadline > old_deadline:
                doc.submission_deadline = submission_deadline
                doc.save()
            else:
                frappe.throw(_("New deadline must be after current deadline"))
        else:
            frappe.throw(_("Only deadline can be extended for Active RFQs"))
    else:
        frappe.throw(_("Cannot update RFQ with status {0}").format(doc.status))

    return {
        "success": True,
        "name": doc.name,
        "status": doc.status,
        "message": _("RFQ updated successfully")
    }


@frappe.whitelist()
def cancel_rfq(rfq_name: str, reason: str = None) -> Dict[str, Any]:
    """
    Cancel an RFQ.

    Can cancel Draft, Active, or Evaluating RFQs.
    Cannot cancel Closed RFQs.

    Args:
        rfq_name: The RFQ document name
        reason: Optional cancellation reason

    Returns:
        dict: {
            "success": True,
            "status": "Cancelled"
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    doc = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(doc.buyer)

    doc.cancel(reason)

    return {
        "success": True,
        "status": doc.status,
        "message": _("RFQ cancelled")
    }


@frappe.whitelist()
def extend_rfq_deadline(
    rfq_name: str,
    new_deadline: str,
    reason: str = None
) -> Dict[str, Any]:
    """
    Extend the submission deadline for an RFQ.

    Args:
        rfq_name: The RFQ document name
        new_deadline: New submission deadline
        reason: Optional reason for extension

    Returns:
        dict: {
            "success": True,
            "new_deadline": datetime
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))
    if not new_deadline:
        frappe.throw(_("New deadline is required"))

    doc = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(doc.buyer)

    if doc.status not in ["Draft", "Active"]:
        frappe.throw(_("Cannot extend deadline for {0} RFQs").format(doc.status))

    new_deadline_dt = get_datetime(new_deadline)
    old_deadline_dt = get_datetime(doc.submission_deadline)

    if new_deadline_dt <= old_deadline_dt:
        frappe.throw(_("New deadline must be after current deadline"))

    if new_deadline_dt <= now_datetime():
        frappe.throw(_("New deadline must be in the future"))

    doc.submission_deadline = new_deadline

    if reason:
        doc.internal_notes = (doc.internal_notes or "") + \
            f"\nDeadline extended to {new_deadline}: {reason}"

    doc.save()

    return {
        "success": True,
        "new_deadline": doc.submission_deadline,
        "message": _("Deadline extended successfully")
    }


# =============================================================================
# SELLER INVITATION APIs
# =============================================================================

@frappe.whitelist()
def invite_sellers(
    rfq_name: str,
    sellers: str,
    message: str = None
) -> Dict[str, Any]:
    """
    Invite one or more sellers to respond to an RFQ.

    Sends invitations to the specified sellers. Sellers will receive
    notifications about the RFQ invitation.

    Args:
        rfq_name: The RFQ document name
        sellers: JSON array of Seller Profile names
        message: Optional invitation message to all sellers

    Returns:
        dict: {
            "success": True,
            "invited": [...],
            "already_invited": [...],
            "invalid": [...]
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    doc = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(doc.buyer)

    if doc.status != "Active":
        frappe.throw(_("Can only invite sellers to Active RFQs"))

    sellers_list = parse_json_param(sellers, "sellers")
    if not sellers_list:
        frappe.throw(_("At least one seller is required"))

    invited = []
    already_invited = []
    invalid = []

    for seller_name in sellers_list:
        # Check if seller exists and is valid
        seller_status = frappe.db.get_value(
            "Seller Profile", seller_name, "status"
        )
        if not seller_status or seller_status not in ["Active", "Verified"]:
            invalid.append(seller_name)
            continue

        # Check if already invited
        existing = frappe.db.exists(
            "RFQ Invited Seller",
            {"parent": rfq_name, "seller": seller_name}
        )
        if existing:
            already_invited.append(seller_name)
            continue

        # Add invitation
        doc.append("invited_sellers", {
            "seller": seller_name,
            "invitation_date": now_datetime(),
            "invitation_message": message,
            "status": "Invited"
        })
        invited.append(seller_name)

    if invited:
        doc.save()

        # Future: Send notification emails to invited sellers
        # for seller_name in invited:
        #     send_rfq_invitation_email(seller_name, rfq_name)

    return {
        "success": True,
        "invited": invited,
        "already_invited": already_invited,
        "invalid": invalid,
        "message": _("{0} seller(s) invited successfully").format(len(invited))
    }


@frappe.whitelist()
def get_invited_sellers(rfq_name: str) -> Dict[str, Any]:
    """
    Get list of sellers invited to an RFQ.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "success": True,
            "sellers": [...],
            "total": int
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    sellers = frappe.get_all(
        "RFQ Invited Seller",
        filters={"parent": rfq_name},
        fields=[
            "seller", "seller_name", "invitation_date",
            "invitation_message", "status", "response_date"
        ],
        order_by="invitation_date"
    )

    # Add quotation status for each seller
    for seller in sellers:
        quotation = frappe.db.get_value(
            "Quotation",
            {"rfq": rfq_name, "seller": seller["seller"], "status": ["!=", "Cancelled"]},
            ["name", "status", "total_amount"],
            as_dict=True
        )
        if quotation:
            seller["quotation"] = quotation["name"]
            seller["quotation_status"] = quotation["status"]
            seller["quotation_amount"] = quotation["total_amount"]
        else:
            seller["quotation"] = None
            seller["quotation_status"] = None
            seller["quotation_amount"] = None

    return {
        "success": True,
        "sellers": sellers,
        "total": len(sellers)
    }


# =============================================================================
# QUOTATION SUBMISSION APIs (Seller)
# =============================================================================

@frappe.whitelist()
def submit_quote(
    rfq_name: str,
    seller: str = None,
    items: str = None,
    validity_date: str = None,
    currency: str = "USD",
    incoterm: str = "EXW",
    delivery_days: int = None,
    payment_terms: str = None,
    payment_description: str = None,
    advance_percentage: float = 0,
    shipping_cost: float = 0,
    tax_amount: float = 0,
    discount_percentage: float = 0,
    seller_notes: str = None,
    production_time_days: int = None,
    production_notes: str = None,
    minimum_order_quantity: int = None,
    submit: int = 0
) -> Dict[str, Any]:
    """
    Submit a quotation for an RFQ.

    This is the primary endpoint for sellers to submit their quotations.
    Creates a quotation in Draft status unless submit=1 is specified.

    Args:
        rfq_name: The RFQ to respond to (required)
        seller: Seller Profile name (optional, defaults to current user's seller profile)
        items: JSON array of quotation items, each with:
            - sku_product: SKU Product name
            - variant: Product Variant name (optional)
            - quantity: Quantity being quoted
            - unit_price: Price per unit
            - notes: Item-specific notes
        validity_date: Date until which quotation is valid
        currency: Currency code (default USD)
        incoterm: Incoterm (default EXW)
        delivery_days: Estimated delivery days from order
        payment_terms: Payment terms
        payment_description: Custom payment terms description
        advance_percentage: Advance payment percentage (0-100)
        shipping_cost: Shipping cost
        tax_amount: Tax amount
        discount_percentage: Discount percentage (0-100)
        seller_notes: Notes to buyer
        production_time_days: Production time in days
        production_notes: Production notes
        minimum_order_quantity: Minimum order quantity
        submit: Set to 1 to immediately submit the quotation

    Returns:
        dict: {
            "success": True,
            "name": "QUO-...",
            "quotation_number": str,
            "status": "Draft" | "Submitted",
            "total_amount": float
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    # Validate seller
    if not seller:
        seller = validate_seller_access()

    # Check RFQ is valid for quotation
    rfq = frappe.get_doc("RFQ", rfq_name)
    if rfq.status not in ["Active", "Evaluating"]:
        frappe.throw(_("Cannot submit quotation for {0} RFQ").format(rfq.status))

    # Check deadline (for new quotations)
    if rfq.status == "Active":
        deadline = get_datetime(rfq.submission_deadline)
        if deadline < now_datetime():
            frappe.throw(_("RFQ submission deadline has passed"))

    # Check if seller already has a quotation
    existing = frappe.db.exists(
        "Quotation",
        {"rfq": rfq_name, "seller": seller, "status": ["!=", "Cancelled"]}
    )
    if existing:
        frappe.throw(_("You have already submitted a quotation for this RFQ"))

    # Parse items
    items_list = parse_json_param(items, "items")
    if not items_list:
        frappe.throw(_("At least one item is required"))

    # Default validity date to 30 days if not provided
    if not validity_date:
        validity_date = add_days(nowdate(), 30)

    # Create quotation
    doc = frappe.new_doc("Quotation")
    doc.rfq = rfq_name
    doc.seller = seller
    doc.validity_date = validity_date
    doc.currency = currency
    doc.incoterm = incoterm
    doc.delivery_days = cint(delivery_days) if delivery_days else None
    doc.payment_terms = payment_terms
    doc.payment_description = payment_description
    doc.advance_percentage = flt(advance_percentage)
    doc.shipping_cost = flt(shipping_cost)
    doc.tax_amount = flt(tax_amount)
    doc.discount_percentage = flt(discount_percentage)
    doc.seller_notes = seller_notes
    doc.production_time_days = cint(production_time_days) if production_time_days else None
    doc.production_notes = production_notes
    doc.minimum_order_quantity = cint(minimum_order_quantity) if minimum_order_quantity else None

    # Add items
    for item in items_list:
        doc.append("items", {
            "sku_product": item.get("sku_product"),
            "variant": item.get("variant"),
            "quantity": flt(item.get("quantity", 1)),
            "unit_price": flt(item.get("unit_price", 0)),
            "notes": item.get("notes"),
            "lead_time_days": cint(item.get("lead_time_days")) if item.get("lead_time_days") else None,
            "available_stock": flt(item.get("available_stock")) if item.get("available_stock") else None,
            "moq": cint(item.get("moq")) if item.get("moq") else None,
            "max_quantity": cint(item.get("max_quantity")) if item.get("max_quantity") else None
        })

    doc.insert()

    # Submit if requested
    if cint(submit):
        doc.submit_quotation()

    # Update invited seller status if applicable
    invited_seller = frappe.db.exists(
        "RFQ Invited Seller",
        {"parent": rfq_name, "seller": seller}
    )
    if invited_seller:
        frappe.db.set_value(
            "RFQ Invited Seller", invited_seller,
            {
                "status": "Responded",
                "response_date": now_datetime()
            }
        )

    return {
        "success": True,
        "name": doc.name,
        "quotation_number": doc.quotation_number,
        "status": doc.status,
        "total_amount": doc.total_amount,
        "message": _("Quotation created successfully")
    }


@frappe.whitelist()
def update_quote(
    quotation_name: str,
    items: str = None,
    validity_date: str = None,
    currency: str = None,
    incoterm: str = None,
    delivery_days: int = None,
    payment_terms: str = None,
    payment_description: str = None,
    advance_percentage: float = None,
    shipping_cost: float = None,
    tax_amount: float = None,
    discount_percentage: float = None,
    seller_notes: str = None,
    production_time_days: int = None,
    production_notes: str = None,
    minimum_order_quantity: int = None
) -> Dict[str, Any]:
    """
    Update a draft quotation.

    Only Draft quotations can be updated. For submitted quotations,
    the seller must cancel and resubmit.

    Args:
        quotation_name: The Quotation document name
        [other fields]: Fields to update

    Returns:
        dict: Updated quotation info
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    doc = frappe.get_doc("Quotation", quotation_name)

    if doc.status != "Draft":
        frappe.throw(_("Can only update Draft quotations"))

    validate_seller_access(doc.seller)

    # Update fields
    if validity_date:
        doc.validity_date = validity_date
    if currency:
        doc.currency = currency
    if incoterm:
        doc.incoterm = incoterm
    if delivery_days is not None:
        doc.delivery_days = cint(delivery_days)
    if payment_terms:
        doc.payment_terms = payment_terms
    if payment_description:
        doc.payment_description = payment_description
    if advance_percentage is not None:
        doc.advance_percentage = flt(advance_percentage)
    if shipping_cost is not None:
        doc.shipping_cost = flt(shipping_cost)
    if tax_amount is not None:
        doc.tax_amount = flt(tax_amount)
    if discount_percentage is not None:
        doc.discount_percentage = flt(discount_percentage)
    if seller_notes:
        doc.seller_notes = seller_notes
    if production_time_days is not None:
        doc.production_time_days = cint(production_time_days)
    if production_notes:
        doc.production_notes = production_notes
    if minimum_order_quantity is not None:
        doc.minimum_order_quantity = cint(minimum_order_quantity)

    # Update items if provided
    if items:
        items_list = parse_json_param(items, "items")
        doc.items = []
        for item in items_list:
            doc.append("items", {
                "sku_product": item.get("sku_product"),
                "variant": item.get("variant"),
                "quantity": flt(item.get("quantity", 1)),
                "unit_price": flt(item.get("unit_price", 0)),
                "notes": item.get("notes"),
                "lead_time_days": cint(item.get("lead_time_days")) if item.get("lead_time_days") else None,
                "available_stock": flt(item.get("available_stock")) if item.get("available_stock") else None,
                "moq": cint(item.get("moq")) if item.get("moq") else None,
                "max_quantity": cint(item.get("max_quantity")) if item.get("max_quantity") else None
            })

    doc.save()

    return {
        "success": True,
        "name": doc.name,
        "status": doc.status,
        "total_amount": doc.total_amount,
        "message": _("Quotation updated successfully")
    }


@frappe.whitelist()
def submit_quotation(quotation_name: str) -> Dict[str, Any]:
    """
    Submit a draft quotation to the buyer.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: {
            "success": True,
            "status": "Submitted"
        }
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    doc = frappe.get_doc("Quotation", quotation_name)
    validate_seller_access(doc.seller)

    doc.submit_quotation()

    return {
        "success": True,
        "status": doc.status,
        "message": _("Quotation submitted successfully")
    }


@frappe.whitelist()
def withdraw_quotation(quotation_name: str, reason: str = None) -> Dict[str, Any]:
    """
    Withdraw (cancel) a quotation.

    Sellers can withdraw their quotations before they are selected.

    Args:
        quotation_name: The Quotation document name
        reason: Optional withdrawal reason

    Returns:
        dict: {
            "success": True,
            "status": "Cancelled"
        }
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    doc = frappe.get_doc("Quotation", quotation_name)
    validate_seller_access(doc.seller)

    doc.cancel(reason)

    return {
        "success": True,
        "status": doc.status,
        "message": _("Quotation withdrawn")
    }


@frappe.whitelist()
def get_my_quotations(
    status: str = None,
    rfq: str = None,
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Get quotations submitted by the current user (seller).

    Args:
        status: Filter by status
        rfq: Filter by RFQ
        limit: Number of records per page
        offset: Starting position

    Returns:
        dict: List of quotations by current seller
    """
    seller = validate_seller_access()
    limit, offset = validate_page_params(limit, offset)

    filters = {"seller": seller}
    if status:
        filters["status"] = status
    if rfq:
        filters["rfq"] = rfq

    quotations = frappe.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "quotation_number", "rfq", "rfq_title",
            "rfq_buyer_company", "status", "submission_date",
            "validity_date", "total_amount", "currency",
            "delivery_days", "incoterm"
        ],
        order_by="submission_date desc",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(quotations) > limit
    if has_more:
        quotations = quotations[:limit]

    return {
        "success": True,
        "quotations": quotations,
        "count": len(quotations),
        "has_more": has_more
    }


# =============================================================================
# QUOTATION COMPARISON AND EVALUATION APIs (Buyer)
# =============================================================================

@frappe.whitelist()
def get_rfq_quotations(
    rfq_name: str,
    status: str = None,
    sort_by: str = "total_amount"
) -> Dict[str, Any]:
    """
    Get all quotations for an RFQ.

    Used by buyers to review received quotations.

    Args:
        rfq_name: The RFQ document name
        status: Filter by quotation status
        sort_by: Sort field (total_amount, delivery_days, submission_date)

    Returns:
        dict: {
            "success": True,
            "quotations": [...],
            "count": int
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    filters = {"rfq": rfq_name}
    if status:
        filters["status"] = status
    else:
        # Default: exclude drafts and cancelled
        filters["status"] = ["not in", ["Draft", "Cancelled"]]

    # Validate sort field
    valid_sort_fields = ["total_amount", "delivery_days", "submission_date", "validity_date"]
    if sort_by not in valid_sort_fields:
        sort_by = "total_amount"

    quotations = frappe.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "quotation_number", "seller", "seller_name",
            "seller_company", "status", "submission_date",
            "validity_date", "subtotal", "discount_percentage",
            "discount_amount", "tax_amount", "shipping_cost",
            "total_amount", "currency", "delivery_days",
            "incoterm", "payment_terms", "advance_percentage",
            "production_time_days", "minimum_order_quantity",
            "buyer_evaluation_score"
        ],
        order_by=f"{sort_by} asc" if sort_by != "submission_date" else f"{sort_by} desc"
    )

    return {
        "success": True,
        "quotations": quotations,
        "count": len(quotations)
    }


@frappe.whitelist()
def compare_rfq_quotations(rfq_name: str) -> Dict[str, Any]:
    """
    Get quotation comparison data for an RFQ.

    Returns all submitted quotations with comparison statistics
    to help buyers make informed decisions.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "success": True,
            "rfq": {...},
            "quotations": [...],
            "comparison": {
                "price_range": {"min": float, "max": float, "avg": float},
                "delivery_range": {"min": int, "max": int, "avg": float},
                "best_price": {...},
                "fastest_delivery": {...}
            }
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    # Get RFQ basic info
    rfq = frappe.db.get_value(
        "RFQ", rfq_name,
        ["name", "title", "status", "buyer_company", "preferred_currency",
         "total_quotations", "lowest_quote", "highest_quote"],
        as_dict=True
    )

    if not rfq:
        frappe.throw(_("RFQ not found"))

    # Get quotations
    quotations = frappe.get_all(
        "Quotation",
        filters={
            "rfq": rfq_name,
            "status": ["not in", ["Draft", "Cancelled"]]
        },
        fields=[
            "name", "quotation_number", "seller", "seller_name",
            "seller_company", "status", "total_amount", "currency",
            "delivery_days", "incoterm", "payment_terms",
            "advance_percentage", "validity_date",
            "production_time_days", "minimum_order_quantity",
            "buyer_evaluation_score"
        ],
        order_by="total_amount asc"
    )

    if not quotations:
        return {
            "success": True,
            "rfq": rfq,
            "quotations": [],
            "comparison": None
        }

    # Calculate comparison statistics
    amounts = [flt(q.total_amount) for q in quotations if q.total_amount]
    delivery_days = [cint(q.delivery_days) for q in quotations if q.delivery_days]

    comparison = {
        "price_range": {
            "min": min(amounts) if amounts else None,
            "max": max(amounts) if amounts else None,
            "avg": sum(amounts) / len(amounts) if amounts else None
        },
        "delivery_range": {
            "min": min(delivery_days) if delivery_days else None,
            "max": max(delivery_days) if delivery_days else None,
            "avg": sum(delivery_days) / len(delivery_days) if delivery_days else None
        },
        "total_quotations": len(quotations),
        "best_price": None,
        "fastest_delivery": None
    }

    # Find best price and fastest delivery
    if amounts:
        min_amount = min(amounts)
        for q in quotations:
            if flt(q.total_amount) == min_amount:
                comparison["best_price"] = {
                    "quotation": q.name,
                    "seller": q.seller_name,
                    "amount": q.total_amount
                }
                break

    if delivery_days:
        min_delivery = min(delivery_days)
        for q in quotations:
            if cint(q.delivery_days) == min_delivery:
                comparison["fastest_delivery"] = {
                    "quotation": q.name,
                    "seller": q.seller_name,
                    "days": q.delivery_days
                }
                break

    return {
        "success": True,
        "rfq": rfq,
        "quotations": quotations,
        "comparison": comparison
    }


@frappe.whitelist()
def get_quotation_details(quotation_name: str) -> Dict[str, Any]:
    """
    Get detailed quotation information including items.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Full quotation details with items
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    quotation = frappe.get_doc("Quotation", quotation_name)

    # Get items
    items = []
    for item in quotation.items:
        items.append(item.as_dict())

    return {
        "success": True,
        "quotation": quotation.as_dict(),
        "items": items,
        "item_count": len(items)
    }


@frappe.whitelist()
def select_quotation(
    quotation_name: str,
    evaluation_score: float = None,
    evaluation_notes: str = None,
    reason: str = None
) -> Dict[str, Any]:
    """
    Select a quotation as the winner for an RFQ.

    This marks the quotation as Selected, rejects other quotations,
    and closes the RFQ.

    Args:
        quotation_name: The Quotation document name
        evaluation_score: Optional evaluation score (0-100)
        evaluation_notes: Optional evaluation notes
        reason: Selection reason

    Returns:
        dict: {
            "success": True,
            "quotation_status": "Selected",
            "rfq_status": "Closed"
        }
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    quotation = frappe.get_doc("Quotation", quotation_name)

    # Validate buyer access
    rfq = frappe.get_doc("RFQ", quotation.rfq)
    validate_buyer_access(rfq.buyer)

    # Select the quotation
    quotation.select(
        flt(evaluation_score) if evaluation_score else None,
        evaluation_notes
    )

    # Update RFQ
    rfq.selected_quotation = quotation_name
    rfq.selection_reason = reason
    rfq.status = "Closed"
    rfq.closed_date = now_datetime()
    rfq.save()

    # Reject other quotations
    other_quotations = frappe.get_all(
        "Quotation",
        filters={
            "rfq": quotation.rfq,
            "name": ["!=", quotation_name],
            "status": ["not in", ["Draft", "Cancelled", "Rejected"]]
        }
    )
    for q in other_quotations:
        frappe.db.set_value("Quotation", q.name, "status", "Rejected")

    return {
        "success": True,
        "quotation_status": quotation.status,
        "rfq_status": rfq.status,
        "message": _("Quotation selected successfully")
    }


@frappe.whitelist()
def reject_quotation(
    quotation_name: str,
    reason: str = None,
    evaluation_score: float = None,
    evaluation_notes: str = None
) -> Dict[str, Any]:
    """
    Reject a quotation.

    Args:
        quotation_name: The Quotation document name
        reason: Rejection reason
        evaluation_score: Optional evaluation score
        evaluation_notes: Optional evaluation notes

    Returns:
        dict: {
            "success": True,
            "status": "Rejected"
        }
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required"))

    quotation = frappe.get_doc("Quotation", quotation_name)

    # Validate buyer access
    rfq = frappe.get_doc("RFQ", quotation.rfq)
    validate_buyer_access(rfq.buyer)

    quotation.reject(
        reason,
        flt(evaluation_score) if evaluation_score else None,
        evaluation_notes
    )

    return {
        "success": True,
        "status": quotation.status,
        "message": _("Quotation rejected")
    }


# =============================================================================
# ORDER CREATION APIs
# =============================================================================

@frappe.whitelist()
def create_order_from_rfq(rfq_name: str) -> Dict[str, Any]:
    """
    Create an order from the selected quotation of an RFQ.

    Requires that a quotation has been selected for the RFQ.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "success": True,
            "order": order_name
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    rfq = frappe.get_doc("RFQ", rfq_name)
    validate_buyer_access(rfq.buyer)

    if not rfq.selected_quotation:
        frappe.throw(_("No quotation has been selected for this RFQ"))

    result = rfq.create_order_from_quotation()

    return {
        "success": True,
        "order": result.get("order"),
        "message": result.get("message")
    }


# =============================================================================
# STATISTICS AND ANALYTICS APIs
# =============================================================================

@frappe.whitelist()
def get_rfq_statistics(
    buyer: str = None,
    tenant: str = None,
    date_from: str = None,
    date_to: str = None
) -> Dict[str, Any]:
    """
    Get RFQ statistics for dashboard display.

    Args:
        buyer: Filter by Buyer Profile
        tenant: Filter by tenant
        date_from: Start date
        date_to: End date

    Returns:
        dict: RFQ statistics including counts, averages, trends
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if tenant:
        filters["tenant"] = tenant
    elif not "System Manager" in frappe.get_roles():
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    if date_from and date_to:
        filters["rfq_date"] = ["between", [date_from, date_to]]
    elif date_from:
        filters["rfq_date"] = [">=", date_from]
    elif date_to:
        filters["rfq_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "RFQ",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}
    total = sum(status_dict.values())

    # Get quotation statistics for closed RFQs
    closed_filters = {**filters, "status": "Closed", "selected_quotation": ["is", "set"]}
    closed_with_selection = frappe.db.count("RFQ", closed_filters)

    # Calculate average response time
    avg_quotations = frappe.db.sql("""
        SELECT AVG(total_quotations) as avg_quotations
        FROM `tabRFQ`
        WHERE status IN ('Evaluating', 'Closed')
        AND total_quotations > 0
        {filters}
    """.format(filters="AND buyer = %(buyer)s" if buyer else ""),
    {"buyer": buyer} if buyer else {},
    as_dict=True)

    selection_rate = 0
    if status_dict.get("Closed", 0) > 0:
        selection_rate = closed_with_selection / status_dict["Closed"] * 100

    return {
        "success": True,
        "statistics": {
            "total_rfqs": total,
            "status_breakdown": status_dict,
            "active_rfqs": status_dict.get("Active", 0),
            "evaluating_rfqs": status_dict.get("Evaluating", 0),
            "closed_rfqs": status_dict.get("Closed", 0),
            "cancelled_rfqs": status_dict.get("Cancelled", 0),
            "expired_rfqs": status_dict.get("Expired", 0),
            "average_quotations_per_rfq": flt(
                avg_quotations[0].avg_quotations, 1
            ) if avg_quotations and avg_quotations[0].avg_quotations else 0,
            "selection_rate": flt(selection_rate, 1)
        }
    }


@frappe.whitelist()
def get_seller_rfq_statistics(seller: str = None) -> Dict[str, Any]:
    """
    Get RFQ and quotation statistics for a seller.

    Args:
        seller: Seller Profile name (defaults to current user's seller)

    Returns:
        dict: Seller-specific statistics
    """
    if not seller:
        seller = validate_seller_access()

    # Get quotation counts by status
    quotation_counts = frappe.db.get_all(
        "Quotation",
        filters={"seller": seller},
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    quotation_dict = {q.status: q.count for q in quotation_counts}
    total_quotations = sum(quotation_dict.values())

    # Calculate win rate
    selected = quotation_dict.get("Selected", 0)
    submitted = selected + quotation_dict.get("Rejected", 0)
    win_rate = (selected / submitted * 100) if submitted > 0 else 0

    # Get invitation statistics
    invitations = frappe.db.count(
        "RFQ Invited Seller",
        {"seller": seller}
    )

    pending_invitations = frappe.db.count(
        "RFQ Invited Seller",
        {"seller": seller, "status": "Invited"}
    )

    # Get average quotation value
    avg_value = frappe.db.sql("""
        SELECT AVG(total_amount) as avg_value
        FROM `tabQuotation`
        WHERE seller = %s AND status NOT IN ('Draft', 'Cancelled')
    """, seller, as_dict=True)

    return {
        "success": True,
        "statistics": {
            "total_quotations": total_quotations,
            "quotation_breakdown": quotation_dict,
            "submitted_quotations": quotation_dict.get("Submitted", 0) + quotation_dict.get("Under Review", 0),
            "selected_quotations": selected,
            "rejected_quotations": quotation_dict.get("Rejected", 0),
            "win_rate": flt(win_rate, 1),
            "total_invitations": invitations,
            "pending_invitations": pending_invitations,
            "average_quotation_value": flt(
                avg_value[0].avg_value, 2
            ) if avg_value and avg_value[0].avg_value else 0
        }
    }


# =============================================================================
# UTILITY APIs
# =============================================================================

@frappe.whitelist()
def get_rfq_config() -> Dict[str, Any]:
    """
    Get RFQ configuration options.

    Returns available options for RFQ types, statuses, incoterms, etc.
    Useful for populating dropdown menus in the frontend.

    Returns:
        dict: Configuration options
    """
    return {
        "success": True,
        "config": {
            "rfq_types": RFQ_TYPES,
            "rfq_statuses": RFQ_STATUSES,
            "quotation_statuses": QUOTATION_STATUSES,
            "incoterms": INCOTERMS,
            "payment_terms": PAYMENT_TERMS,
            "priority_levels": ["Low", "Normal", "High", "Urgent"],
            "budget_visibility_options": ["Hidden", "Range", "Exact"],
            "default_validity_days": 30,
            "default_currency": "USD"
        }
    }


@frappe.whitelist()
def check_rfq_deadline(rfq_name: str) -> Dict[str, Any]:
    """
    Check if an RFQ's submission deadline has passed.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: {
            "is_active": bool,
            "deadline": datetime,
            "time_remaining": str
        }
    """
    if not rfq_name:
        frappe.throw(_("RFQ name is required"))

    rfq = frappe.db.get_value(
        "RFQ", rfq_name,
        ["status", "submission_deadline"],
        as_dict=True
    )

    if not rfq:
        frappe.throw(_("RFQ not found"))

    deadline = get_datetime(rfq.submission_deadline)
    now = now_datetime()
    is_active = rfq.status == "Active" and deadline > now

    time_remaining = None
    if is_active:
        diff = deadline - now
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60

        if days > 0:
            time_remaining = f"{days} day(s), {hours} hour(s)"
        elif hours > 0:
            time_remaining = f"{hours} hour(s), {minutes} minute(s)"
        else:
            time_remaining = f"{minutes} minute(s)"

    return {
        "success": True,
        "is_active": is_active,
        "status": rfq.status,
        "deadline": rfq.submission_deadline,
        "time_remaining": time_remaining
    }
