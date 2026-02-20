# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ API Endpoints

REST API for RFQ operations.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, getdate
from typing import Dict, Any, List, Optional
import json


def _response(success: bool, data: Any = None, message: str = None, errors: List = None) -> Dict:
    """Standard API response format."""
    return {
        "success": success,
        "data": data,
        "message": message,
        "errors": errors or []
    }


@frappe.whitelist()
def create_rfq(
    title: str,
    description: str,
    category: str,
    target_type: str = "Public",
    deadline: str = None,
    budget_min: float = None,
    budget_max: float = None,
    quantity: float = None,
    unit: str = None,
    delivery_date: str = None,
    delivery_location: str = None,
    requires_nda: bool = False,
    nda_template: str = None,
    items: str = None,
    target_sellers: str = None,
    target_categories: str = None
) -> Dict:
    """
    Create a new RFQ.

    Args:
        title: RFQ title
        description: Detailed description
        category: Primary category
        target_type: Public/Category/Selected
        deadline: Quote deadline
        budget_min: Minimum budget
        budget_max: Maximum budget
        quantity: Required quantity
        unit: Unit of measure
        delivery_date: Expected delivery date
        delivery_location: Delivery location
        requires_nda: Whether NDA is required
        nda_template: NDA template if required
        items: JSON array of RFQ items
        target_sellers: JSON array of seller names (for Selected type)
        target_categories: JSON array of category names (for Category type)

    Returns:
        API response with created RFQ
    """
    try:
        # Get current user's buyer profile
        buyer = frappe.db.get_value(
            "Buyer Profile",
            {"user": frappe.session.user},
            "name"
        )
        if not buyer:
            return _response(False, message=_("No buyer profile found for current user"))

        # Validate NDA requirements
        if requires_nda and not nda_template:
            return _response(False, message=_("NDA template is required when NDA is enabled"))

        # Create RFQ
        rfq = frappe.get_doc({
            "doctype": "RFQ",
            "buyer": buyer,
            "title": title,
            "description": description,
            "category": category,
            "target_type": target_type,
            "deadline": deadline,
            "budget_min": budget_min,
            "budget_max": budget_max,
            "quantity": quantity,
            "unit": unit,
            "delivery_date": delivery_date,
            "delivery_location": delivery_location,
            "requires_nda": requires_nda,
            "nda_template": nda_template,
            "status": "Draft"
        })

        # Add items
        if items:
            items_list = json.loads(items) if isinstance(items, str) else items
            for item in items_list:
                rfq.append("items", {
                    "item_name": item.get("item_name"),
                    "description": item.get("description"),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                    "specifications": item.get("specifications")
                })

        # Add target sellers
        if target_sellers and target_type == "Selected":
            sellers_list = json.loads(target_sellers) if isinstance(target_sellers, str) else target_sellers
            for seller in sellers_list:
                rfq.append("target_sellers", {"seller": seller})

        # Add target categories
        if target_categories and target_type == "Category":
            cats_list = json.loads(target_categories) if isinstance(target_categories, str) else target_categories
            for cat in cats_list:
                rfq.append("target_categories", {"category": cat})

        rfq.insert()
        frappe.db.commit()

        return _response(True, data={"name": rfq.name, "rfq_code": rfq.rfq_code})

    except Exception as e:
        frappe.log_error(f"Error creating RFQ: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def publish_rfq(rfq_name: str) -> Dict:
    """
    Publish an RFQ to make it visible to sellers.

    Args:
        rfq_name: RFQ document name

    Returns:
        API response
    """
    try:
        rfq = frappe.get_doc("RFQ", rfq_name)

        # Validate ownership
        if rfq.buyer != _get_current_buyer():
            return _response(False, message=_("You don't have permission to publish this RFQ"))

        if rfq.status != "Draft":
            return _response(False, message=_("Only draft RFQs can be published"))

        if not rfq.deadline:
            return _response(False, message=_("Deadline is required to publish"))

        rfq.status = "Published"
        rfq.published_at = now_datetime()
        rfq.save()
        frappe.db.commit()

        # TODO: Notify target sellers

        return _response(True, message=_("RFQ published successfully"))

    except Exception as e:
        frappe.log_error(f"Error publishing RFQ: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def submit_quote(
    rfq_name: str,
    price: float,
    currency: str = "TRY",
    terms: str = None,
    delivery_days: int = None,
    valid_until: str = None,
    notes: str = None
) -> Dict:
    """
    Submit a quote for an RFQ.

    Args:
        rfq_name: RFQ document name
        price: Quote price
        currency: Currency code
        terms: Quote terms
        delivery_days: Estimated delivery days
        valid_until: Quote validity date
        notes: Additional notes

    Returns:
        API response with quote details
    """
    try:
        from tradehub_commerce.tradehub_commerce.rfq_utils.nda_integration import check_nda_signed, create_nda_for_rfq

        rfq = frappe.get_doc("RFQ", rfq_name)
        seller = _get_current_seller()

        if not seller:
            return _response(False, message=_("No seller profile found for current user"))

        # Check RFQ status
        if rfq.status not in ["Published", "Quoting"]:
            return _response(False, message=_("This RFQ is not accepting quotes"))

        # Check deadline
        if rfq.deadline and now_datetime() > rfq.deadline:
            return _response(False, message=_("Quote deadline has passed"))

        # Check NDA requirement
        if rfq.requires_nda and not check_nda_signed(rfq_name, seller):
            # Create NDA if not exists
            nda_instance = create_nda_for_rfq(rfq_name, seller)
            return _response(
                False,
                message=_("NDA signature required before submitting quote"),
                data={"nda_instance": nda_instance}
            )

        # Check for existing quote
        existing = frappe.db.exists("RFQ Quote", {"rfq": rfq_name, "seller": seller})
        if existing:
            return _response(
                False,
                message=_("You have already submitted a quote. Use revise_quote to update it."),
                data={"existing_quote": existing}
            )

        # Create quote
        quote = frappe.get_doc({
            "doctype": "RFQ Quote",
            "rfq": rfq_name,
            "seller": seller,
            "price": price,
            "currency": currency,
            "terms": terms,
            "delivery_days": delivery_days,
            "valid_until": valid_until,
            "notes": notes,
            "status": "Submitted"
        })
        quote.insert()

        # Update RFQ status if first quote
        if rfq.status == "Published":
            rfq.status = "Quoting"
            rfq.save()

        frappe.db.commit()

        return _response(True, data={"name": quote.name}, message=_("Quote submitted successfully"))

    except Exception as e:
        frappe.log_error(f"Error submitting quote: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def revise_quote(
    quote_name: str,
    new_price: float = None,
    new_terms: str = None,
    new_delivery_days: int = None,
    reason: str = None
) -> Dict:
    """
    Revise an existing quote.

    Args:
        quote_name: RFQ Quote document name
        new_price: New quote price
        new_terms: New terms
        new_delivery_days: New delivery estimate
        reason: Reason for revision

    Returns:
        API response
    """
    try:
        quote = frappe.get_doc("RFQ Quote", quote_name)
        seller = _get_current_seller()

        if quote.seller != seller:
            return _response(False, message=_("You don't have permission to revise this quote"))

        if quote.status not in ["Submitted", "Under Review"]:
            return _response(False, message=_("This quote cannot be revised"))

        # Create revision record
        revision_no = frappe.db.count("RFQ Quote Revision", {"original_quote": quote_name}) + 1

        revision = frappe.get_doc({
            "doctype": "RFQ Quote Revision",
            "original_quote": quote_name,
            "revision_no": revision_no,
            "previous_price": quote.price,
            "new_price": new_price or quote.price,
            "previous_terms": quote.terms,
            "new_terms": new_terms or quote.terms,
            "previous_delivery_days": quote.delivery_days,
            "new_delivery_days": new_delivery_days or quote.delivery_days,
            "reason": reason,
            "revised_by": frappe.session.user,
            "revised_at": now_datetime()
        })
        revision.insert()

        # Update quote
        if new_price:
            quote.price = new_price
        if new_terms:
            quote.terms = new_terms
        if new_delivery_days:
            quote.delivery_days = new_delivery_days

        quote.revision_count = revision_no
        quote.last_revised_at = now_datetime()
        quote.save()

        frappe.db.commit()

        return _response(True, data={"revision": revision.name}, message=_("Quote revised successfully"))

    except Exception as e:
        frappe.log_error(f"Error revising quote: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def accept_quote(rfq_name: str, quote_name: str) -> Dict:
    """
    Accept a quote for an RFQ.

    Args:
        rfq_name: RFQ document name
        quote_name: RFQ Quote document name

    Returns:
        API response
    """
    try:
        rfq = frappe.get_doc("RFQ", rfq_name)
        buyer = _get_current_buyer()

        if rfq.buyer != buyer:
            return _response(False, message=_("You don't have permission to accept quotes for this RFQ"))

        if rfq.status not in ["Quoting", "Negotiation"]:
            return _response(False, message=_("This RFQ is not in a state where quotes can be accepted"))

        quote = frappe.get_doc("RFQ Quote", quote_name)

        if quote.rfq != rfq_name:
            return _response(False, message=_("Quote does not belong to this RFQ"))

        # Update quote status
        quote.status = "Accepted"
        quote.accepted_at = now_datetime()
        quote.save()

        # Update RFQ status
        rfq.status = "Accepted"
        rfq.accepted_quote = quote_name
        rfq.save()

        # Reject other quotes
        other_quotes = frappe.get_all(
            "RFQ Quote",
            filters={"rfq": rfq_name, "name": ["!=", quote_name]}
        )
        for q in other_quotes:
            frappe.db.set_value("RFQ Quote", q.name, "status", "Rejected")

        frappe.db.commit()

        return _response(True, message=_("Quote accepted successfully"))

    except Exception as e:
        frappe.log_error(f"Error accepting quote: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def send_message(
    rfq_name: str,
    message: str,
    thread_name: str = None,
    recipient_seller: str = None
) -> Dict:
    """
    Send a message in RFQ conversation.

    Args:
        rfq_name: RFQ document name
        message: Message content
        thread_name: Existing thread name (optional)
        recipient_seller: Seller to message (for buyer)

    Returns:
        API response
    """
    try:
        rfq = frappe.get_doc("RFQ", rfq_name)
        current_seller = _get_current_seller()
        current_buyer = _get_current_buyer()

        # Determine sender type and recipient
        if current_buyer == rfq.buyer:
            sender_type = "Buyer"
            sender = current_buyer
            recipient = recipient_seller
        elif current_seller:
            sender_type = "Seller"
            sender = current_seller
            recipient = rfq.buyer
        else:
            return _response(False, message=_("You don't have permission to send messages"))

        # Find or create thread
        if not thread_name:
            # Look for existing thread
            existing_thread = frappe.get_all(
                "RFQ Message Thread",
                filters={
                    "rfq": rfq_name,
                    "seller": current_seller or recipient_seller
                },
                limit=1
            )

            if existing_thread:
                thread_name = existing_thread[0].name
            else:
                # Create new thread
                thread = frappe.get_doc({
                    "doctype": "RFQ Message Thread",
                    "rfq": rfq_name,
                    "buyer": rfq.buyer,
                    "seller": current_seller or recipient_seller,
                    "status": "Open"
                })
                thread.insert()
                thread_name = thread.name

        # Create message
        msg = frappe.get_doc({
            "doctype": "RFQ Message",
            "thread": thread_name,
            "sender_type": sender_type,
            "sender": sender,
            "recipient": recipient,
            "message": message,
            "sent_at": now_datetime()
        })
        msg.insert()

        # Update thread
        frappe.db.set_value("RFQ Message Thread", thread_name, "last_message_at", now_datetime())

        frappe.db.commit()

        # Real-time notification
        recipient_user = _get_user_for_party(recipient, "Buyer" if sender_type == "Seller" else "Seller")
        if recipient_user:
            frappe.publish_realtime(
                event="rfq_message",
                message={"thread": thread_name, "message": msg.as_dict()},
                user=recipient_user
            )

        return _response(True, data={"message": msg.name, "thread": thread_name})

    except Exception as e:
        frappe.log_error(f"Error sending message: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_rfq_list(
    status: str = None,
    category: str = None,
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get list of RFQs.

    Args:
        status: Filter by status
        category: Filter by category
        limit: Number of results
        offset: Pagination offset

    Returns:
        API response with RFQ list
    """
    try:
        filters = {}
        seller = _get_current_seller()
        buyer = _get_current_buyer()

        if buyer:
            # Buyer sees their own RFQs
            filters["buyer"] = buyer
        elif seller:
            # Seller sees public and targeted RFQs
            filters["status"] = ["in", ["Published", "Quoting", "Negotiation"]]
            # TODO: Add filter for seller targeting

        if status:
            filters["status"] = status
        if category:
            filters["category"] = category

        rfqs = frappe.get_all(
            "RFQ",
            filters=filters,
            fields=[
                "name", "rfq_code", "title", "category", "target_type",
                "deadline", "budget_min", "budget_max", "status",
                "requires_nda", "creation"
            ],
            order_by="creation desc",
            limit=limit,
            start=offset
        )

        total = frappe.db.count("RFQ", filters)

        return _response(True, data={"rfqs": rfqs, "total": total})

    except Exception as e:
        frappe.log_error(f"Error getting RFQ list: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_quotes(rfq_name: str) -> Dict:
    """
    Get quotes for an RFQ.

    Args:
        rfq_name: RFQ document name

    Returns:
        API response with quotes
    """
    try:
        rfq = frappe.get_doc("RFQ", rfq_name)
        buyer = _get_current_buyer()
        seller = _get_current_seller()

        # Buyer can see all quotes
        if buyer == rfq.buyer:
            quotes = frappe.get_all(
                "RFQ Quote",
                filters={"rfq": rfq_name},
                fields=[
                    "name", "seller", "price", "currency", "terms",
                    "delivery_days", "valid_until", "status",
                    "revision_count", "creation"
                ]
            )
        # Seller can only see their own quote
        elif seller:
            quotes = frappe.get_all(
                "RFQ Quote",
                filters={"rfq": rfq_name, "seller": seller},
                fields=[
                    "name", "seller", "price", "currency", "terms",
                    "delivery_days", "valid_until", "status",
                    "revision_count", "creation"
                ]
            )
        else:
            return _response(False, message=_("You don't have permission to view quotes"))

        return _response(True, data={"quotes": quotes})

    except Exception as e:
        frappe.log_error(f"Error getting quotes: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_messages(thread_name: str) -> Dict:
    """
    Get messages for a thread.

    Args:
        thread_name: RFQ Message Thread name

    Returns:
        API response with messages
    """
    try:
        thread = frappe.get_doc("RFQ Message Thread", thread_name)

        # Verify access
        buyer = _get_current_buyer()
        seller = _get_current_seller()

        if thread.buyer != buyer and thread.seller != seller:
            return _response(False, message=_("You don't have permission to view this thread"))

        messages = frappe.get_all(
            "RFQ Message",
            filters={"thread": thread_name},
            fields=["name", "sender_type", "sender", "message", "sent_at", "read_at"],
            order_by="sent_at asc"
        )

        # Mark unread messages as read
        for msg in messages:
            if not msg.get("read_at"):
                frappe.db.set_value("RFQ Message", msg["name"], "read_at", now_datetime())

        return _response(True, data={"messages": messages, "thread": thread.as_dict()})

    except Exception as e:
        frappe.log_error(f"Error getting messages: {str(e)}")
        return _response(False, message=str(e))


# Helper functions
def _get_current_buyer() -> Optional[str]:
    """Get current user's buyer profile."""
    return frappe.db.get_value("Buyer Profile", {"user": frappe.session.user}, "name")


def _get_current_seller() -> Optional[str]:
    """Get current user's seller profile."""
    return frappe.db.get_value("Seller Profile", {"user": frappe.session.user}, "name")


def _get_user_for_party(party: str, party_type: str) -> Optional[str]:
    """Get user for a buyer/seller profile."""
    if party_type == "Buyer":
        return frappe.db.get_value("Buyer Profile", party, "user")
    else:
        return frappe.db.get_value("Seller Profile", party, "user")
